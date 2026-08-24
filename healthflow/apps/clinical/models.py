"""
clinical/models.py

Phase 3: Appointment (booking lifecycle)
Phase 4: PreVisitAttachment (lab results upload)
Phase 5: MedicineCatalog, VisitNote, Prescription (consultation)
         + summary_status / post_summary_id / approved_by / follow_up_days on Appointment
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Choices / enums
# ---------------------------------------------------------------------------

class AppointmentStatus(models.TextChoices):
    HELD       = "held",       "Held"
    CONFIRMED  = "confirmed",  "Confirmed"
    COMPLETED  = "completed",  "Completed"
    CANCELLED  = "cancelled",  "Cancelled"
    NO_SHOW    = "no_show",    "No Show"
    REASSIGNED = "reassigned", "Reassigned"


class CancelReason(models.TextChoices):
    PATIENT_INITIATED  = "patient_initiated",  "Patient initiated"
    AFFECTED_BY_LEAVE  = "affected_by_leave",  "Affected by leave"
    AFFECTED_BY_ABSENT = "affected_by_absent", "Affected by absence"


class PreSummaryStatus(models.TextChoices):
    PENDING     = "pending",     "Pending"
    READY       = "ready",       "Ready"
    UNAVAILABLE = "unavailable", "Unavailable"


class SummaryStatus(models.TextChoices):
    """Post-visit summary lifecycle (Phase 5)."""
    PENDING     = "pending",     "Pending"
    DRAFT       = "draft",       "Draft"       # LLM wrote it; awaiting doctor approval
    APPROVED    = "approved",    "Approved"    # patient-visible
    UNAVAILABLE = "unavailable", "Unavailable" # LLM failed; raw notes only


class MedicineStatus(models.TextChoices):
    ACTIVE         = "active",         "Active"
    PENDING_REVIEW = "pending_review", "Pending review"
    REJECTED       = "rejected",       "Rejected"


# ---------------------------------------------------------------------------
# MedicineCatalog  (Phase 5)
# ---------------------------------------------------------------------------

class MedicineCatalog(models.Model):
    """
    Hospital-scoped medicine catalog.

    Medicines created ad-hoc during a consultation go into pending_review
    until an admin approves or merges them.

    Rules (phases.md Phase 5):
      - Prescription rows must reference a MedicineCatalog entry (FK, not free text).
      - The post-visit LLM prompt receives ONLY the structured rows {name, dosage,
        frequency, duration} — never raw notes — preventing hallucination of drugs
        not actually prescribed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    hospital = models.ForeignKey(
        "accounts.Hospital",
        on_delete=models.CASCADE,
        related_name="medicine_catalog",
        db_column="hospital_id",
    )
    name           = models.CharField(max_length=200)
    generic_name   = models.CharField(max_length=200, blank=True, default="")
    default_dosage = models.CharField(max_length=100, blank=True, default="")
    status         = models.CharField(
        max_length=15,
        choices=MedicineStatus.choices,
        default=MedicineStatus.ACTIVE,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="medicines_created",
        db_column="created_by_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "medicine_catalog"
        indexes  = [
            models.Index(fields=["hospital", "status"], name="idx_med_hospital_status"),
            models.Index(fields=["hospital", "name"],   name="idx_med_hospital_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.status}]"


# ---------------------------------------------------------------------------
# Appointment
# ---------------------------------------------------------------------------

class Appointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="appointments",
        db_column="patient_id",
    )
    doctor   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="doctor_appointments",
        db_column="doctor_id",
    )
    slot     = models.ForeignKey(
        "scheduling.AppointmentSlot",
        on_delete=models.PROTECT,
        related_name="appointments",
        db_column="slot_id",
    )
    hospital = models.ForeignKey(
        "accounts.Hospital",
        on_delete=models.PROTECT,
        related_name="appointments",
        db_column="hospital_id",
    )

    # Booking status
    status = models.CharField(
        max_length=12,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.HELD,
        db_index=True,
    )
    cancel_reason = models.CharField(
        max_length=20,
        choices=CancelReason.choices,
        blank=True,
        default="",
    )
    held_until = models.DateTimeField(null=True, blank=True)
    token      = models.PositiveSmallIntegerField(null=True, blank=True)

    # Pre-visit (Phase 3/4)
    symptom_text  = models.TextField(blank=True, default="")
    urgency_level = models.CharField(max_length=6, blank=True, default="")

    # Pre-visit AI (Phase 4)
    ai_pre_summary_id  = models.CharField(max_length=64, blank=True, default="")
    pre_summary_status = models.CharField(
        max_length=12,
        choices=PreSummaryStatus.choices,
        default=PreSummaryStatus.PENDING,
    )

    # Post-visit AI (Phase 5)
    summary_status = models.CharField(
        max_length=12,
        choices=SummaryStatus.choices,
        default=SummaryStatus.PENDING,
        db_index=True,
    )
    post_summary_id = models.CharField(max_length=64, blank=True, default="")  # MongoDB _id
    approved_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_summaries",
        db_column="approved_by_id",
    )
    approved_at    = models.DateTimeField(null=True, blank=True)
    follow_up_days = models.PositiveSmallIntegerField(null=True, blank=True)

    # Reassignment chain
    original_request = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reassignments",
        db_column="original_request_id",
    )
    reassignment_note = models.TextField(blank=True, default="")  # Phase 7: shown to patient
    google_calendar_event_id = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "appointments"
        indexes  = [
            models.Index(fields=["patient",  "status"], name="idx_appt_patient_status"),
            models.Index(fields=["doctor",   "status"], name="idx_appt_doctor_status"),
            models.Index(fields=["hospital", "status"], name="idx_appt_hospital_status"),
            models.Index(fields=["slot",     "status"], name="idx_appt_slot_status"),
            models.Index(fields=["held_until"],          name="idx_appt_held_until"),
        ]

    def __str__(self) -> str:
        return f"Appointment({self.id} {self.status} patient={self.patient_id})"


# ---------------------------------------------------------------------------
# VisitNote  (Phase 5)
# ---------------------------------------------------------------------------

class VisitNote(models.Model):
    """
    Doctor's free-text consultation notes — one per appointment (1:1).
    Raw notes are NEVER sent to the patient. The LLM rewrites them into
    patient-friendly language; the doctor approves before the patient sees anything.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name="visit_note",
        db_column="appointment_id",
    )
    notes      = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="visit_notes_authored",
        db_column="created_by_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "visit_notes"

    def __str__(self) -> str:
        return f"VisitNote({self.appointment_id})"


# ---------------------------------------------------------------------------
# Prescription  (Phase 5)
# ---------------------------------------------------------------------------

class Prescription(models.Model):
    """
    One prescription line per appointment.
    medicine FK → MedicineCatalog entry (no free-text medicine names).
    This is the primary mechanism preventing LLM hallucination of medications.
    """
    FREQUENCY_CHOICES = [
        ("once_daily",        "Once daily"),
        ("twice_daily",       "Twice daily"),
        ("three_times_daily", "Three times daily"),
        ("four_times_daily",  "Four times daily"),
        ("at_bedtime",        "At bedtime"),
        ("as_needed",         "As needed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        db_column="appointment_id",
    )
    medicine = models.ForeignKey(
        MedicineCatalog,
        on_delete=models.PROTECT,
        related_name="prescriptions",
        db_column="medicine_id",
    )
    dosage       = models.CharField(max_length=100)
    frequency    = models.CharField(max_length=20, choices=FREQUENCY_CHOICES)
    duration     = models.CharField(max_length=50)
    instructions   = models.TextField(blank=True, default="")
    reminder_times = models.JSONField(default=list, blank=True)
    sort_order     = models.PositiveSmallIntegerField(default=0)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "prescriptions"
        ordering = ["sort_order", "created_at"]
        indexes  = [
            models.Index(fields=["appointment"], name="idx_rx_appointment"),
        ]

    def get_reminder_slots(self) -> list[str]:
        """
        Return the daily reminder slot identifiers for this prescription.
        If doctor configured specific reminder_times, use them;
        otherwise default to standard medical schedule for the frequency.
        """
        if self.reminder_times and isinstance(self.reminder_times, list) and len(self.reminder_times) > 0:
            return [str(t) for t in self.reminder_times]
        defaults = {
            "once_daily":        ["morning"],
            "twice_daily":       ["morning", "evening"],
            "three_times_daily": ["morning", "afternoon", "evening"],
            "four_times_daily":  ["morning", "afternoon", "evening", "bedtime"],
            "at_bedtime":        ["bedtime"],
            "as_needed":         [],
        }
        return defaults.get(self.frequency, ["morning"])

    def __str__(self) -> str:
        return f"Rx({self.medicine.name} for appt={self.appointment_id})"


# ---------------------------------------------------------------------------
# PreVisitAttachment  (Phase 4)
# ---------------------------------------------------------------------------

def _attachment_upload_path(instance: "PreVisitAttachment", filename: str) -> str:
    import os
    ext    = os.path.splitext(filename)[1].lower()
    new_fn = f"{uuid.uuid4().hex}{ext}"
    return f"attachments/{instance.appointment_id}/{new_fn}"


class AllowedFileType(models.TextChoices):
    PDF  = "pdf",  "PDF"
    JPEG = "jpeg", "JPEG"
    PNG  = "png",  "PNG"


class PreVisitAttachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.CASCADE,
        related_name="attachments",
        db_column="appointment_id",
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_attachments",
        db_column="uploaded_by_id",
    )
    file              = models.FileField(upload_to=_attachment_upload_path)
    file_type         = models.CharField(max_length=4, choices=AllowedFileType.choices)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    file_size_bytes   = models.PositiveIntegerField(default=0)
    uploaded_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pre_visit_attachments"
        indexes  = [
            models.Index(fields=["appointment"], name="idx_attach_appointment"),
        ]

    def __str__(self) -> str:
        return f"Attachment({self.id} appt={self.appointment_id} {self.file_type})"
