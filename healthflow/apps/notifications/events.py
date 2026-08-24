"""
notifications/events.py

The single place that converts an appointment lifecycle event into:
  1. A Notification row  (in-app, immediate)
  2. An EmailJob row     (queued, retried by Celery)

Both are created inside the caller's transaction.atomic() block — they are
always created together or not at all.

Rules (phases.md Phase 6):
  - fire_notification() is called from clinical/state_machine.py AFTER the
    status transition is committed.
  - Never called from a view directly — views call state_machine functions.
  - ICS generation is enqueued here as a side-task for booking_confirmed.
  - Google Calendar sync is enqueued here for confirmed / cancelled / rescheduled.
  - MongoDB or Redis failures must not block notification creation.
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.notifications.models import (
    EmailJob,
    EmailJobStatus,
    Notification,
    NotificationEventType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict[str, str]] = {
    NotificationEventType.BOOKING_CONFIRMED: {
        "title": "Appointment confirmed",
        "body":  "Your appointment with {doctor_name} on {slot_date} at {slot_time} is confirmed. Token #{token}.",
        "subject": "Your HealthFlow appointment is confirmed",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Your appointment with {doctor_name} on {slot_date} at {slot_time} "
            "has been confirmed.\n\nToken number: #{token}\n\n"
            "A calendar invite is attached to this email.\n\n"
            "HealthFlow"
        ),
    },
    NotificationEventType.BOOKING_CANCELLED: {
        "title": "Appointment cancelled",
        "body":  "Your appointment with {doctor_name} on {slot_date} has been cancelled.",
        "subject": "Your HealthFlow appointment has been cancelled",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Your appointment with {doctor_name} on {slot_date} has been cancelled.\n\n"
            "You can book a new appointment at any time.\n\nHealthFlow"
        ),
    },
    NotificationEventType.BOOKING_RESCHEDULED: {
        "title": "Appointment rescheduled",
        "body":  "Your appointment has been rescheduled to {slot_date} at {slot_time}. Token #{token}.",
        "subject": "Your HealthFlow appointment has been rescheduled",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Your appointment has been rescheduled.\n\n"
            "New date: {slot_date} at {slot_time}\nToken: #{token}\n\n"
            "An updated calendar invite is attached.\n\nHealthFlow"
        ),
    },
    NotificationEventType.VISIT_SUMMARY_READY: {
        "title": "Your visit summary is ready",
        "body":  "Your visit summary from {slot_date} with {doctor_name} has been approved.",
        "subject": "Your HealthFlow visit summary is ready",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Your visit summary from {slot_date} has been approved by {doctor_name}.\n\n"
            "Log in to view your summary, prescription, and any follow-up notes.\n\n"
            "HealthFlow"
        ),
    },
    NotificationEventType.DOCTOR_ABSENT: {
        "title": "Doctor unavailable",
        "body":  "Dr {doctor_name} is unavailable for your appointment on {slot_date}. We'll reach out with options.",
        "subject": "Update on your HealthFlow appointment",
        "email_text": (
            "Hello {patient_name},\n\n"
            "We're sorry — {doctor_name} is unavailable for your appointment on {slot_date}.\n\n"
            "Our team will contact you with available alternatives.\n\nHealthFlow"
        ),
    },
    NotificationEventType.RESCHEDULE_OFFER: {
        "title": "Alternative appointment available",
        "body":  "Dr {doctor_name} is unavailable. An alternative slot is available on {slot_date} at {slot_time}.",
        "subject": "Alternative appointment option for your HealthFlow visit",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Due to schedule changes, an alternative appointment has been offered on {slot_date} at {slot_time} with Dr {doctor_name}.\n\n"
            "Please log in to accept this slot or choose another time.\n\nHealthFlow"
        ),
    },
    NotificationEventType.RUNNING_LATE: {
        "title": "Doctor running behind schedule",
        "body":  "Dr {doctor_name} is currently running behind schedule today. Your appointment token is #{token}.",
        "subject": "Schedule update: Dr {doctor_name} is running behind schedule",
        "email_text": (
            "Hello {patient_name},\n\n"
            "Dr {doctor_name} is currently running behind schedule today.\n\n"
            "Your appointment token is #{token}. We apologize for the inconvenience and will attend to you as soon as possible.\n\nHealthFlow"
        ),
    },
    NotificationEventType.FOLLOW_UP_AVAILABLE: {
        "title": "Follow-up consultation recommended",
        "body":  "It has been {follow_up_days} days since your visit with Dr {doctor_name}. You can now schedule your follow-up.",
        "subject": "Time to schedule your follow-up consultation with Dr {doctor_name}",
        "email_text": (
            "Hello {patient_name},\n\n"
            "It has been {follow_up_days} days since your visit with Dr {doctor_name}.\n\n"
            "Please log in to book your follow-up consultation.\n\nHealthFlow"
        ),
    },
    NotificationEventType.MEDICATION_REMINDER: {
        "title": "Medication reminder: {medicine_name}",
        "body":  "Time to take {medicine_name} ({dosage}) — {instructions}",
        "subject": "Medication reminder: {medicine_name}",
        "email_text": (
            "Hello {patient_name},\n\n"
            "This is a reminder to take your prescribed medication:\n\n"
            "Medicine: {medicine_name}\n"
            "Dosage: {dosage}\n"
            "Instructions: {instructions}\n\n"
            "HealthFlow"
        ),
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fire_notification(
    event_type: str,
    appointment,          # apps.clinical.models.Appointment
    extra_context: dict[str, Any] | None = None,
) -> Notification | None:
    """
    Create a Notification + EmailJob for the given appointment event.

    Must be called inside a transaction (typically the state_machine transition).
    Returns the created Notification or None on failure.

    Failures are logged but never raise — notification failures must not
    roll back the appointment transition.
    """
    template = _TEMPLATES.get(event_type)
    if not template:
        logger.warning("fire_notification: no template for event_type=%s", event_type)
        return None

    ctx = _build_context(appointment, extra_context or {})

    # Pre-generate ICS attachment for booking confirmed / rescheduled so it is
    # reliably attached in the database before email sending begins
    ics_attachment = ""
    if event_type in (
        NotificationEventType.BOOKING_CONFIRMED,
        NotificationEventType.BOOKING_RESCHEDULED,
    ) and getattr(appointment, "slot", None):
        try:
            from apps.notifications.tasks import _build_ics
            ics_attachment = _build_ics(appointment)
        except Exception as ics_err:
            logger.warning("fire_notification: failed to pre-build ics: %s", ics_err)

    try:
        with transaction.atomic():
            notif = Notification.objects.create(
                patient     = appointment.patient,
                hospital    = appointment.hospital,
                appointment = appointment,
                event_type  = event_type,
                title       = template["title"].format(**ctx),
                body        = template["body"].format(**ctx),
            )

            EmailJob.objects.create(
                notification    = notif,
                recipient_email = appointment.patient.email,
                subject         = template["subject"].format(**ctx),
                body_text       = template["email_text"].format(**ctx),
                ics_attachment  = ics_attachment,
            )

            # Doctor notification for booking lifecycle events
            if appointment.doctor and appointment.doctor.email and event_type in (
                NotificationEventType.BOOKING_CONFIRMED,
                NotificationEventType.BOOKING_CANCELLED,
                NotificationEventType.BOOKING_RESCHEDULED,
            ):
                doc_subjects = {
                    NotificationEventType.BOOKING_CONFIRMED:   f"New Booking: {appointment.patient.name} on {ctx['slot_date']}",
                    NotificationEventType.BOOKING_CANCELLED:   f"Booking Cancelled: {appointment.patient.name} on {ctx['slot_date']}",
                    NotificationEventType.BOOKING_RESCHEDULED: f"Booking Rescheduled: {appointment.patient.name} to {ctx['slot_date']}",
                }
                doc_bodies = {
                    NotificationEventType.BOOKING_CONFIRMED:   f"Hello Dr. {appointment.doctor.name},\n\nA new appointment has been confirmed with {appointment.patient.name} on {ctx['slot_date']} at {ctx['slot_time']}.\nToken: #{ctx['token']}.\n\nHealthFlow",
                    NotificationEventType.BOOKING_CANCELLED:   f"Hello Dr. {appointment.doctor.name},\n\nThe appointment with {appointment.patient.name} on {ctx['slot_date']} has been cancelled.\n\nHealthFlow",
                    NotificationEventType.BOOKING_RESCHEDULED: f"Hello Dr. {appointment.doctor.name},\n\nThe appointment with {appointment.patient.name} has been rescheduled to {ctx['slot_date']} at {ctx['slot_time']}.\nToken: #{ctx['token']}.\n\nHealthFlow",
                }
                doc_notif = Notification.objects.create(
                    patient     = appointment.doctor,
                    hospital    = appointment.hospital,
                    appointment = appointment,
                    event_type  = event_type,
                    title       = doc_subjects[event_type],
                    body        = doc_bodies[event_type],
                )
                doc_job = EmailJob.objects.create(
                    notification    = doc_notif,
                    recipient_email = appointment.doctor.email,
                    subject         = doc_subjects[event_type],
                    body_text       = doc_bodies[event_type],
                    ics_attachment  = ics_attachment if event_type != NotificationEventType.BOOKING_CANCELLED else "",
                )
                from apps.notifications.tasks import send_email_job
                send_email_job.delay(str(doc_job.id))

        # Enqueue async tasks — best-effort, don't block the response
        _enqueue_side_tasks(event_type, appointment, notif)

        return notif

    except Exception as exc:
        logger.exception(
            "fire_notification: failed to create notification for appt=%s event=%s: %s",
            appointment.id, event_type, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_context(appointment, extra: dict) -> dict:
    ctx = {
        "patient_name":   appointment.patient.name,
        "doctor_name":    appointment.doctor.name if appointment.doctor else "Doctor",
        "slot_date":      "",
        "slot_time":      "",
        "token":          appointment.token or "—",
        "delay_minutes":  30,
        "follow_up_days": getattr(appointment, "follow_up_days", 7) or 7,
        "medicine_name":  "Medication",
        "dosage":         "",
        "instructions":   "Take as prescribed",
        "frequency":      "",
    }
    try:
        if getattr(appointment, "slot", None):
            ctx["slot_date"] = appointment.slot.date.strftime("%d %b %Y")
            ctx["slot_time"] = appointment.slot.slot_start.strftime("%H:%M")
    except Exception:
        pass
    ctx.update(extra)
    return ctx


def _enqueue_side_tasks(event_type: str, appointment, notif: Notification) -> None:
    """
    Enqueue async side-tasks for the event.
    All enqueue calls are best-effort — failures are logged, not raised.
    """
    try:
        from apps.notifications.tasks import (
            send_email_job,
            sync_google_calendar_event,
            generate_ics,
        )

        # Ensure ICS task is also enqueued if not already populated
        if event_type in (
            NotificationEventType.BOOKING_CONFIRMED,
            NotificationEventType.BOOKING_RESCHEDULED,
        ) and not notif.email_job.ics_attachment:
            generate_ics.delay(str(appointment.id), str(notif.email_job.id))

        # Send email — always
        send_email_job.delay(str(notif.email_job.id))

        # Google Calendar — on confirmed, cancelled, rescheduled
        if event_type in (
            NotificationEventType.BOOKING_CONFIRMED,
            NotificationEventType.BOOKING_CANCELLED,
            NotificationEventType.BOOKING_RESCHEDULED,
        ):
            action = {
                NotificationEventType.BOOKING_CONFIRMED:   "create",
                NotificationEventType.BOOKING_CANCELLED:   "delete",
                NotificationEventType.BOOKING_RESCHEDULED: "update",
            }[event_type]
            sync_google_calendar_event.delay(str(appointment.id), action)

    except Exception as exc:
        logger.warning(
            "_enqueue_side_tasks: failed for appt=%s event=%s: %s",
            appointment.id, event_type, exc,
        )
