"""
notifications/models.py

Phase 6: Notification, EmailJob, DoctorGoogleCredentials

Design rules (phases.md Phase 6):
  - Notification row and EmailJob are created in the same transaction.atomic()
    inside events.py — they must never diverge.
  - EmailJob rows are never deleted; they carry the full retry history.
  - DoctorGoogleCredentials stores encrypted OAuth tokens (Fernet).
    The raw token is never logged or returned in an API response.
  - One DoctorGoogleCredentials row per doctor (OneToOne).
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class NotificationEventType(models.TextChoices):
    BOOKING_CONFIRMED       = "booking_confirmed",       "Booking confirmed"
    BOOKING_CANCELLED       = "booking_cancelled",       "Booking cancelled"
    BOOKING_RESCHEDULED     = "booking_rescheduled",     "Booking rescheduled"
    DOCTOR_ABSENT           = "doctor_absent",           "Doctor marked absent"
    RESCHEDULE_OFFER        = "reschedule_offer",        "Reschedule offered"
    RUNNING_LATE            = "running_late",            "Doctor running late"
    FOLLOW_UP_AVAILABLE     = "follow_up_available",     "Follow-up available"
    VISIT_SUMMARY_READY     = "visit_summary_ready",     "Visit summary ready"
    MEDICATION_REMINDER     = "medication_reminder",     "Medication reminder"


class EmailJobStatus(models.TextChoices):
    PENDING   = "pending",   "Pending"
    SENT      = "sent",      "Sent"
    FAILED    = "failed",    "Failed"
    CANCELLED = "cancelled", "Cancelled"


# ---------------------------------------------------------------------------
# Notification  (in-app)
# ---------------------------------------------------------------------------

class Notification(models.Model):
    """
    In-app notification row — one per patient per event.
    Read at GET /notifications (patient-scoped).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_column="patient_id",
    )
    hospital = models.ForeignKey(
        "accounts.Hospital",
        on_delete=models.CASCADE,
        related_name="notifications",
        db_column="hospital_id",
    )
    appointment = models.ForeignKey(
        "clinical.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
        db_column="appointment_id",
    )

    event_type  = models.CharField(max_length=30, choices=NotificationEventType.choices)
    title       = models.CharField(max_length=200)
    body        = models.TextField(blank=True, default="")
    is_read     = models.BooleanField(default=False, db_index=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes  = [
            models.Index(fields=["patient",  "is_read"], name="idx_notif_patient_read"),
            models.Index(fields=["hospital", "event_type"], name="idx_notif_hospital_event"),
        ]

    def __str__(self) -> str:
        return f"Notification({self.event_type} patient={self.patient_id})"


# ---------------------------------------------------------------------------
# EmailJob
# ---------------------------------------------------------------------------

class EmailJob(models.Model):
    """
    Email delivery record — mirrors the in-app Notification.
    Created in the same transaction; retried independently via Celery.
    Records are never deleted; max_retries=5 then status=failed.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    notification = models.OneToOneField(
        Notification,
        on_delete=models.CASCADE,
        related_name="email_job",
        db_column="notification_id",
    )
    recipient_email = models.EmailField()
    subject         = models.CharField(max_length=200)
    body_text       = models.TextField()
    body_html       = models.TextField(blank=True, default="")
    ics_attachment  = models.TextField(blank=True, default="")  # raw .ics content

    status      = models.CharField(
        max_length=10,
        choices=EmailJobStatus.choices,
        default=EmailJobStatus.PENDING,
        db_index=True,
    )
    retry_count = models.PositiveSmallIntegerField(default=0)
    last_error  = models.TextField(blank=True, default="")
    sent_at     = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_jobs"
        indexes  = [
            models.Index(fields=["status", "retry_count"], name="idx_emailjob_status"),
        ]

    def __str__(self) -> str:
        return f"EmailJob({self.status} to={self.recipient_email})"


# ---------------------------------------------------------------------------
# DoctorGoogleCredentials
# ---------------------------------------------------------------------------

class DoctorGoogleCredentials(models.Model):
    """
    Stores encrypted Google Calendar OAuth tokens for one doctor.
    The raw access/refresh tokens are NEVER stored in plain text.
    encrypt_token / decrypt_token from common.encryption handle the Fernet wrapping.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    doctor = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="google_credentials",
        db_column="doctor_id",
    )

    # Encrypted at rest via common.encryption.encrypt_token
    access_token_enc  = models.TextField()
    refresh_token_enc = models.TextField(blank=True, default="")
    token_expiry      = models.DateTimeField(null=True, blank=True)
    scopes            = models.TextField(blank=True, default="")  # space-separated

    # The doctor's primary Google Calendar ID (set on first event creation)
    calendar_id   = models.CharField(max_length=200, blank=True, default="primary")

    connected_at  = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "doctor_google_credentials"

    def __str__(self) -> str:
        return f"GoogleCreds(doctor={self.doctor_id})"


# ---------------------------------------------------------------------------
# MedicationReminderLog  (Phase 8)
# ---------------------------------------------------------------------------

class MedicationReminderLog(models.Model):
    """
    Tracks daily medication reminder dispatches per prescription and time slot.
    Guarantees strict idempotency for medication_reminder_dispatch.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    patient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="medication_reminders",
        db_column="patient_id",
    )
    prescription = models.ForeignKey(
        "clinical.Prescription",
        on_delete=models.CASCADE,
        related_name="reminder_logs",
        db_column="prescription_id",
    )
    reminder_date = models.DateField(db_index=True)
    time_slot     = models.CharField(max_length=20, blank=True, default="morning")
    sent_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "medication_reminder_logs"
        unique_together = [("prescription", "reminder_date", "time_slot")]
        indexes = [
            models.Index(fields=["patient", "reminder_date"], name="idx_med_remind_patient_date"),
        ]

    def __str__(self) -> str:
        return f"MedReminder({self.patient_id} rx={self.prescription_id} {self.reminder_date} {self.time_slot})"
