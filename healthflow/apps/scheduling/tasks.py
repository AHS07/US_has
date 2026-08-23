"""
scheduling/tasks.py

Celery tasks for slot generation and counter reconciliation.

Phase 2: slot_generation_task (on-demand + nightly beat schedule).
Phase 3: reconcile_slot_counters now fully active — resyncs Redis against
         Postgres booked_count for all upcoming slots.
"""
from __future__ import annotations

import datetime
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="scheduling.slot_generation_task",
)
def slot_generation_task(
    self,
    doctor_user_id: str,
    date_from_iso: str,
    date_to_iso: str,
) -> dict:
    """
    Generate appointment slots for one doctor over a date range.
    Called on-demand via POST /admin-api/doctors/<id>/slots/generate and
    nightly via django-celery-beat (rolling 30-day window).
    """
    from apps.scheduling.models import DoctorProfile
    from apps.scheduling.services import generate_slots_for_doctor

    try:
        doctor = DoctorProfile.objects.select_related(
            "shift_config", "user__hospital"
        ).get(user_id=doctor_user_id)
    except DoctorProfile.DoesNotExist:
        logger.error(
            "slot_generation_task: DoctorProfile not found for user_id=%s",
            doctor_user_id,
        )
        return {"status": "error", "detail": "Doctor not found."}

    date_from = datetime.date.fromisoformat(date_from_iso)
    date_to   = datetime.date.fromisoformat(date_to_iso)

    try:
        result = generate_slots_for_doctor(doctor, date_from, date_to)
    except ValueError as exc:
        logger.error(
            "slot_generation_task: ValueError for doctor=%s: %s",
            doctor_user_id, exc,
        )
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:
        logger.exception(
            "slot_generation_task: unexpected error for doctor=%s",
            doctor_user_id,
        )
        raise self.retry(exc=exc)

    summary = {
        "status":    "ok",
        "doctor_id": doctor_user_id,
        "date_from": date_from_iso,
        "date_to":   date_to_iso,
        "created":   result.created,
        "skipped":   result.skipped,
        "guarded":   result.guarded,
    }
    logger.info("slot_generation_task completed: %s", summary)
    return summary


@shared_task(name="scheduling.reconcile_slot_counters")
def reconcile_slot_counters() -> dict:
    """
    Hourly: resync Redis slot:{id}:remaining against Postgres booked_count
    for all upcoming slots (today and forward, status != cancelled).

    Postgres is always the source of truth. Redis is disposable — we just
    SET it to (capacity - booked_count) for every upcoming slot.
    This corrects any drift from crashed processes or missed INCR/DECR calls.
    """
    from apps.scheduling.models import AppointmentSlot
    from common.redis_client import slot_counter_set

    today = datetime.date.today()

    upcoming = AppointmentSlot.objects.filter(date__gte=today).only(
        "id", "capacity", "booked_count"
    )

    synced = 0
    for slot in upcoming.iterator():
        remaining = max(0, slot.capacity - slot.booked_count)
        slot_counter_set(str(slot.id), remaining)
        synced += 1

    logger.info("reconcile_slot_counters: synced %d slots", synced)
    return {"status": "ok", "synced": synced}


# ---------------------------------------------------------------------------
# Phase 7 — Absence cascade task
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    name="scheduling.cascade_absence_task",
    acks_late=True,
)
def cascade_absence_task(
    self,
    doctor_user_id: str,
    date_iso: str,
    shift: str | None = None,   # "morning" | "afternoon" | None (full day)
    reason: str = "affected_by_absent",
) -> dict:
    """
    Phase 7 cascade pipeline:
      1. Cancel every confirmed/held appointment in the affected window
      2. For each cancelled appointment, find a same-specialization alternate slot
      3. If found → create a new held appointment (reassigned flow) and fire
         RESCHEDULE_OFFER notification
      4. If not found → fire DOCTOR_ABSENT notification
      5. Mark the original appointment as reassigned (state_machine)

    The task is idempotent: appointments already cancelled are skipped silently.
    """
    from apps.clinical.models import Appointment, AppointmentStatus
    from apps.clinical.state_machine import mark_reassigned
    from apps.scheduling.models import DoctorProfile
    from apps.scheduling.services import cascade_cancel_appointments, find_reassignment_slot
    from django.utils import timezone

    try:
        profile = DoctorProfile.objects.select_related(
            "user__hospital", "shift_config"
        ).get(user_id=doctor_user_id)
    except DoctorProfile.DoesNotExist:
        logger.error("cascade_absence_task: DoctorProfile not found for user_id=%s", doctor_user_id)
        return {"status": "error", "detail": "Doctor not found."}

    date = datetime.date.fromisoformat(date_iso)

    try:
        cancelled_appts = cascade_cancel_appointments(profile, date, shift, reason=reason)
    except Exception as exc:
        logger.exception("cascade_absence_task: cascade_cancel_appointments failed: %s", exc)
        raise self.retry(exc=exc)

    HOLD_TTL = 600  # seconds — patients have 10 min to confirm the new slot

    reassigned_count = 0
    notified_absent  = 0
    notified_offer   = 0

    for original_appt in cancelled_appts:
        try:
            alt_slot = find_reassignment_slot(
                profile,
                date,
                preferred_slot_start=original_appt.slot.slot_start,
            )

            if alt_slot:
                # Create new held appointment (symptom text + original_request carried forward)
                held_until = timezone.now() + datetime.timedelta(seconds=HOLD_TTL)
                new_appt = Appointment.objects.create(
                    patient          = original_appt.patient,
                    doctor           = alt_slot.doctor.user,
                    slot             = alt_slot,
                    hospital         = alt_slot.hospital,
                    status           = AppointmentStatus.HELD,
                    held_until       = held_until,
                    symptom_text     = original_appt.symptom_text,
                    urgency_level    = original_appt.urgency_level,
                    original_request = original_appt,
                    reassignment_note=(
                        f"Reassigned from Dr {original_appt.doctor.name} "
                        f"({_shift_label(shift)}) to "
                        f"Dr {alt_slot.doctor.user.name} at "
                        f"{alt_slot.slot_start.strftime('%H:%M')}."
                    ),
                )
                # Decrement Redis counter for the new slot
                from apps.scheduling.services import try_hold_slot
                try_hold_slot(alt_slot)

                # Fire RESCHEDULE_OFFER notification for the new appointment
                try:
                    from apps.notifications.events import fire_notification
                    from apps.notifications.models import NotificationEventType
                    fire_notification(NotificationEventType.RESCHEDULE_OFFER, new_appt)
                    notified_offer += 1
                except Exception as n_exc:
                    logger.warning("cascade: RESCHEDULE_OFFER notification failed: %s", n_exc)

                reassigned_count += 1

            else:
                # No alternate slot available — notify patient of cancellation
                try:
                    from apps.notifications.events import fire_notification
                    from apps.notifications.models import NotificationEventType
                    fire_notification(NotificationEventType.DOCTOR_ABSENT, original_appt)
                    notified_absent += 1
                except Exception as n_exc:
                    logger.warning("cascade: DOCTOR_ABSENT notification failed: %s", n_exc)

        except Exception as exc:
            logger.warning(
                "cascade_absence_task: failed to process appt %s: %s",
                original_appt.id, exc,
            )

    result = {
        "status":       "ok",
        "cancelled":    len(cancelled_appts),
        "reassigned":   reassigned_count,
        "notified_absent": notified_absent,
        "notified_offer":  notified_offer,
        "doctor_id":    doctor_user_id,
        "date":         date_iso,
        "shift":        shift,
    }
    logger.info("cascade_absence_task completed: %s", result)
    return result


def _shift_label(shift: str | None) -> str:
    if shift == "morning":   return "morning shift"
    if shift == "afternoon": return "afternoon shift"
    return "all shifts"
