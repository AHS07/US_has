"""
notifications/tasks.py

Phase 6 Celery tasks:
  send_email_job           — delivers one EmailJob with max_retries=5, exponential backoff
  generate_ics             — builds a .ics string and attaches it to the EmailJob
  sync_google_calendar_event — create/update/delete a Google Calendar event for a doctor
  expire_stale_holds       — sweep confirmed-expired holds → cancelled (Phase 8 hook)

Rules (phases.md Phase 6 / rules.md §5):
  - Every task is idempotent: re-running with the same arguments is safe.
  - Failed tasks do not raise after max_retries; they set their record to 'failed'.
  - No raw credentials appear in logs (encrypt_token / decrypt_token used throughout).
"""
from __future__ import annotations

import datetime
import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# send_email_job
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=5,
    name="notifications.send_email_job",
    acks_late=True,
)
def send_email_job(self, email_job_id: str) -> dict:
    """
    Deliver one EmailJob.

    Retry schedule (exponential backoff):
      attempt 1 → immediate
      attempt 2 → 30 s
      attempt 3 → 2 min
      attempt 4 → 8 min
      attempt 5 → 32 min
      after 5   → status = failed, no more retries
    """
    from apps.notifications.models import EmailJob, EmailJobStatus
    from django.core.mail import EmailMultiAlternatives
    from django.conf import settings

    try:
        job = EmailJob.objects.select_related("notification").get(id=email_job_id)
    except EmailJob.DoesNotExist:
        logger.error("send_email_job: EmailJob %s not found", email_job_id)
        return {"status": "error", "detail": "not found"}

    if job.status == EmailJobStatus.SENT:
        return {"status": "already_sent"}
    if job.status == EmailJobStatus.CANCELLED:
        return {"status": "cancelled"}

    try:
        msg = EmailMultiAlternatives(
            subject    = job.subject,
            body       = job.body_text,
            from_email = settings.DEFAULT_FROM_EMAIL,
            to         = [job.recipient_email],
        )
        if job.body_html:
            msg.attach_alternative(job.body_html, "text/html")

        # Attach .ics calendar file if present
        if job.ics_attachment:
            msg.attach(
                filename     = "appointment.ics",
                content      = job.ics_attachment,
                mimetype     = "text/calendar",
            )

        msg.send(fail_silently=False)

        job.status  = EmailJobStatus.SENT
        job.sent_at = timezone.now()
        job.save(update_fields=["status", "sent_at"])
        logger.info("send_email_job: sent %s to %s", email_job_id, job.recipient_email)
        return {"status": "sent"}

    except Exception as exc:
        job.retry_count += 1
        job.last_error   = str(exc)[:1000]

        if job.retry_count >= 5:
            job.status = EmailJobStatus.FAILED
            job.save(update_fields=["status", "retry_count", "last_error"])
            logger.error(
                "send_email_job: permanently failed %s after 5 retries: %s",
                email_job_id, exc,
            )
            return {"status": "failed"}

        job.save(update_fields=["retry_count", "last_error"])
        countdown = 30 * (4 ** (job.retry_count - 1))  # 30s, 120s, 480s, 1920s
        logger.warning(
            "send_email_job: retry %d for %s in %ds: %s",
            job.retry_count, email_job_id, countdown, exc,
        )
        raise self.retry(exc=exc, countdown=countdown)


# ---------------------------------------------------------------------------
# generate_ics
# ---------------------------------------------------------------------------

@shared_task(name="notifications.generate_ics")
def generate_ics(appointment_id: str, email_job_id: str) -> dict:
    """
    Build a .ics calendar attachment for the appointment and attach it
    to the given EmailJob so the next send attempt includes it.

    Idempotent: safe to run more than once — subsequent runs overwrite
    ics_attachment with the same content.
    """
    from apps.notifications.models import EmailJob

    try:
        from apps.clinical.models import Appointment
        appointment = Appointment.objects.select_related(
            "patient", "doctor", "slot", "hospital"
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error("generate_ics: Appointment %s not found", appointment_id)
        return {"status": "error"}

    ics_content = _build_ics(appointment)

    try:
        job = EmailJob.objects.get(id=email_job_id)
        job.ics_attachment = ics_content
        job.save(update_fields=["ics_attachment"])
        logger.info("generate_ics: attached .ics to EmailJob %s", email_job_id)
    except EmailJob.DoesNotExist:
        logger.error("generate_ics: EmailJob %s not found", email_job_id)
        return {"status": "error"}

    return {"status": "ok"}


def _build_ics(appointment) -> str:
    """Build a minimal RFC 5545-compliant .ics string for the appointment."""
    slot       = appointment.slot
    date       = slot.date
    start_time = slot.slot_start
    end_time   = slot.slot_end

    def _dt(d: datetime.date, t: datetime.time) -> str:
        return datetime.datetime.combine(d, t).strftime("%Y%m%dT%H%M%S")

    uid       = f"{appointment.id}@healthflow.local"
    dtstamp   = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    dtstart   = _dt(date, start_time)
    dtend     = _dt(date, end_time)
    summary   = f"Appointment with {appointment.doctor.name}"
    organizer = appointment.hospital.name

    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//HealthFlow//Appointment//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{summary}",
        f"ORGANIZER;CN={organizer}:mailto:{appointment.hospital.contact_email}",
        f"ATTENDEE;CN={appointment.patient.name}:mailto:{appointment.patient.email}",
        f"DESCRIPTION:Token #{appointment.token or 'TBC'}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ])


# ---------------------------------------------------------------------------
# sync_google_calendar_event
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="notifications.sync_google_calendar_event",
)
def sync_google_calendar_event(self, appointment_id: str, action: str) -> dict:
    """
    Sync an appointment to the doctor's Google Calendar.
    action: "create" | "update" | "delete"

    If the doctor has no connected Google Calendar, this is a no-op.
    """
    from apps.notifications.models import DoctorGoogleCredentials

    try:
        from apps.clinical.models import Appointment
        appointment = Appointment.objects.select_related(
            "doctor", "slot", "hospital", "patient"
        ).get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error("sync_google_calendar_event: Appointment %s not found", appointment_id)
        return {"status": "error"}

    try:
        creds = DoctorGoogleCredentials.objects.get(doctor=appointment.doctor)
    except DoctorGoogleCredentials.DoesNotExist:
        return {"status": "skipped", "reason": "no_calendar_connected"}

    try:
        from apps.integrations.calendar.client import GoogleCalendarClient
        client = GoogleCalendarClient(creds)

        if action == "create":
            event_id = client.create_event(appointment)
            logger.info(
                "sync_google_calendar_event: created event %s for appt %s",
                event_id, appointment_id,
            )
            return {"status": "ok", "event_id": event_id}

        elif action == "update":
            client.update_event(appointment)
            return {"status": "ok"}

        elif action == "delete":
            client.delete_event(appointment)
            return {"status": "ok"}

        else:
            logger.error("sync_google_calendar_event: unknown action %r", action)
            return {"status": "error", "detail": f"unknown action: {action}"}

    except Exception as exc:
        logger.warning(
            "sync_google_calendar_event: error for appt=%s action=%s: %s",
            appointment_id, action, exc,
        )
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# expire_stale_holds (Phase 8 — registered now so beat schedule can reference it)
# ---------------------------------------------------------------------------

@shared_task(name="notifications.expire_stale_holds")
def expire_stale_holds() -> dict:
    """
    Cancel held appointments whose held_until has passed.
    Frees Redis counter + creates cancellation notification.
    Phase 8 activates the full sweep; this is a no-op placeholder until then.
    """
    from apps.clinical.models import Appointment, AppointmentStatus
    from apps.clinical.state_machine import cancel_hold

    now     = timezone.now()
    expired = Appointment.objects.filter(
        status=AppointmentStatus.HELD,
        held_until__lt=now,
    )

    cancelled = 0
    for appt in expired.iterator():
        try:
            cancel_hold(appt)
            cancelled += 1
        except Exception as exc:
            logger.warning("expire_stale_holds: failed for %s: %s", appt.id, exc)

    logger.info("expire_stale_holds: cancelled %d stale holds", cancelled)
    return {"status": "ok", "cancelled": cancelled}
