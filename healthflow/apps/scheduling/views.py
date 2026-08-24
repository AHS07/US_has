"""
scheduling/views.py

Admin Phase 2 scheduling endpoints:

  Doctor profile & shift config
    GET  /admin-api/doctors/<id>/profile          DoctorProfileDetailView
    PATCH /admin-api/doctors/<id>/profile         DoctorProfileDetailView
    PUT  /admin-api/doctors/<id>/shift-config     ShiftConfigView

  Leave CRUD
    GET  /admin-api/doctors/<id>/leave            DoctorLeaveListView
    POST /admin-api/doctors/<id>/leave            DoctorLeaveListView
    DELETE /admin-api/doctors/<id>/leave/<lid>    DoctorLeaveDetailView

  Attendance sheet (day-of)
    GET  /admin-api/attendance                    AttendanceSheetView
    PUT  /admin-api/attendance/<doctor_id>        AttendanceMarkView

  Slot generation (on-demand)
    POST /admin-api/doctors/<id>/slots/generate   SlotGenerateView

  Doctor day-view (doctor portal — Phase 2 structure, patient data in Phase 3)
    GET  /doctor/slots                            DoctorDayView

Rules:
  - Admin views use IsAdmin + IsNotForcedReset; doctor views use IsDoctor.
  - Hospital scoping enforced on every query; no cross-hospital access.
  - Slot generation is sync in Phase 2 (small window); Phase 8 moves nightly
    bulk generation to the Celery beat schedule. On-demand stays sync.
"""
from __future__ import annotations

import datetime

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User, UserRole
from apps.accounts.permissions import IsAdmin, IsDoctor, IsNotForcedReset
from apps.scheduling.models import (
    AppointmentSlot,
    AttendanceStatus,
    DoctorAttendance,
    DoctorLeave,
    DoctorProfile,
    ShiftConfig,
    ShiftName,
)
from apps.scheduling.serializers import (
    AppointmentSlotSerializer,
    AttendanceSheetEntrySerializer,
    AttendanceUpdateSerializer,
    CreateLeaveSerializer,
    DoctorLeaveSerializer,
    DoctorProfileSerializer,
    DoctorProfileUpdateSerializer,
    ShiftConfigUpdateSerializer,
    SlotGenerateSerializer,
)
from apps.scheduling.services import generate_slots_for_doctor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_doctor_profile(request: Request, doctor_id: str) -> DoctorProfile:
    """
    Load a DoctorProfile that belongs to the requesting admin's hospital.
    Raises NotFound (404) — never 403 — to avoid confirming existence.
    """
    try:
        return DoctorProfile.objects.select_related(
            "user", "shift_config"
        ).get(
            user_id=doctor_id,
            user__hospital=request.user.hospital,
        )
    except DoctorProfile.DoesNotExist:
        raise NotFound("Doctor not found.") from None


# ---------------------------------------------------------------------------
# Doctor profile & shift config
# ---------------------------------------------------------------------------

class DoctorProfileDetailView(APIView):
    """
    GET  /admin-api/doctors/<doctor_id>/profile  — full profile + shift config
    PATCH /admin-api/doctors/<doctor_id>/profile — edit specialization / is_active
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        return Response(DoctorProfileSerializer(profile).data)

    def patch(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        serializer = DoctorProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        update_fields: list[str] = []
        if "specialization" in d:
            profile.specialization = d["specialization"]
            update_fields.append("specialization")
        if "is_active" in d:
            profile.is_active = d["is_active"]
            update_fields.append("is_active")

        if update_fields:
            profile.save(update_fields=update_fields)

        return Response(DoctorProfileSerializer(profile).data)


class ShiftConfigView(APIView):
    """
    PUT /admin-api/doctors/<doctor_id>/shift-config
    Replaces the entire shift config + slot settings in one call.
    Uses update_or_create so it works even before a ShiftConfig row exists.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def put(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        serializer = ShiftConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        with transaction.atomic():
            shift, _ = ShiftConfig.objects.update_or_create(
                doctor=profile,
                defaults={
                    "shift_1_start": d["shift_1_start"],
                    "shift_1_end":   d["shift_1_end"],
                    "shift_2_start": d["shift_2_start"],
                    "shift_2_end":   d["shift_2_end"],
                    "working_days":  d["working_days"],
                },
            )
            # Slot settings live on DoctorProfile
            profile.slot_duration_minutes = d["slot_duration_minutes"]
            profile.slot_capacity         = d["slot_capacity"]
            profile.save(update_fields=["slot_duration_minutes", "slot_capacity"])

        # Re-fetch with fresh shift_config for response
        profile.refresh_from_db()
        return Response(DoctorProfileSerializer(profile).data)

    def get(self, request: Request, doctor_id: str) -> Response:
        """Convenience GET so the frontend can pre-fill the form."""
        profile = _get_doctor_profile(request, doctor_id)
        try:
            shift = profile.shift_config
        except ShiftConfig.DoesNotExist:
            return Response(
                {"error": {"code": "not_found", "message": "Shift config not set yet."}},
                status=status.HTTP_404_NOT_FOUND,
            )
        from apps.scheduling.serializers import ShiftConfigSerializer
        data = ShiftConfigSerializer(shift).data
        data["slot_duration_minutes"] = profile.slot_duration_minutes
        data["slot_capacity"]         = profile.slot_capacity
        return Response(data)


# ---------------------------------------------------------------------------
# Leave CRUD
# ---------------------------------------------------------------------------

class DoctorLeaveListView(APIView):
    """
    GET  /admin-api/doctors/<doctor_id>/leave   — list leave days
    POST /admin-api/doctors/<doctor_id>/leave   — add a leave day
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        leave = DoctorLeave.objects.filter(doctor=profile).order_by("date")
        return Response(DoctorLeaveSerializer(leave, many=True).data)

    def post(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        serializer = CreateLeaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        # Duplicate guard with a clear error
        if DoctorLeave.objects.filter(doctor=profile, date=d["date"]).exists():
            raise ValidationError(
                {"date": f"Leave already recorded for {d['date']}."}
            )

        leave = DoctorLeave.objects.create(
            doctor=profile,
            date=d["date"],
            reason=d.get("reason", ""),
            created_by=request.user,
        )

        # Phase 7: cascade-cancel any confirmed appointments on the leave date
        try:
            from apps.scheduling.tasks import cascade_absence_task
            cascade_absence_task.delay(
                str(profile.user_id),
                d["date"].isoformat(),
                None,                    # full day
                "affected_by_leave",
            )
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "DoctorLeaveListView: cascade enqueue failed: %s", exc
            )

        return Response(DoctorLeaveSerializer(leave).data, status=status.HTTP_201_CREATED)


class DoctorLeaveDetailView(APIView):
    """
    DELETE /admin-api/doctors/<doctor_id>/leave/<leave_id>
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def delete(self, request: Request, doctor_id: str, leave_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        try:
            leave = DoctorLeave.objects.get(id=leave_id, doctor=profile)
        except DoctorLeave.DoesNotExist:
            raise NotFound("Leave record not found.") from None
        leave.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Attendance sheet
# ---------------------------------------------------------------------------

class AttendanceSheetView(APIView):
    """
    GET /admin-api/attendance?date=YYYY-MM-DD&search=

    Returns one row per doctor showing their morning/afternoon status for the
    requested date (defaults to today). Default = present (no row in DB).
    On-leave doctors are flagged based on DoctorLeave table.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def get(self, request: Request) -> Response:
        date_str = request.query_params.get("date", "")
        search   = request.query_params.get("search", "").strip()

        try:
            target_date = (
                datetime.date.fromisoformat(date_str)
                if date_str
                else datetime.date.today()
            )
        except ValueError:
            raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD."})

        profiles_qs = DoctorProfile.objects.select_related(
            "user", "shift_config"
        ).filter(
            user__hospital=request.user.hospital,
            is_active=True,
        ).order_by("user__name")

        if search:
            profiles_qs = profiles_qs.filter(
                Q(user__name__icontains=search) |
                Q(specialization__icontains=search)
            )

        # Pre-load all attendance and leave records for this date in two queries
        attendance_map: dict[str, dict[str, str]] = {}
        for rec in DoctorAttendance.objects.filter(
            doctor__user__hospital=request.user.hospital,
            date=target_date,
        ):
            attendance_map.setdefault(str(rec.doctor_id), {})[rec.shift] = rec.status

        on_leave_ids = set(
            DoctorLeave.objects.filter(
                doctor__user__hospital=request.user.hospital,
                date=target_date,
            ).values_list("doctor_id", flat=True)
        )
        on_leave_ids = {str(pk) for pk in on_leave_ids}

        rows = []
        for profile in profiles_qs:
            pid = str(profile.user_id)
            on_leave = pid in on_leave_ids
            doc_attendance = attendance_map.get(pid, {})

            if on_leave:
                morning_status   = "on_leave"
                afternoon_status = "on_leave"
            else:
                morning_status   = doc_attendance.get(ShiftName.MORNING,   AttendanceStatus.PRESENT)
                afternoon_status = doc_attendance.get(ShiftName.AFTERNOON, AttendanceStatus.PRESENT)

            # Build human-readable shift string
            try:
                sc = profile.shift_config
                shifts_str = (
                    f"{sc.shift_1_start.strftime('%H:%M')}–{sc.shift_1_end.strftime('%H:%M')}"
                    f" / "
                    f"{sc.shift_2_start.strftime('%H:%M')}–{sc.shift_2_end.strftime('%H:%M')}"
                )
            except ShiftConfig.DoesNotExist:
                shifts_str = "Not configured"

            rows.append({
                "doctor_id":        pid,
                "name":             profile.user.name,
                "specialization":   profile.specialization,
                "shifts":           shifts_str,
                "morning_status":   morning_status,
                "afternoon_status": afternoon_status,
                "on_leave":         on_leave,
            })

        return Response({"date": target_date.isoformat(), "doctors": rows})


class AttendanceMarkView(APIView):
    """
    PUT /admin-api/attendance/<doctor_id>

    Mark a doctor absent (or reset to present) for one half-day on a date.
    Body: { "date": "YYYY-MM-DD", "shift": "morning"|"afternoon", "status": "present"|"absent" }

    present  → delete the DoctorAttendance row (default = present = no row)
    absent   → upsert a DoctorAttendance row with status=absent

    Phase 7 adds the cascade-cancel logic on absent transitions.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def put(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        serializer = AttendanceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        if d["status"] == AttendanceStatus.PRESENT:
            # "Present" = no row — delete if it exists
            DoctorAttendance.objects.filter(
                doctor=profile,
                date=d["date"],
                shift=d["shift"],
            ).delete()
            return Response({"status": "present", "date": d["date"], "shift": d["shift"]})

        # absent → upsert
        attendance, created = DoctorAttendance.objects.update_or_create(
            doctor=profile,
            date=d["date"],
            shift=d["shift"],
            defaults={
                "status":    AttendanceStatus.ABSENT,
                "marked_by": request.user,
            },
        )

        # Phase 7: enqueue cascade only on a new absent marking (not on duplicate PUT)
        if created or attendance.status == AttendanceStatus.ABSENT:
            try:
                from apps.scheduling.tasks import cascade_absence_task
                cascade_absence_task.delay(
                    str(profile.user_id),
                    d["date"].isoformat(),
                    d["shift"],
                    "affected_by_absent",
                )
            except Exception as exc:
                import logging as _log
                _log.getLogger(__name__).warning(
                    "AttendanceMarkView: cascade enqueue failed: %s", exc
                )

        return Response(
            {
                "status":    attendance.status,
                "date":      attendance.date.isoformat(),
                "shift":     attendance.shift,
                "marked_at": attendance.marked_at.isoformat(),
            }
        )


# ---------------------------------------------------------------------------
# Slot generation (on-demand)
# ---------------------------------------------------------------------------

class SlotGenerateView(APIView):
    """
    POST /admin-api/doctors/<doctor_id>/slots/generate

    Runs slot generation synchronously for admin feedback.
    The nightly bulk generation runs via Celery beat (slot_generation_task)
    but the on-demand path here is sync so the admin sees the result immediately.
    """
    permission_classes = [IsAuthenticated, IsAdmin, IsNotForcedReset]

    def post(self, request: Request, doctor_id: str) -> Response:
        profile = _get_doctor_profile(request, doctor_id)
        serializer = SlotGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        try:
            result = generate_slots_for_doctor(
                profile, d["date_from"], d["date_to"]
            )
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc

        return Response(
            {
                "created": result.created,
                "skipped": result.skipped,
                "guarded": result.guarded,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Doctor portal — day view (slot grid)
# ---------------------------------------------------------------------------

class DoctorDayView(APIView):
    """
    GET /doctor/slots?date=YYYY-MM-DD

    Returns the requesting doctor's slots for the given date (default today)
    along with patient booking counts. In Phase 2 there are no bookings yet,
    so patient cards are always empty — the structure is correct for Phase 3
    to populate.
    """
    permission_classes = [IsAuthenticated, IsDoctor, IsNotForcedReset]

    def get(self, request: Request) -> Response:
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
            profile = DoctorProfile.objects.select_related("shift_config").get(
                user=request.user
            )
        except DoctorProfile.DoesNotExist:
            raise NotFound("Doctor profile not configured. Contact your admin.")

        slots = (
            AppointmentSlot.objects.filter(doctor=profile, date=target_date)
            .order_by("slot_start")
        )

        # Check leave / attendance for the unavailable flag
        on_leave = DoctorLeave.objects.filter(doctor=profile, date=target_date).exists()
        absent_shifts = set(
            DoctorAttendance.objects.filter(
                doctor=profile,
                date=target_date,
                status=AttendanceStatus.ABSENT,
            ).values_list("shift", flat=True)
        )

        def _shift_name(slot: AppointmentSlot) -> str:
            try:
                sc = profile.shift_config
                if slot.slot_start < sc.shift_2_start:
                    return ShiftName.MORNING
            except ShiftConfig.DoesNotExist:
                pass
            return ShiftName.AFTERNOON

        from apps.clinical.models import Appointment, AppointmentStatus

        appts = (
            Appointment.objects.filter(
                slot__in=slots,
                status__in=[
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.COMPLETED,
                    AppointmentStatus.HELD,
                ],
            )
            .select_related("patient")
            .order_by("token", "created_at")
        )

        appts_by_slot: dict[str, list] = {}
        for appt in appts:
            appts_by_slot.setdefault(str(appt.slot_id), []).append({
                "id":                str(appt.id),
                "name":              appt.patient.name,
                "age":               getattr(appt.patient, "age", 30) or 30,
                "token":             appt.token or 0,
                "chief_complaint":   appt.symptom_text[:80] if appt.symptom_text else "No symptoms provided",
                "urgency":           appt.urgency_level or "Low",
                "ai_summary_status": appt.pre_summary_status,
                "appointment_id":    str(appt.id),
            })

        slot_data = []
        for slot in slots:
            shift = _shift_name(slot)
            unavailable = on_leave or (shift in absent_shifts)
            slot_data.append({
                **AppointmentSlotSerializer(slot).data,
                "shift":       shift,
                "unavailable": unavailable,
                "patients":    appts_by_slot.get(str(slot.id), []),
            })

        return Response({
            "date":  target_date.isoformat(),
            "slots": slot_data,
        })
