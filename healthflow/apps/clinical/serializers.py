"""
clinical/serializers.py

Phase 3 serializers for the booking flow.
Phase 4 adds: PreVisitAttachmentSerializer, DoctorAppointmentCardSerializer
              extended with pre_summary_content.
"""
from __future__ import annotations

import os

from django.conf import settings
from rest_framework import serializers

from apps.clinical.models import (
    Appointment,
    AppointmentStatus,
    AllowedFileType,
    PreSummaryStatus,
    PreVisitAttachment,
)
from apps.scheduling.models import AppointmentSlot

MAX_UPLOAD_BYTES: int = getattr(settings, "MAX_UPLOAD_SIZE_BYTES", 5 * 1024 * 1024)
_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


# ---------------------------------------------------------------------------
# Appointment read serializer
# ---------------------------------------------------------------------------

class AppointmentSerializer(serializers.ModelSerializer):
    """Full read representation returned to patient and doctor/admin."""
    doctor_name       = serializers.CharField(source="doctor.name",         read_only=True)
    doctor_id         = serializers.UUIDField(source="doctor.id",           read_only=True)
    specialization    = serializers.SerializerMethodField()
    hospital_name     = serializers.CharField(source="hospital.name",       read_only=True)
    slot_date         = serializers.DateField(source="slot.date",           read_only=True)
    slot_start        = serializers.TimeField(source="slot.slot_start",     read_only=True)
    slot_end          = serializers.TimeField(source="slot.slot_end",       read_only=True)
    original_doctor_name = serializers.SerializerMethodField()

    class Meta:
        model  = Appointment
        fields = [
            "id", "status", "cancel_reason",
            "doctor_id", "doctor_name", "specialization",
            "hospital_name",
            "slot_id", "slot_date", "slot_start", "slot_end",
            "token",
            "symptom_text", "urgency_level",
            "pre_summary_status", "ai_pre_summary_id",
            "held_until",
            "reassignment_note",         # Phase 7
            "original_doctor_name",      # Phase 7
            "created_at", "updated_at",
        ]

    def get_specialization(self, obj: Appointment) -> str:
        try:
            return obj.doctor.doctor_profile.specialization
        except Exception:
            return ""

    def get_original_doctor_name(self, obj: Appointment) -> str:
        """Return the original doctor's name when this appointment was reassigned."""
        try:
            if obj.original_request:
                return obj.original_request.doctor.name
        except Exception:
            pass
        return ""


# ---------------------------------------------------------------------------
# Booking input serializers
# ---------------------------------------------------------------------------

class HoldSerializer(serializers.Serializer):
    """POST /appointments/hold"""
    slot_id   = serializers.UUIDField()
    doctor_id = serializers.UUIDField()

    def validate_slot_id(self, value):
        try:
            slot = AppointmentSlot.objects.select_related("doctor__user").get(id=value)
        except AppointmentSlot.DoesNotExist:
            raise serializers.ValidationError("Slot not found.") from None
        self._slot = slot
        return value

    def validate(self, attrs):
        slot = getattr(self, "_slot", None)
        if slot is None:
            return attrs

        # Ensure doctor_id matches the slot's doctor
        if str(slot.doctor.user_id) != str(attrs["doctor_id"]):
            raise serializers.ValidationError(
                {"doctor_id": "Doctor does not own this slot."}
            )

        # Basic capacity guard (Redis DECR is the real lock; this is a pre-check)
        if slot.booked_count >= slot.capacity:
            raise serializers.ValidationError(
                {"slot_id": "This slot is fully booked."}
            )

        # No duplicate holds by the same patient on the same slot
        request = self.context.get("request")
        if request and Appointment.objects.filter(
            patient=request.user,
            slot=slot,
            status__in=[AppointmentStatus.HELD, AppointmentStatus.CONFIRMED],
        ).exists():
            raise serializers.ValidationError(
                {"slot_id": "You already have a booking in this slot."}
            )

        attrs["slot"] = slot
        return attrs


class ConfirmSerializer(serializers.Serializer):
    """POST /appointments/:id/confirm"""
    symptom_text = serializers.CharField(min_length=10, max_length=2000)


class CancelSerializer(serializers.Serializer):
    """POST /appointments/:id/cancel  — patient-initiated only"""
    # No extra fields needed; reason is always patient_initiated for patient role
    pass


class RescheduleSerializer(serializers.Serializer):
    """
    POST /appointments/:id/reschedule

    Cancel the current confirmed appointment and hold a new slot — same
    symptom_text carried forward, no re-entry required.
    """
    new_slot_id   = serializers.UUIDField()
    new_doctor_id = serializers.UUIDField()

    def validate_new_slot_id(self, value):
        try:
            slot = AppointmentSlot.objects.select_related("doctor__user").get(id=value)
        except AppointmentSlot.DoesNotExist:
            raise serializers.ValidationError("New slot not found.") from None
        self._new_slot = slot
        return value

    def validate(self, attrs):
        slot = getattr(self, "_new_slot", None)
        if slot is None:
            return attrs
        if str(slot.doctor.user_id) != str(attrs["new_doctor_id"]):
            raise serializers.ValidationError(
                {"new_doctor_id": "Doctor does not own the new slot."}
            )
        if slot.booked_count >= slot.capacity:
            raise serializers.ValidationError(
                {"new_slot_id": "The new slot is fully booked."}
            )
        attrs["new_slot"] = slot
        return attrs


# ---------------------------------------------------------------------------
# Patient-facing list item (compact)
# ---------------------------------------------------------------------------

class AppointmentListItemSerializer(serializers.ModelSerializer):
    doctor_name    = serializers.CharField(source="doctor.name",     read_only=True)
    specialization = serializers.SerializerMethodField()
    slot_date      = serializers.DateField(source="slot.date",       read_only=True)
    slot_start     = serializers.TimeField(source="slot.slot_start", read_only=True)
    slot_end       = serializers.TimeField(source="slot.slot_end",   read_only=True)
    hospital_name  = serializers.CharField(source="hospital.name",   read_only=True)

    class Meta:
        model  = Appointment
        fields = [
            "id", "status", "cancel_reason",
            "doctor_name", "specialization",
            "hospital_name",
            "slot_date", "slot_start", "slot_end",
            "token", "urgency_level", "pre_summary_status",
            "created_at",
        ]

    def get_specialization(self, obj: Appointment) -> str:
        try:
            return obj.doctor.doctor_profile.specialization
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# Doctor-facing appointment card (includes symptom text + AI status)
# ---------------------------------------------------------------------------

class DoctorAppointmentCardSerializer(serializers.ModelSerializer):
    patient_name   = serializers.CharField(source="patient.name",    read_only=True)
    patient_id     = serializers.UUIDField(source="patient.id",      read_only=True)
    slot_date      = serializers.DateField(source="slot.date",       read_only=True)
    slot_start     = serializers.TimeField(source="slot.slot_start", read_only=True)

    class Meta:
        model  = Appointment
        fields = [
            "id", "status",
            "patient_id", "patient_name",
            "slot_date", "slot_start",
            "token", "symptom_text",
            "urgency_level", "pre_summary_status", "ai_pre_summary_id",
        ]


# ---------------------------------------------------------------------------
# PreVisitAttachment (Phase 4)
# ---------------------------------------------------------------------------

class PreVisitAttachmentSerializer(serializers.ModelSerializer):
    """Read serializer — returned to patient (list) and doctor (detail)."""
    file_url = serializers.SerializerMethodField()

    class Meta:
        model  = PreVisitAttachment
        fields = [
            "id", "appointment_id", "file_type",
            "original_filename", "file_size_bytes",
            "file_url", "uploaded_at",
        ]

    def get_file_url(self, obj: PreVisitAttachment) -> str:
        request = self.context.get("request")
        if request and obj.file:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url if obj.file else ""


class AttachmentUploadSerializer(serializers.Serializer):
    """
    POST /appointments/:id/attachments

    Validates MIME type and size before the file ever touches disk.
    Only pdf/jpeg/png are accepted; max 5 MB.
    """
    file = serializers.FileField()

    def validate_file(self, value):
        # Size check
        if value.size > MAX_UPLOAD_BYTES:
            max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(
                f"File too large. Maximum size is {max_mb} MB."
            )

        # Extension / type check
        name = value.name or ""
        ext  = os.path.splitext(name)[1].lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            )

        # Map extension → AllowedFileType value
        ext_to_type = {
            ".pdf":  AllowedFileType.PDF,
            ".jpg":  AllowedFileType.JPEG,
            ".jpeg": AllowedFileType.JPEG,
            ".png":  AllowedFileType.PNG,
        }
        value._resolved_file_type = ext_to_type[ext]
        value._original_filename  = name
        return value


# ---------------------------------------------------------------------------
# DoctorAppointmentCardSerializer — extended with pre_summary_content (Phase 4)
# ---------------------------------------------------------------------------

class DoctorAppointmentCardSerializer(serializers.ModelSerializer):
    """
    Doctor-facing appointment card.
    Includes symptom text, AI summary status, and — when status is 'ready' —
    the full parsed summary fetched from MongoDB.
    pre_summary_content is None when status != 'ready'.
    """
    patient_name        = serializers.CharField(source="patient.name",    read_only=True)
    patient_id          = serializers.UUIDField(source="patient.id",      read_only=True)
    slot_date           = serializers.DateField(source="slot.date",       read_only=True)
    slot_start          = serializers.TimeField(source="slot.slot_start", read_only=True)
    pre_summary_content = serializers.SerializerMethodField()
    attachments         = serializers.SerializerMethodField()

    class Meta:
        model  = Appointment
        fields = [
            "id", "status",
            "patient_id", "patient_name",
            "slot_date", "slot_start",
            "token", "symptom_text",
            "urgency_level", "pre_summary_status",
            "pre_summary_content",
            "attachments",
        ]

    def get_pre_summary_content(self, obj: Appointment) -> dict | None:
        if obj.pre_summary_status != PreSummaryStatus.READY:
            return None
        if not obj.ai_pre_summary_id:
            return None
        try:
            from apps.integrations.llm.mongo_log import get_pre_visit_log
            doc = get_pre_visit_log(str(obj.id))
            if doc and doc.get("parsed"):
                return doc["parsed"]
        except Exception:
            pass
        return None

    def get_attachments(self, obj: Appointment) -> list:
        request = self.context.get("request")
        qs = obj.attachments.all().order_by("uploaded_at")
        return PreVisitAttachmentSerializer(qs, many=True, context={"request": request}).data


# Import models needed by Phase 5 serializers (avoid NameError)
from apps.clinical.models import MedicineCatalog, Prescription  # noqa: E402

# ---------------------------------------------------------------------------
# Phase 5 — Consultation serializers
# ---------------------------------------------------------------------------

class MedicineCatalogSerializer(serializers.ModelSerializer):
    class Meta:
        model  = MedicineCatalog
        fields = ["id", "name", "generic_name", "default_dosage", "status"]
        read_only_fields = ["id", "status"]

    def validate_name(self, value: str) -> str:
        return value.strip()


class MedicineCreateSerializer(serializers.Serializer):
    """POST /medicine-catalog — create or retrieve existing (case-insensitive)."""
    name           = serializers.CharField(max_length=200)
    generic_name   = serializers.CharField(max_length=200, required=False, default="", allow_blank=True)
    default_dosage = serializers.CharField(max_length=100, required=False, default="", allow_blank=True)

    def validate_name(self, value: str) -> str:
        return value.strip()


class PrescriptionReadSerializer(serializers.ModelSerializer):
    medicine_name  = serializers.CharField(source="medicine.name",            read_only=True)
    medicine_id    = serializers.UUIDField(source="medicine.id",              read_only=True)
    frequency_display = serializers.CharField(source="get_frequency_display", read_only=True)

    class Meta:
        model  = Prescription
        fields = [
            "id", "medicine_id", "medicine_name",
            "dosage", "frequency", "frequency_display",
            "duration", "instructions", "sort_order",
        ]


class PrescriptionWriteSerializer(serializers.Serializer):
    """One prescription row inside ConsultationSerializer."""
    medicine_id  = serializers.UUIDField()
    dosage       = serializers.CharField(max_length=100)
    frequency    = serializers.ChoiceField(choices=[c[0] for c in Prescription.FREQUENCY_CHOICES])
    duration     = serializers.CharField(max_length=50)
    instructions = serializers.CharField(required=False, default="", allow_blank=True)
    sort_order   = serializers.IntegerField(required=False, default=0)

    def validate_medicine_id(self, value):
        request  = self.context.get("request")
        hospital = request.user.hospital if request else None
        try:
            med = MedicineCatalog.objects.get(
                id=value,
                hospital=hospital,
                status__in=["active", "pending_review"],
            )
        except MedicineCatalog.DoesNotExist:
            raise serializers.ValidationError(
                "Medicine not found in this hospital's catalog."
            ) from None
        self._medicine = med
        return value


class ConsultationSerializer(serializers.Serializer):
    """
    POST /doctor/appointments/:id/consultation

    Submits visit notes + prescription rows in one call.
    Also accepts an optional follow_up_days.
    """
    notes          = serializers.CharField(min_length=10, max_length=10000)
    prescriptions  = serializers.ListField(
        child=PrescriptionWriteSerializer(),
        min_length=0,
        allow_empty=True,
    )
    follow_up_days = serializers.IntegerField(min_value=1, max_value=365, required=False, allow_null=True)

    def validate_prescriptions(self, value: list) -> list:
        # Re-validate each child with the request context
        request = self.context.get("request")
        validated = []
        for item in value:
            child = PrescriptionWriteSerializer(data=item, context={"request": request})
            child.is_valid(raise_exception=True)
            validated.append(child.validated_data)
        return validated


class SummaryDraftSerializer(serializers.Serializer):
    """
    GET /doctor/appointments/:id/summary

    Returns the draft summary for doctor review.
    summary_text is the editable LLM output; medications are canonical DB rows.
    """
    appointment_id = serializers.UUIDField()
    summary_status = serializers.CharField()
    summary_text   = serializers.CharField(allow_blank=True)
    medications    = PrescriptionReadSerializer(many=True)
    follow_up_note = serializers.CharField(allow_null=True, allow_blank=True)
    visit_notes    = serializers.CharField()  # raw — for side-by-side display


class SummaryApproveSerializer(serializers.Serializer):
    """
    PUT /doctor/appointments/:id/summary/approve
    """
    edited_text = serializers.CharField(min_length=10, max_length=20000)


class PostVisitSummarySerializer(serializers.Serializer):
    """
    GET /appointments/:id/summary   (patient-facing — only when approved)
    """
    appointment_id = serializers.UUIDField()
    summary_text   = serializers.CharField()
    medications    = serializers.ListField(child=serializers.DictField())
    follow_up_note = serializers.CharField(allow_null=True, allow_blank=True)
    approved_by    = serializers.CharField()   # doctor name
    approved_at    = serializers.DateTimeField()
    follow_up_days = serializers.IntegerField(allow_null=True)


# Import models needed by Phase 5 serializers (avoid NameError)
