"""
clinical/views.py

Phase 3 booking views + patient doctor-discovery views.

Booking (patient role):
  POST   /appointments/hold              HoldView
  POST   /appointments/:id/confirm       ConfirmView
  DELETE /appointments/:id/hold          CancelHoldView
  POST   /appointments/:id/cancel        CancelView
  POST   /appointments/:id/reschedule    RescheduleView
  GET    /appointments/me                AppointmentListView
  GET    /appointments/:id               AppointmentDetailView

Doctor-facing:
  GET    /doctor/appointments/:id        DoctorAppointmentDetailView

Discovery (patient role):
  GET    /doctors                        DoctorListView
  GET    /doctors/:id/slots              DoctorSlotListView

Rules:
  - All patient-owned queries go through ScopedQuerysetMixin.
  - No appointment status is written except through state_machine functions.
  - Booking confirmation uses SELECT FOR UPDATE on AppointmentSlot.booked_count
    inside a transaction so Postgres stays the source of truth.
  - Redis DECR happens on hold; INCR happens on abandon/cancel/no-show.
"""
from __future__ import annotations

import datetime
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import UserRole
from apps.accounts.permissions import IsDoctor, IsNotForcedReset, IsPatient
from apps.clinical.models import Appointment, AppointmentStatus, CancelReason, PreVisitAttachment
from apps.clinical.serializers import (
    AppointmentListItemSerializer,
    AppointmentSerializer,
    AttachmentUploadSerializer,
    CancelSerializer,
    ConfirmSerializer,
    DoctorAppointmentCardSerializer,
    HoldSerializer,
    PreVisitAttachmentSerializer,
    RescheduleSerializer,
)
from apps.clinical.state_machine import (
    cancel_confirmed,
    cancel_hold,
    confirm,
)
from apps.scheduling.models import AppointmentSlot, DoctorAttendance, DoctorLeave, DoctorProfile
from apps.scheduling.serializers import AppointmentSlotSerializer, DoctorProfileSerializer
from apps.scheduling.services import try_hold_slot
from common.scoping import ScopedQuerysetMixin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOLD_TTL_SECONDS: int = getattr(settings, "SLOT_HOLD_TTL_SECONDS", 600)


def _get_own_appointment(request: Request, appointment_id: str) -> Appointment:
    """
    Load an appointment that belongs to the requesting patient.
    Returns 404 — never 403 — to avoid confirming existence.
    """
    try:
        return (
            Appointment.objects
            .select_related("slot", "doctor__doctor_profile", "hospital")
            .get(id=appointment_id, patient=request.user)
        )
    except Appointment.DoesNotExist:
        raise NotFound("Appointment not found.") from None


def _next_token(slot: AppointmentSlot) -> int:
    """1-based booking order within the slot."""
    used = Appointment.objects.filter(
        slot=slot,
        status__in=[AppointmentStatus.CONFIRMED, AppointmentStatus.COMPLETED],
    ).count()
    return used + 1


# ---------------------------------------------------------------------------
# Booking — hold
# ---------------------------------------------------------------------------

class HoldView(APIView):
    """
    POST /appointments/hold

    1. Validate slot exists and belongs to the doctor.
    2. DECR Redis counter (fast-path full check).
    3. Create an Appointment row with status=held + held_until TTL.
    4. Return the appointment so the frontend can start the symptom form.

    If Redis is unavailable, falls back to Postgres booked_count check.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def post(self, request: Request) -> Response:
        serializer = HoldSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        slot: AppointmentSlot = d["slot"]

        # Redis DECR — grants or denies the hold
        if not try_hold_slot(slot):
            return Response(
                {"error": {"code": "slot_full", "message": "This slot is fully booked."}},
                status=status.HTTP_409_CONFLICT,
            )

        held_until = timezone.now() + datetime.timedelta(seconds=HOLD_TTL_SECONDS)

        appointment = Appointment.objects.create(
            patient    = request.user,
            doctor     = slot.doctor.user,
            slot       = slot,
            hospital   = slot.hospital,
            status     = AppointmentStatus.HELD,
            held_until = held_until,
        )

        logger.info(
            "Hold created: appointment=%s slot=%s patient=%s held_until=%s",
            appointment.id, slot.id, request.user.id, held_until,
        )
        return Response(AppointmentSerializer(appointment).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Booking — confirm
# ---------------------------------------------------------------------------

class ConfirmView(APIView):
    """
    POST /appointments/:id/confirm

    1. Validate hold belongs to patient and is not expired.
    2. Increment AppointmentSlot.booked_count under SELECT FOR UPDATE.
    3. Transition held → confirmed via state_machine.confirm().
    4. Enqueue pre-visit LLM job (Phase 4 — currently a no-op).
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def post(self, request: Request, appointment_id: str) -> Response:
        appointment = _get_own_appointment(request, appointment_id)

        if appointment.status != AppointmentStatus.HELD:
            raise ValidationError(
                {"status": f"Cannot confirm an appointment with status '{appointment.status}'."}
            )

        if appointment.held_until and appointment.held_until < timezone.now():
            raise ValidationError({"status": "This hold has expired. Please start a new booking."})

        serializer = ConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        symptom_text = serializer.validated_data["symptom_text"]

        with transaction.atomic():
            slot = AppointmentSlot.objects.select_for_update().get(id=appointment.slot_id)

            # Double-check capacity under the lock
            if slot.booked_count >= slot.capacity:
                # Redis said ok but Postgres disagrees — INCR back and reject
                from common.redis_client import slot_counter_incr
                slot_counter_incr(str(slot.id))
                return Response(
                    {"error": {"code": "slot_full", "message": "This slot is now fully booked."}},
                    status=status.HTTP_409_CONFLICT,
                )

            token = _next_token(slot)
            slot.booked_count += 1
            slot.save(update_fields=["booked_count"])

            confirm(appointment, symptom_text=symptom_text, token=token)

        # Phase 6: fire booking_confirmed notification (best-effort, after commit)
        try:
            from apps.notifications.events import fire_notification
            from apps.notifications.models import NotificationEventType
            fire_notification(NotificationEventType.BOOKING_CONFIRMED, appointment)
        except Exception as exc:
            logger.warning("state_machine.confirm: notification failed for %s: %s", appointment.id, exc)

        # Phase 4: enqueue pre-visit LLM job — fire-and-forget, never blocks confirm
        try:
            from apps.clinical.tasks import pre_visit_llm_job
            pre_visit_llm_job.delay(str(appointment.id))
        except Exception as enqueue_exc:
            # Celery may not be running in dev — log and continue
            logger.warning(
                "Could not enqueue pre_visit_llm_job for %s: %s",
                appointment.id, enqueue_exc,
            )

        appointment.refresh_from_db()
        return Response(AppointmentSerializer(appointment).data)


# ---------------------------------------------------------------------------
# Booking — cancel hold (before confirming)
# ---------------------------------------------------------------------------

class CancelHoldView(APIView):
    """
    DELETE /appointments/:id/hold

    Abandons an unconfirmed hold. Redis counter is incremented back.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def delete(self, request: Request, appointment_id: str) -> Response:
        appointment = _get_own_appointment(request, appointment_id)
        if appointment.status != AppointmentStatus.HELD:
            raise ValidationError(
                {"status": "Only held appointments can be abandoned this way."}
            )
        cancel_hold(appointment)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Booking — cancel confirmed appointment
# ---------------------------------------------------------------------------

class CancelView(APIView):
    """
    POST /appointments/:id/cancel

    Patient-initiated cancellation of a confirmed appointment.
    Frees Postgres booked_count + Redis counter.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def post(self, request: Request, appointment_id: str) -> Response:
        appointment = _get_own_appointment(request, appointment_id)
        if appointment.status != AppointmentStatus.CONFIRMED:
            raise ValidationError(
                {"status": f"Cannot cancel an appointment with status '{appointment.status}'."}
            )
        cancel_confirmed(appointment, reason=CancelReason.PATIENT_INITIATED)
        appointment.refresh_from_db()
        return Response(AppointmentSerializer(appointment).data)


# ---------------------------------------------------------------------------
# Booking — reschedule
# ---------------------------------------------------------------------------

class RescheduleView(APIView):
    """
    POST /appointments/:id/reschedule

    Cancel the current confirmed appointment and hold a new slot.
    The original symptom_text is carried forward automatically.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def post(self, request: Request, appointment_id: str) -> Response:
        old = _get_own_appointment(request, appointment_id)
        if old.status != AppointmentStatus.CONFIRMED:
            raise ValidationError(
                {"status": f"Only confirmed appointments can be rescheduled (current: '{old.status}')."}
            )

        serializer = RescheduleSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        new_slot: AppointmentSlot = serializer.validated_data["new_slot"]

        # Try to hold the new slot first (DECR Redis)
        if not try_hold_slot(new_slot):
            return Response(
                {"error": {"code": "slot_full", "message": "The new slot is fully booked."}},
                status=status.HTTP_409_CONFLICT,
            )

        held_until = timezone.now() + datetime.timedelta(seconds=HOLD_TTL_SECONDS)

        with transaction.atomic():
            # Cancel old — frees its Postgres count + Redis counter
            cancel_confirmed(old, reason=CancelReason.PATIENT_INITIATED)

            # Create new hold carrying symptom text forward
            new_appointment = Appointment.objects.create(
                patient           = request.user,
                doctor            = new_slot.doctor.user,
                slot              = new_slot,
                hospital          = new_slot.hospital,
                status            = AppointmentStatus.HELD,
                held_until        = held_until,
                symptom_text      = old.symptom_text,
                original_request  = old,
            )

        return Response(
            AppointmentSerializer(new_appointment).data,
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Patient appointment list
# ---------------------------------------------------------------------------

class AppointmentListView(ScopedQuerysetMixin, APIView):
    """
    GET /appointments/me?status=upcoming|past|all

    Returns the requesting patient's appointments, scoped by patient_id.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        status_filter = request.query_params.get("status", "all")

        qs = self.scope(
            Appointment.objects
            .select_related("slot", "doctor__doctor_profile", "hospital")
            .order_by("-slot__date", "-slot__slot_start")
        )

        if status_filter == "upcoming":
            qs = qs.filter(
                status__in=[AppointmentStatus.HELD, AppointmentStatus.CONFIRMED],
                slot__date__gte=datetime.date.today(),
            )
        elif status_filter == "past":
            qs = qs.filter(
                status__in=[
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.CANCELLED,
                    AppointmentStatus.NO_SHOW,
                ]
            )

        return Response(AppointmentListItemSerializer(qs, many=True).data)


# ---------------------------------------------------------------------------
# Patient appointment detail
# ---------------------------------------------------------------------------

class AppointmentDetailView(ScopedQuerysetMixin, APIView):
    """
    GET /appointments/:id

    Full detail incl. post-visit summary (Phase 5) once approved.
    Scoped — patient A cannot fetch patient B's appointment.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request, appointment_id: str) -> Response:
        appointment = self.scope_or_404(
            Appointment.objects.select_related(
                "slot", "doctor__doctor_profile", "hospital"
            ),
            id=appointment_id,
        )
        return Response(AppointmentSerializer(appointment).data)


# ---------------------------------------------------------------------------
# Doctor appointment detail
# ---------------------------------------------------------------------------

class DoctorAppointmentDetailView(APIView):
    """
    GET /doctor/appointments/:id

    Returns the full patient card for the doctor, including symptom text
    and AI pre-visit summary status.
    Scoped by hospital_id (doctor sees only their hospital's appointments).
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def get(self, request: Request, appointment_id: str) -> Response:
        try:
            appointment = Appointment.objects.select_related(
                "patient", "slot", "hospital"
            ).prefetch_related("attachments").get(
                id=appointment_id,
                doctor=request.user,
                hospital=request.user.hospital,
            )
        except Appointment.DoesNotExist:
            raise NotFound("Appointment not found.") from None
        return Response(
            DoctorAppointmentCardSerializer(
                appointment, context={"request": request}
            ).data
        )


# ---------------------------------------------------------------------------
# Task 9 — Patient discovery: GET /doctors  &  GET /doctors/:id/slots
# ---------------------------------------------------------------------------

class DoctorListView(APIView):
    """
    GET /doctors?specialization=&date_from=&date_to=&hospital_id=

    Returns active doctors with their next available slot shown.
    Patients are not tied to one hospital so hospital_id is optional filter.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        specialization = request.query_params.get("specialization", "").strip()
        date_from_str  = request.query_params.get("date_from", "")
        date_to_str    = request.query_params.get("date_to", "")
        hospital_id    = request.query_params.get("hospital_id", "").strip()

        profiles = DoctorProfile.objects.select_related(
            "user", "user__hospital", "shift_config"
        ).filter(is_active=True)

        if specialization:
            profiles = profiles.filter(specialization__icontains=specialization)
        if hospital_id:
            profiles = profiles.filter(user__hospital_id=hospital_id)

        today = datetime.date.today()
        try:
            date_from = datetime.date.fromisoformat(date_from_str) if date_from_str else today
            date_to   = datetime.date.fromisoformat(date_to_str)   if date_to_str   else today + datetime.timedelta(days=30)
        except ValueError:
            raise ValidationError({"date_from": "Invalid date format. Use YYYY-MM-DD."})

        result = []
        for profile in profiles:
            next_slot = _next_available_slot(profile, date_from, date_to)
            data = DoctorProfileSerializer(profile).data
            data["next_available_slot"] = (
                _slot_summary(next_slot) if next_slot else None
            )
            result.append(data)

        # Sort: doctors with an available slot first
        result.sort(key=lambda d: (d["next_available_slot"] is None, ))
        return Response(result)


class DoctorSlotListView(APIView):
    """
    GET /doctors/:doctor_id/slots?date=YYYY-MM-DD

    Returns all slots for the given doctor on the given date with
    true_remaining capacity. Unavailable slots (leave / attendance) are
    flagged but still returned so the frontend can show "unavailable" state.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request, doctor_id: str) -> Response:
        date_str = request.query_params.get("date", "")
        try:
            target_date = (
                datetime.date.fromisoformat(date_str)
                if date_str
                else datetime.date.today()
            )
        except ValueError:
            raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD."})

        try:
            profile = DoctorProfile.objects.select_related(
                "user", "shift_config"
            ).get(user_id=doctor_id, is_active=True)
        except DoctorProfile.DoesNotExist:
            raise NotFound("Doctor not found.") from None

        slots = AppointmentSlot.objects.filter(
            doctor=profile, date=target_date
        ).order_by("slot_start")

        on_leave = DoctorLeave.objects.filter(
            doctor=profile, date=target_date
        ).exists()

        absent_shifts = set(
            DoctorAttendance.objects.filter(
                doctor=profile,
                date=target_date,
                status="absent",
            ).values_list("shift", flat=True)
        )

        slot_data = []
        for slot in slots:
            # Determine shift (morning = before shift_2_start)
            shift = "morning"
            try:
                if slot.slot_start >= profile.shift_config.shift_2_start:
                    shift = "afternoon"
            except Exception:
                pass

            unavailable = on_leave or (shift in absent_shifts)
            serialized  = AppointmentSlotSerializer(slot).data
            serialized["shift"]       = shift
            serialized["unavailable"] = unavailable
            slot_data.append(serialized)

        return Response({
            "doctor_id": str(doctor_id),
            "date":      target_date.isoformat(),
            "slots":     slot_data,
        })


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_available_slot(
    profile: DoctorProfile,
    date_from: datetime.date,
    date_to: datetime.date,
) -> AppointmentSlot | None:
    """Return the earliest open slot for *profile* in the date range."""
    on_leave_dates = set(
        DoctorLeave.objects.filter(
            doctor=profile,
            date__range=(date_from, date_to),
        ).values_list("date", flat=True)
    )
    absent_slots = set(
        DoctorAttendance.objects.filter(
            doctor=profile,
            date__range=(date_from, date_to),
            status="absent",
        ).values_list("date", flat=True)
    )

    return (
        AppointmentSlot.objects
        .filter(
            doctor=profile,
            date__range=(date_from, date_to),
        )
        .exclude(date__in=on_leave_dates)
        .filter(booked_count__lt=models_F("capacity"))
        .order_by("date", "slot_start")
        .first()
    )


def _slot_summary(slot: AppointmentSlot) -> dict:
    return {
        "slot_id":    str(slot.id),
        "date":       slot.date.isoformat(),
        "slot_start": str(slot.slot_start)[:5],
        "slot_end":   str(slot.slot_end)[:5],
        "remaining":  slot.true_remaining,
    }


# late import to avoid circular at module load
from django.db.models import F as models_F  # noqa: E402


# ---------------------------------------------------------------------------
# Phase 4 — Attachment CRUD
# ---------------------------------------------------------------------------

class AttachmentListCreateView(APIView):
    """
    GET  /appointments/:id/attachments   — list attachments (patient sees own; doctor sees theirs)
    POST /appointments/:id/attachments   — upload a file (patient only, multipart/form-data)
    """
    permission_classes = [IsAuthenticated, IsNotForcedReset]

    def _get_appointment(self, request: Request, appointment_id: str) -> Appointment:
        """
        Patients can only access their own appointments.
        Doctors can access appointments at their hospital.
        """
        user = request.user
        try:
            if user.role == "patient":
                return Appointment.objects.get(id=appointment_id, patient=user)
            if user.role == "doctor":
                return Appointment.objects.get(
                    id=appointment_id,
                    doctor=user,
                    hospital=user.hospital,
                )
        except Appointment.DoesNotExist:
            pass
        raise NotFound("Appointment not found.")

    def get(self, request: Request, appointment_id: str) -> Response:
        appointment = self._get_appointment(request, appointment_id)
        qs = PreVisitAttachment.objects.filter(
            appointment=appointment
        ).order_by("uploaded_at")
        return Response(
            PreVisitAttachmentSerializer(qs, many=True, context={"request": request}).data
        )

    def post(self, request: Request, appointment_id: str) -> Response:
        # Upload is patient-only
        if request.user.role != "patient":
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Only patients can upload attachments.")

        appointment = self._get_appointment(request, appointment_id)

        # Only allowed on held or confirmed appointments
        if appointment.status not in (
            AppointmentStatus.HELD, AppointmentStatus.CONFIRMED
        ):
            raise ValidationError(
                {"status": "Attachments can only be added to active appointments."}
            )

        # Max 5 attachments per appointment
        existing = PreVisitAttachment.objects.filter(appointment=appointment).count()
        if existing >= 5:
            raise ValidationError(
                {"file": "Maximum 5 attachments per appointment."}
            )

        serializer = AttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = serializer.validated_data["file"]

        attachment = PreVisitAttachment.objects.create(
            appointment       = appointment,
            uploaded_by       = request.user,
            file              = uploaded_file,
            file_type         = uploaded_file._resolved_file_type,
            original_filename = uploaded_file._original_filename,
            file_size_bytes   = uploaded_file.size,
        )
        return Response(
            PreVisitAttachmentSerializer(attachment, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class AttachmentDeleteView(APIView):
    """
    DELETE /appointments/:id/attachments/:att_id

    Only the uploading patient can delete their own attachment.
    Doctors and admins cannot delete patient files.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def delete(self, request: Request, appointment_id: str, attachment_id: str) -> Response:
        try:
            attachment = PreVisitAttachment.objects.select_related("appointment").get(
                id=attachment_id,
                appointment_id=appointment_id,
                appointment__patient=request.user,
            )
        except PreVisitAttachment.DoesNotExist:
            raise NotFound("Attachment not found.")

        # Delete the file from disk too
        if attachment.file:
            try:
                attachment.file.delete(save=False)
            except Exception:
                pass  # best effort — the DB row is what matters

        attachment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Phase 5 — Consultation, summary, medicine catalog views
# ---------------------------------------------------------------------------

from apps.clinical.models import (   # noqa: E402  (needed for Phase 5 views)
    MedicineCatalog,
    MedicineStatus,
    Prescription,
    SummaryStatus,
    VisitNote,
)
from apps.clinical.serializers import (   # noqa: E402
    ConsultationSerializer,
    MedicineCatalogSerializer,
    MedicineCreateSerializer,
    PostVisitSummarySerializer,
    PrescriptionReadSerializer,
    SummaryApproveSerializer,
    SummaryDraftSerializer,
)
from apps.clinical.state_machine import complete as sm_complete  # noqa: E402
from apps.clinical.state_machine import mark_summary_approved    # noqa: E402
from apps.accounts.permissions import IsAdmin, IsAdminOrDoctor   # noqa: E402


class ConsultationView(APIView):
    """
    POST /doctor/appointments/:id/consultation

    Atomically:
      1. Create/update VisitNote
      2. Replace all Prescription rows
      3. Transition confirmed → completed  (state_machine.complete)
      4. Enqueue post_visit_llm_job (fire-and-forget)

    No partial saves — entire operation is in one transaction.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def post(self, request: Request, appointment_id: str) -> Response:
        try:
            appointment = Appointment.objects.select_related(
                "slot", "hospital"
            ).get(
                id=appointment_id,
                doctor=request.user,
                hospital=request.user.hospital,
                status=AppointmentStatus.CONFIRMED,
            )
        except Appointment.DoesNotExist:
            raise NotFound(
                "Confirmed appointment not found. "
                "Only confirmed appointments can be completed."
            ) from None

        serializer = ConsultationSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        with transaction.atomic():
            # ── VisitNote (upsert) ───────────────────────────────────────────
            VisitNote.objects.update_or_create(
                appointment=appointment,
                defaults={"notes": d["notes"], "created_by": request.user},
            )

            # ── Prescriptions (replace) ──────────────────────────────────────
            Prescription.objects.filter(appointment=appointment).delete()
            for i, row in enumerate(d["prescriptions"]):
                med = MedicineCatalog.objects.get(id=row["medicine_id"])
                Prescription.objects.create(
                    appointment  = appointment,
                    medicine     = med,
                    dosage       = row["dosage"],
                    frequency    = row["frequency"],
                    duration     = row["duration"],
                    instructions = row.get("instructions", ""),
                    sort_order   = row.get("sort_order", i),
                )

            # ── Complete transition ──────────────────────────────────────────
            sm_complete(appointment, follow_up_days=d.get("follow_up_days"))

        # ── Enqueue LLM job ──────────────────────────────────────────────────
        try:
            from apps.clinical.tasks import post_visit_llm_job
            post_visit_llm_job.delay(str(appointment.id))
        except Exception as exc:
            logger.warning("Could not enqueue post_visit_llm_job for %s: %s", appointment.id, exc)

        appointment.refresh_from_db()
        return Response(
            {
                "id":             str(appointment.id),
                "status":         appointment.status,
                "summary_status": appointment.summary_status,
            },
            status=status.HTTP_200_OK,
        )


class SummaryReviewView(APIView):
    """
    GET /doctor/appointments/:id/summary
        Returns the draft for side-by-side review (raw notes vs AI text).

    PUT /doctor/appointments/:id/summary/approve
        Doctor approves (possibly after editing).
        Writes edited_text back to MongoDB then flips summary_status = approved.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def _get_appointment(self, request: Request, appointment_id: str) -> Appointment:
        try:
            return Appointment.objects.select_related(
                "visit_note", "approved_by"
            ).prefetch_related(
                "prescriptions__medicine"
            ).get(
                id=appointment_id,
                doctor=request.user,
                hospital=request.user.hospital,
                status=AppointmentStatus.COMPLETED,
            )
        except Appointment.DoesNotExist:
            raise NotFound("Completed appointment not found.") from None

    def get(self, request: Request, appointment_id: str) -> Response:
        appointment = self._get_appointment(request, appointment_id)

        if appointment.summary_status == SummaryStatus.PENDING:
            return Response(
                {"summary_status": "pending", "detail": "AI summary is still being generated."},
                status=status.HTTP_202_ACCEPTED,
            )

        # Fetch draft text from MongoDB
        summary_text = ""
        follow_up_note = None
        if appointment.summary_status == SummaryStatus.DRAFT and appointment.post_summary_id:
            from apps.integrations.llm.mongo_log import get_pre_visit_log
            doc = get_pre_visit_log(str(appointment.id))
            if doc and doc.get("parsed"):
                summary_text   = doc["parsed"].get("summary_text", "")
                follow_up_note = doc["parsed"].get("follow_up_note")

        prescriptions = appointment.prescriptions.select_related("medicine")
        visit_notes   = getattr(appointment, "visit_note", None)

        return Response({
            "appointment_id": str(appointment.id),
            "summary_status": appointment.summary_status,
            "summary_text":   summary_text,
            "medications":    PrescriptionReadSerializer(prescriptions, many=True).data,
            "follow_up_note": follow_up_note,
            "visit_notes":    visit_notes.notes if visit_notes else "",
        })

    def put(self, request: Request, appointment_id: str) -> Response:
        appointment = self._get_appointment(request, appointment_id)

        if appointment.summary_status != SummaryStatus.DRAFT:
            raise ValidationError(
                {"summary_status": f"Cannot approve summary with status '{appointment.summary_status}'."}
            )

        serializer = SummaryApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        edited_text = serializer.validated_data["edited_text"]

        # Write edited text back to MongoDB audit log
        if appointment.post_summary_id:
            try:
                from apps.integrations.llm.mongo_log import _get_collection
                _get_collection().update_one(
                    {"appointment_id": str(appointment.id), "call_type": "pre_visit",
                     "status": "ok"},
                    {"$set": {"parsed.summary_text": edited_text, "edited_by_doctor": True}},
                    upsert=False,
                )
            except Exception as exc:
                logger.warning("MongoDB update failed for %s: %s", appointment.id, exc)

        mark_summary_approved(appointment, approved_by=request.user)

        return Response({
            "id":             str(appointment.id),
            "summary_status": appointment.summary_status,
            "approved_at":    appointment.approved_at.isoformat() if appointment.approved_at else None,
        })


class PatientPostVisitSummaryView(ScopedQuerysetMixin, APIView):
    """
    GET /appointments/:id/post-visit-summary

    Patient-facing — only visible when summary_status = approved.
    Scoped: patient can only see their own appointment.
    Returns the doctor-approved text and structured medication list.
    """
    permission_classes = [IsAuthenticated, IsPatient, IsNotForcedReset]

    def get(self, request: Request, appointment_id: str) -> Response:
        appointment = self.scope_or_404(
            Appointment.objects.select_related(
                "approved_by"
            ).prefetch_related("prescriptions__medicine"),
            id=appointment_id,
        )

        if appointment.summary_status != SummaryStatus.APPROVED:
            return Response(
                {"summary_status": appointment.summary_status,
                 "detail": "Summary not yet available."},
                status=status.HTTP_202_ACCEPTED,
            )

        # Fetch approved text from MongoDB
        summary_text   = ""
        follow_up_note = None
        if appointment.post_summary_id:
            from apps.integrations.llm.mongo_log import get_pre_visit_log
            doc = get_pre_visit_log(str(appointment.id))
            if doc and doc.get("parsed"):
                summary_text   = doc["parsed"].get("summary_text", "")
                follow_up_note = doc["parsed"].get("follow_up_note")

        prescriptions = appointment.prescriptions.select_related("medicine")
        medications = [
            {
                "name":         rx.medicine.name,
                "dosage":       rx.dosage,
                "frequency":    rx.get_frequency_display(),
                "duration":     rx.duration,
                "instructions": rx.instructions,
            }
            for rx in prescriptions
        ]

        return Response({
            "appointment_id": str(appointment.id),
            "summary_text":   summary_text,
            "medications":    medications,
            "follow_up_note": follow_up_note,
            "follow_up_days": appointment.follow_up_days,
            "approved_by":    appointment.approved_by.name if appointment.approved_by else "",
            "approved_at":    appointment.approved_at.isoformat() if appointment.approved_at else None,
        })


# ---------------------------------------------------------------------------
# Medicine catalog views
# ---------------------------------------------------------------------------

class MedicineCatalogSearchView(APIView):
    """
    GET /medicine-catalog?q=&status=active

    Searchable by name prefix. Used by the consultation autocomplete.
    Doctors and admins can access. Returns active + pending_review medicines.
    """
    permission_classes = [IsAuthenticated, IsAdminOrDoctor, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        q      = request.query_params.get("q", "").strip()
        status_filter = request.query_params.get("status", "active")

        qs = MedicineCatalog.objects.filter(
            hospital=request.user.hospital,
        )

        if status_filter == "all":
            pass
        elif status_filter == "pending":
            qs = qs.filter(status=MedicineStatus.PENDING_REVIEW)
        else:
            qs = qs.filter(status=MedicineStatus.ACTIVE)

        if q:
            qs = qs.filter(name__icontains=q)

        qs = qs.order_by("name")[:20]
        return Response(MedicineCatalogSerializer(qs, many=True).data)


class MedicineCatalogCreateView(APIView):
    """
    POST /medicine-catalog

    Creates a new medicine entry with status=pending_review.
    Used when a doctor prescribes something not yet in the catalog.
    If a matching (case-insensitive) entry already exists, returns it.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def post(self, request: Request) -> Response:
        serializer = MedicineCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Idempotent: return existing if name matches (case-insensitive)
        existing = MedicineCatalog.objects.filter(
            hospital=request.user.hospital,
            name__iexact=d["name"],
        ).first()
        if existing:
            return Response(
                MedicineCatalogSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        med = MedicineCatalog.objects.create(
            hospital       = request.user.hospital,
            name           = d["name"],
            generic_name   = d.get("generic_name", ""),
            default_dosage = d.get("default_dosage", ""),
            status         = MedicineStatus.PENDING_REVIEW,
            created_by     = request.user,
        )
        return Response(MedicineCatalogSerializer(med).data, status=status.HTTP_201_CREATED)


class MedicineCatalogAdminView(APIView):
    """
    PATCH /medicine-catalog/:id  — admin approves or rejects a pending medicine.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def patch(self, request: Request, medicine_id: str) -> Response:
        try:
            med = MedicineCatalog.objects.get(
                id=medicine_id, hospital=request.user.hospital
            )
        except MedicineCatalog.DoesNotExist:
            raise NotFound("Medicine not found.") from None

        new_status = request.data.get("status")
        if new_status not in ("active", "rejected"):
            raise ValidationError({"status": "Must be 'active' or 'rejected'."})

        # Merge: optionally rename to the canonical name before approving
        if canonical_name := request.data.get("name"):
            med.name = str(canonical_name).strip()

        med.status = new_status
        med.save(update_fields=["status", "name", "updated_at"])
        return Response(MedicineCatalogSerializer(med).data)
