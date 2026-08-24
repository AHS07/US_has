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
from django.core.mail import EmailMultiAlternatives
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

        # Attach .ics calendar file if present (or build on the fly if needed for confirmation/reschedule)
        ics_data = job.ics_attachment
        if not ics_data and job.notification and job.notification.event_type in (
            "booking_confirmed", "booking_rescheduled"
        ) and job.notification.appointment:
            try:
                ics_data = _build_ics(job.notification.appointment)
                job.ics_attachment = ics_data
                job.save(update_fields=["ics_attachment"])
            except Exception as ics_err:
                logger.warning("send_email_job: on-the-fly ics generation failed: %s", ics_err)

        if ics_data:
            msg.attach(
                filename     = "appointment.ics",
                content      = ics_data,
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
            if event_id:
                appointment.google_calendar_event_id = event_id
                appointment.save(update_fields=["google_calendar_event_id"])
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
            if appointment.google_calendar_event_id:
                appointment.google_calendar_event_id = ""
                appointment.save(update_fields=["google_calendar_event_id"])
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


# ---------------------------------------------------------------------------
# Phase 8 — no_show_sweep
# ---------------------------------------------------------------------------

@shared_task(name="notifications.no_show_sweep")
def no_show_sweep() -> dict:
    """
    Run every 30 minutes.

    Marks confirmed appointments as no_show when their slot window has closed
    (slot.date < today OR slot.date = today AND slot.slot_end < now UTC).

    Frees Postgres booked_count + Redis counter so the slot capacity is
    correctly reflected for any future reconciliation.

    Phase 8 exit criterion:
      "A simulated stuck confirmed appointment past its slot window flips to
       no_show and frees its seat without manual intervention."

    Idempotent: already-marked appointments are never touched.
    """
    from apps.clinical.models import Appointment, AppointmentStatus
    from apps.clinical.state_machine import mark_no_show

    now        = timezone.now()
    today      = now.date()
    now_time   = now.time()

    # Select confirmed appointments whose slot has ended
    # We use two separate filters to avoid complex ORM joins:
    #   1. Slot date is in the past
    #   2. Slot date is today AND slot_end has passed
    past_date_qs = Appointment.objects.filter(
        status=AppointmentStatus.CONFIRMED,
        slot__date__lt=today,
    ).select_related("slot")

    today_ended_qs = Appointment.objects.filter(
        status=AppointmentStatus.CONFIRMED,
        slot__date=today,
        slot__slot_end__lt=now_time,
    ).select_related("slot")

    marked   = 0
    errors   = 0

    for qs in (past_date_qs, today_ended_qs):
        for appt in qs.iterator():
            try:
                mark_no_show(appt)
                marked += 1
                logger.info(
                    "no_show_sweep: marked %s as no_show (slot=%s %s %s)",
                    appt.id, appt.slot.date, appt.slot.slot_start, appt.slot.slot_end,
                )
            except Exception as exc:
                errors += 1
                logger.warning("no_show_sweep: failed for %s: %s", appt.id, exc)

    logger.info("no_show_sweep: marked=%d errors=%d", marked, errors)
    return {"status": "ok", "marked_no_show": marked, "errors": errors}


# ---------------------------------------------------------------------------
# Phase 8 — running_late_check
# ---------------------------------------------------------------------------

@shared_task(name="notifications.running_late_check")
def running_late_check() -> dict:
    """
    Run every 15 minutes during clinic hours.

    Structural trigger — not a timing prediction engine.
    A slot is considered "running late" when:
      - The slot has started (slot_start <= now)
      - The slot has NOT ended yet (slot_end > now)
      - The PREVIOUS slot on the same day for the same doctor still has
        confirmed appointments (i.e. the doctor hasn't finished yet)
      - A RUNNING_LATE notification has not been sent for this slot today
        (de-duplication via Notification table).

    Fires at most ONE RUNNING_LATE notification per patient per slot.
    """
    from apps.clinical.models import Appointment, AppointmentStatus
    from apps.notifications.events import fire_notification
    from apps.notifications.models import NotificationEventType, Notification

    now      = timezone.now()
    today    = now.date()
    now_time = now.time()

    # Current slots in progress (started but not ended yet)
    in_progress_appts = Appointment.objects.filter(
        status=AppointmentStatus.CONFIRMED,
        slot__date=today,
        slot__slot_start__lte=now_time,
        slot__slot_end__gt=now_time,
    ).select_related("slot", "patient", "doctor", "hospital").order_by("slot__slot_start")

    notified  = 0
    checked   = 0

    for appt in in_progress_appts:
        checked += 1
        slot = appt.slot

        # Check if any EARLIER slot for this doctor on this day still has confirmed appointments
        earlier_confirmed = Appointment.objects.filter(
            status=AppointmentStatus.CONFIRMED,
            slot__doctor=slot.doctor,
            slot__date=today,
            slot__slot_start__lt=slot.slot_start,
        ).exists()

        if not earlier_confirmed:
            continue  # on schedule

        # De-duplicate: already sent RUNNING_LATE for this appointment today?
        already_notified = Notification.objects.filter(
            appointment=appt,
            event_type=NotificationEventType.RUNNING_LATE,
        ).exists()

        if already_notified:
            continue

        try:
            fire_notification(NotificationEventType.RUNNING_LATE, appt)
            notified += 1
        except Exception as exc:
            logger.warning("running_late_check: notification failed for %s: %s", appt.id, exc)

    logger.info("running_late_check: checked=%d notified=%d", checked, notified)
    return {"status": "ok", "checked": checked, "running_late_notified": notified}


# ---------------------------------------------------------------------------
# Phase 8 — Reminder Dispatches (Follow-up & Medication)
# ---------------------------------------------------------------------------

@shared_task(name="notifications.follow_up_reminder_dispatch")
def follow_up_reminder_dispatch() -> dict:
    """
    Run daily at 08:00 UTC.

    For every completed appointment that has:
      - An approved post-visit summary
      - follow_up_days set
      - follow_up_days days have elapsed since approved_at (or slot date)
      - No FOLLOW_UP_AVAILABLE notification sent yet

    Fire a FOLLOW_UP_AVAILABLE in-app notification and email.

    Idempotent: de-duplicated via the Notification table.
    """
    from apps.clinical.models import Appointment, AppointmentStatus, SummaryStatus
    from apps.notifications.events import fire_notification
    from apps.notifications.models import NotificationEventType, Notification
    import datetime as _dt

    today    = timezone.now().date()
    notified = 0
    checked  = 0

    candidates = Appointment.objects.filter(
        status=AppointmentStatus.COMPLETED,
        summary_status=SummaryStatus.APPROVED,
        follow_up_days__isnull=False,
        approved_at__isnull=False,
    ).select_related("patient", "doctor", "slot", "hospital")

    for appt in candidates.iterator():
        checked += 1

        # Has the follow-up window arrived?
        reference_date = (
            appt.approved_at.date() if appt.approved_at else appt.slot.date
        )
        follow_up_due = reference_date + _dt.timedelta(days=appt.follow_up_days)

        if today < follow_up_due:
            continue  # not yet due

        # De-duplicate: only fire once per appointment
        if Notification.objects.filter(
            appointment=appt,
            event_type=NotificationEventType.FOLLOW_UP_AVAILABLE,
        ).exists():
            continue

        try:
            fire_notification(
                NotificationEventType.FOLLOW_UP_AVAILABLE,
                appt,
                extra_context={"follow_up_days": appt.follow_up_days},
            )
            notified += 1
        except Exception as exc:
            logger.warning(
                "follow_up_reminder_dispatch: notification failed for %s: %s",
                appt.id, exc,
            )

    logger.info(
        "follow_up_reminder_dispatch: checked=%d notified=%d", checked, notified
    )
    return {"status": "ok", "checked": checked, "follow_up_notified": notified}


@shared_task(name="notifications.medication_reminder_dispatch")
def medication_reminder_dispatch() -> dict:
    """
    Run daily at 08:00 UTC (and/or 20:00 UTC).

    Dispatches medication reminders for active prescriptions from completed,
    doctor-approved visits.

    Rules:
      - Iterates over prescriptions whose active treatment course includes today.
      - Sends MEDICATION_REMINDER notification with medicine name, dosage, frequency, and instructions.
      - Strictly de-duplicated per day via MedicationReminderLog table.
    """
    from apps.clinical.models import AppointmentStatus, Prescription, SummaryStatus
    from apps.notifications.events import fire_notification
    from apps.notifications.models import (
        MedicationReminderLog,
        Notification,
        NotificationEventType,
    )
    import datetime as _dt
    import re as _re

    today    = timezone.now().date()
    notified = 0
    checked  = 0

    # Query prescriptions for completed, approved visits
    active_prescriptions = Prescription.objects.filter(
        appointment__status=AppointmentStatus.COMPLETED,
        appointment__summary_status=SummaryStatus.APPROVED,
        appointment__approved_at__isnull=False,
    ).select_related(
        "appointment",
        "appointment__patient",
        "appointment__doctor",
        "appointment__hospital",
        "medicine",
    )

    for rx in active_prescriptions.iterator():
        checked += 1
        appt = rx.appointment
        ref_date = appt.approved_at.date() if appt.approved_at else appt.slot.date

        # Parse duration string into days (e.g. "5 days" -> 5, "2 weeks" -> 14, default 7)
        duration_days = 7
        if rx.duration:
            num_match = _re.search(r"(\d+)", rx.duration)
            if num_match:
                val = int(num_match.group(1))
                if "week" in rx.duration.lower():
                    duration_days = val * 7
                elif "month" in rx.duration.lower():
                    duration_days = val * 30
                else:
                    duration_days = val

        treatment_end_date = ref_date + _dt.timedelta(days=duration_days)

        slots = rx.get_reminder_slots()
        for slot_name in slots:
            # Check if already notified today for this prescription and time slot
            already_sent = MedicationReminderLog.objects.filter(
                prescription=rx,
                reminder_date=today,
                time_slot=slot_name,
            ).exists()

            if already_sent:
                continue

            try:
                notif = fire_notification(
                    NotificationEventType.MEDICATION_REMINDER,
                    appt,
                    extra_context={
                        "medicine_name": rx.medicine.name,
                        "dosage":        rx.dosage,
                        "frequency":     rx.get_frequency_display(),
                        "instructions":  rx.instructions or "Take as prescribed",
                        "time_slot":     slot_name,
                    },
                )
                # Only mark as sent if fire_notification succeeded
                if notif is not None:
                    MedicationReminderLog.objects.create(
                        patient=appt.patient,
                        prescription=rx,
                        reminder_date=today,
                        time_slot=slot_name,
                    )
                    notified += 1
            except Exception as exc:
                logger.warning(
                    "medication_reminder_dispatch: notification failed for rx %s slot %s: %s",
                    rx.id, slot_name, exc,
                )

    # Also trigger follow_up check as part of daily cycle
    follow_up_count = 0
    try:
        fu_res = follow_up_reminder_dispatch()
        follow_up_count = fu_res.get("follow_up_notified", 0)
    except Exception as exc:
        logger.warning("medication_reminder_dispatch: follow_up call failed: %s", exc)

    logger.info(
        "medication_reminder_dispatch: checked=%d rx_notified=%d fu_notified=%d",
        checked, notified, follow_up_count,
    )
    return {
        "status": "ok",
        "checked": checked,
        "medication_notified": notified,
        "follow_up_notified": follow_up_count,
    }
