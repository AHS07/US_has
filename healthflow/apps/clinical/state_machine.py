"""
clinical/state_machine.py

The ONLY place appointment status transitions happen.
Views enqueue work and call transition functions here; they never write
appointment.status directly.

Valid transitions:
  held        → confirmed   (patient submits symptom form)
  held        → cancelled   (patient abandons hold / TTL sweep)
  confirmed   → completed   (doctor marks visit done — Phase 5)
  confirmed   → cancelled   (patient cancel OR admin/leave cascade — Phase 7)
  confirmed   → no_show     (background sweep — Phase 8)
  confirmed   → reassigned  (doctor-absence flow — Phase 7)
  completed   → (terminal)
  cancelled   → (terminal)
  no_show     → (terminal)
  reassigned  → (terminal — original row; a new Appointment is created)

Rules (rules.md §5):
  - Every transition is wrapped in the caller's transaction.atomic() block.
  - Redis counter is updated inside the same transition call so Postgres and
    Redis never diverge within a single request.
  - No transition bypasses this module; doing so is a bug.
"""
from __future__ import annotations

import logging

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.clinical.models import Appointment, AppointmentStatus, CancelReason, SummaryStatus
from common.redis_client import slot_counter_incr

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allowed transition map
# ---------------------------------------------------------------------------

_ALLOWED: dict[str, set[str]] = {
    AppointmentStatus.HELD:       {AppointmentStatus.CONFIRMED, AppointmentStatus.CANCELLED},
    AppointmentStatus.CONFIRMED:  {
        AppointmentStatus.COMPLETED,
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
        AppointmentStatus.REASSIGNED,
    },
    AppointmentStatus.COMPLETED:  set(),
    AppointmentStatus.CANCELLED:  set(),
    AppointmentStatus.NO_SHOW:    set(),
    AppointmentStatus.REASSIGNED: set(),
}


def _assert_transition(appointment: Appointment, to_status: str) -> None:
    allowed = _ALLOWED.get(appointment.status, set())
    if to_status not in allowed:
        raise ValidationError(
            {
                "status": (
                    f"Cannot transition appointment from '{appointment.status}' "
                    f"to '{to_status}'."
                )
            }
        )


# ---------------------------------------------------------------------------
# Public transition functions
# ---------------------------------------------------------------------------

def confirm(appointment: Appointment, symptom_text: str, token: int) -> Appointment:
    """
    held → confirmed

    Called inside the same transaction.atomic() as the booked_count increment
    (SELECT FOR UPDATE). symptom_text and token are written here.
    Redis counter is NOT decremented here — it was already decremented on hold.
    pre_summary_status stays 'pending' until the LLM job runs (Phase 4).
    """
    _assert_transition(appointment, AppointmentStatus.CONFIRMED)
    appointment.status       = AppointmentStatus.CONFIRMED
    appointment.symptom_text = symptom_text
    appointment.token        = token
    appointment.held_until   = None
    appointment.save(update_fields=["status", "symptom_text", "token", "held_until", "updated_at"])
    logger.info("Appointment %s confirmed (slot=%s token=%s)", appointment.id, appointment.slot_id, token)
    return appointment


def cancel_hold(appointment: Appointment) -> Appointment:
    """
    held → cancelled (patient abandons hold before confirming)

    Increments Redis counter back — the seat is freed immediately.
    booked_count is NOT touched because it was never incremented on hold.
    """
    _assert_transition(appointment, AppointmentStatus.CANCELLED)
    appointment.status        = AppointmentStatus.CANCELLED
    appointment.cancel_reason = CancelReason.PATIENT_INITIATED
    appointment.held_until    = None
    appointment.save(update_fields=["status", "cancel_reason", "held_until", "updated_at"])
    slot_counter_incr(str(appointment.slot_id))
    logger.info("Hold %s cancelled; Redis counter incremented for slot %s", appointment.id, appointment.slot_id)
    # Phase 6 notification
    try:
        from apps.notifications.events import fire_notification
        from apps.notifications.models import NotificationEventType
        fire_notification(NotificationEventType.BOOKING_CANCELLED, appointment)
    except Exception as exc:
        logger.warning("cancel_hold notification failed for %s: %s", appointment.id, exc)
    return appointment


def cancel_confirmed(
    appointment: Appointment,
    reason: str = CancelReason.PATIENT_INITIATED,
) -> Appointment:
    """
    confirmed → cancelled

    Decrements AppointmentSlot.booked_count under SELECT FOR UPDATE and
    increments Redis counter so the seat is immediately available again.
    """
    _assert_transition(appointment, AppointmentStatus.CANCELLED)
    from apps.scheduling.models import AppointmentSlot

    with transaction.atomic():
        slot = AppointmentSlot.objects.select_for_update().get(id=appointment.slot_id)
        if slot.booked_count > 0:
            slot.booked_count -= 1
            slot.save(update_fields=["booked_count"])

        appointment.status        = AppointmentStatus.CANCELLED
        appointment.cancel_reason = reason
        appointment.save(update_fields=["status", "cancel_reason", "updated_at"])

    slot_counter_incr(str(appointment.slot_id))
    logger.info("Confirmed appointment %s cancelled (reason=%s)", appointment.id, reason)
    # Phase 6 notification
    try:
        from apps.notifications.events import fire_notification
        from apps.notifications.models import NotificationEventType
        fire_notification(NotificationEventType.BOOKING_CANCELLED, appointment)
    except Exception as exc:
        logger.warning("cancel_confirmed notification failed for %s: %s", appointment.id, exc)
    return appointment


def mark_no_show(appointment: Appointment) -> Appointment:
    """
    confirmed → no_show  (called by the no-show sweep task, Phase 8)

    Frees booked_count + Redis counter so the seat is released.
    """
    _assert_transition(appointment, AppointmentStatus.NO_SHOW)
    from apps.scheduling.models import AppointmentSlot

    with transaction.atomic():
        slot = AppointmentSlot.objects.select_for_update().get(id=appointment.slot_id)
        if slot.booked_count > 0:
            slot.booked_count -= 1
            slot.save(update_fields=["booked_count"])

        appointment.status = AppointmentStatus.NO_SHOW
        appointment.save(update_fields=["status", "updated_at"])

    slot_counter_incr(str(appointment.slot_id))
    logger.info("Appointment %s marked no_show", appointment.id)
    return appointment


def mark_reassigned(appointment: Appointment) -> Appointment:
    """
    confirmed → reassigned  (doctor-absence cascade, Phase 7)

    Frees slot capacity. A new Appointment pointing back via
    original_request_id is created by the caller.
    """
    _assert_transition(appointment, AppointmentStatus.REASSIGNED)
    from apps.scheduling.models import AppointmentSlot

    with transaction.atomic():
        slot = AppointmentSlot.objects.select_for_update().get(id=appointment.slot_id)
        if slot.booked_count > 0:
            slot.booked_count -= 1
            slot.save(update_fields=["booked_count"])

        appointment.status = AppointmentStatus.REASSIGNED
        appointment.save(update_fields=["status", "updated_at"])

    slot_counter_incr(str(appointment.slot_id))
    logger.info("Appointment %s marked reassigned", appointment.id)
    return appointment


def complete(
    appointment: Appointment,
    follow_up_days: int | None = None,
) -> Appointment:
    """
    confirmed → completed  (manual-only, doctor-triggered via ConsultationView)

    This is the ONLY way an appointment reaches 'completed'.
    No background sweep calls this — it requires the doctor to submit notes.
    Does NOT free slot capacity (the visit happened).
    Sets summary_status = pending so post_visit_llm_job picks it up.
    """
    _assert_transition(appointment, AppointmentStatus.COMPLETED)
    appointment.status         = AppointmentStatus.COMPLETED
    appointment.follow_up_days = follow_up_days
    appointment.summary_status = SummaryStatus.PENDING
    appointment.save(update_fields=[
        "status", "follow_up_days", "summary_status", "updated_at"
    ])
    logger.info("Appointment %s completed", appointment.id)
    return appointment


def mark_summary_approved(
    appointment: Appointment,
    approved_by,
    edited_text: str | None = None,
) -> Appointment:
    """
    summary_status: draft → approved

    Called by SummaryReviewView when the doctor approves the post-visit summary.
    If the doctor edited the text, the updated version is written back to MongoDB
    by the caller before calling this function — this only flips the status.
    """
    from django.utils import timezone

    if appointment.summary_status != SummaryStatus.DRAFT:
        raise ValidationError(
            {"summary_status": f"Cannot approve a summary with status '{appointment.summary_status}'."}
        )
    appointment.summary_status = SummaryStatus.APPROVED
    appointment.approved_by    = approved_by
    appointment.approved_at    = timezone.now()
    appointment.save(update_fields=[
        "summary_status", "approved_by", "approved_at", "updated_at"
    ])
    logger.info(
        "Summary approved for appointment %s by doctor %s",
        appointment.id, approved_by.id,
    )
    # Phase 6 notification — patient can now see the summary
    try:
        from apps.notifications.events import fire_notification
        from apps.notifications.models import NotificationEventType
        fire_notification(NotificationEventType.VISIT_SUMMARY_READY, appointment)
    except Exception as exc:
        logger.warning(
            "mark_summary_approved notification failed for %s: %s", appointment.id, exc
        )
    return appointment
