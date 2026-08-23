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
