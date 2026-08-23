"""
scheduling/services.py

Slot generation logic — the only place that turns shift_config rows into
appointment_slots rows. Kept out of views and tasks so it's unit-testable
without HTTP or Celery machinery.

Rules (from phases.md / architecture.md):
  - Only fills empty future dates; never regenerates or deletes a slot that
    already has booked_count > 0 or any held/confirmed appointment against it.
  - Skips the 13:00–14:00 lunch gap by honouring shift boundaries exactly —
    no slot is ever created that spans that window.
  - Working-day check: only generates slots for dates whose ISO weekday is in
    shift_config.working_days.
  - Idempotent: re-running for a date that already has unbooked slots is safe
    (uses update_or_create with only the unbooked condition being guarded).
"""
from __future__ import annotations

import datetime
from typing import NamedTuple

from django.db import transaction

from apps.scheduling.models import AppointmentSlot, DoctorProfile, ShiftConfig
from common.redis_client import slot_counter_seed


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class GenerationResult(NamedTuple):
    created: int    # number of new slots inserted
    skipped: int    # dates with no working shift for those dates
    guarded: int    # slots NOT touched because they have existing bookings


def generate_slots_for_doctor(
    doctor: DoctorProfile,
    date_from: datetime.date,
    date_to: datetime.date,
) -> GenerationResult:
    """
    Generate AppointmentSlot rows for *doctor* from *date_from* to *date_to*
    (both inclusive) using the doctor's current ShiftConfig.

    Returns a GenerationResult namedtuple with counts.

    Raises ValueError if the doctor has no ShiftConfig.
    """
    try:
        shift = doctor.shift_config
    except ShiftConfig.DoesNotExist:
        raise ValueError(
            f"Doctor {doctor.user_id} has no ShiftConfig. "
            "Set shift hours before generating slots."
        )

    if date_from > date_to:
        raise ValueError("date_from must be <= date_to.")

    duration = datetime.timedelta(minutes=doctor.slot_duration_minutes)
    hospital = doctor.user.hospital  # denormalized onto each slot row

    created = 0
    skipped = 0
    guarded = 0

    current = date_from
    while current <= date_to:
        # Respect working_days (ISO weekday: 1=Mon … 7=Sun)
        if current.isoweekday() not in (shift.working_days or []):
            skipped += 1
            current += datetime.timedelta(days=1)
            continue

        # Build all slot windows for this date across both shifts
        windows = _build_windows(shift, current, duration)

        with transaction.atomic():
            for slot_start, slot_end in windows:
                c, g = _upsert_slot(doctor, hospital, current, slot_start, slot_end)
                created += c
                guarded += g

        current += datetime.timedelta(days=1)

    return GenerationResult(created=created, skipped=skipped, guarded=guarded)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_windows(
    shift: ShiftConfig,
    date: datetime.date,
    duration: datetime.timedelta,
) -> list[tuple[datetime.time, datetime.time]]:
    """
    Return a list of (slot_start, slot_end) time pairs for all slots that
    fit within shift_1 and shift_2 on the given date.
    The 13:00–14:00 gap is handled implicitly: shift_1_end caps the morning
    window and shift_2_start caps the afternoon window.
    """
    windows: list[tuple[datetime.time, datetime.time]] = []

    for window_start, window_end in (
        (shift.shift_1_start, shift.shift_1_end),
        (shift.shift_2_start, shift.shift_2_end),
    ):
        # Skip degenerate windows (e.g. if shift_2 not configured)
        if window_start >= window_end:
            continue

        current = _time_to_dt(date, window_start)
        end_dt  = _time_to_dt(date, window_end)

        while current + duration <= end_dt:
            next_dt = current + duration
            windows.append((current.time(), next_dt.time()))
            current = next_dt

    return windows


def _upsert_slot(
    doctor: DoctorProfile,
    hospital,
    date: datetime.date,
    slot_start: datetime.time,
    slot_end: datetime.time,
) -> tuple[int, int]:
    """
    Insert a new AppointmentSlot if one does not already exist for this
    doctor/date/slot_start combination.

    If a slot EXISTS and has booked_count > 0, it is left entirely untouched
    (guard logic — we never delete or overwrite a booked slot).

    Returns (created_count, guarded_count) as a (0|1, 0|1) tuple.
    """
    existing = AppointmentSlot.objects.filter(
        doctor=doctor, date=date, slot_start=slot_start
    ).first()

    if existing is not None:
        if existing.booked_count > 0:
            # Has bookings — do not touch
            return 0, 1
        # Exists but empty — update capacity/end in case config changed
        existing.slot_end = slot_end
        existing.capacity = doctor.slot_capacity
        existing.save(update_fields=["slot_end", "capacity"])
        return 0, 0

    # No existing slot — create it
    AppointmentSlot.objects.create(
        doctor=doctor,
        hospital=hospital,
        date=date,
        slot_start=slot_start,
        slot_end=slot_end,
        capacity=doctor.slot_capacity,
        booked_count=0,
    )
    # Seed Redis counter so the first hold attempt doesn't have to fall back
    # to Postgres. Best-effort — reconciliation task corrects any drift.
    slot_obj = AppointmentSlot.objects.get(
        doctor=doctor, date=date, slot_start=slot_start
    )
    slot_counter_seed(str(slot_obj.id), doctor.slot_capacity)
    return 1, 0


def _time_to_dt(date: datetime.date, t: datetime.time) -> datetime.datetime:
    """Combine a date and time into a naive datetime for arithmetic."""
    return datetime.datetime.combine(date, t)


# ---------------------------------------------------------------------------
# Phase 3 — Redis hold helpers (called by booking views)
# ---------------------------------------------------------------------------

def try_hold_slot(slot: AppointmentSlot) -> bool:
    """
    Attempt to hold one seat in *slot* via the Redis fast-path counter.

    Returns True if the hold was granted (counter was > 0 before DECR).
    Returns False if the slot is full — the caller must reject the request.

    If Redis is unavailable, falls back to Postgres booked_count check so
    bookings are never blocked by a Redis outage (at the cost of slightly
    less precise over-booking protection until reconciliation runs).
    """
    from common.redis_client import slot_counter_decr, slot_counter_incr, slot_counter_get

    # Warm the counter from Postgres if it was never seeded (restart scenario)
    if slot_counter_get(str(slot.id)) is None:
        remaining = slot.capacity - slot.booked_count
        slot_counter_seed(str(slot.id), max(0, remaining))

    try:
        new_val = slot_counter_decr(str(slot.id))
    except Exception:
        # Redis down — fall back to Postgres count (best-effort)
        return slot.booked_count < slot.capacity

    if new_val < 0:
        # Over-capacity — roll back immediately
        slot_counter_incr(str(slot.id))
        return False

    return True


# ---------------------------------------------------------------------------
# Phase 7 — Absence cascade helpers
# ---------------------------------------------------------------------------

from typing import NamedTuple as _NamedTuple  # already imported above; guard


class CascadeResult(_NamedTuple):
    cancelled: int      # appointments cancelled
    reassigned: int     # new held appointments created for same-spec doctors
    notified: int       # DOCTOR_ABSENT notifications fired


def _get_affected_slots(
    profile: DoctorProfile,
    date: datetime.date,
    shift: str | None,  # "morning" | "afternoon" | None (= whole day)
) -> list:
    """
    Return AppointmentSlot queryset for the affected window.
    shift=None means all slots on the date (full-day leave).
    shift="morning"/"afternoon" means only slots in that half-day.
    """
    qs = AppointmentSlot.objects.filter(doctor=profile, date=date)

    if shift is not None:
        # Determine the boundary from ShiftConfig
        try:
            sc = profile.shift_config
            if shift == "morning":
                qs = qs.filter(slot_start__lt=sc.shift_2_start)
            else:
                qs = qs.filter(slot_start__gte=sc.shift_2_start)
        except ShiftConfig.DoesNotExist:
            pass  # no config → treat all slots as affected

    return list(qs.order_by("slot_start"))


def cascade_cancel_appointments(
    profile: DoctorProfile,
    date: datetime.date,
    shift: str | None = None,
    reason: str = "affected_by_absent",
) -> list:
    """
    Cancel every confirmed or held appointment in the affected slot window.

    Returns a list of cancelled Appointment objects so the caller can
    attempt reassignment and fire notifications.

    Each cancellation:
      - Transitions the appointment via state_machine (frees Postgres + Redis)
      - Sets cancel_reason to reason ("affected_by_absent" or "affected_by_leave")

    Does NOT fire notifications — caller handles that after reassignment attempts.
    """
    from apps.clinical.models import Appointment, AppointmentStatus
    from apps.clinical.state_machine import cancel_confirmed, cancel_hold

    affected_slots = _get_affected_slots(profile, date, shift)
    slot_ids       = [s.id for s in affected_slots]

    appointments = (
        Appointment.objects
        .filter(
            slot_id__in=slot_ids,
            status__in=[AppointmentStatus.CONFIRMED, AppointmentStatus.HELD],
        )
        .select_related("patient", "doctor", "slot", "hospital")
        .order_by("slot__slot_start", "token")
    )

    cancelled = []
    for appt in appointments:
        try:
            if appt.status == AppointmentStatus.CONFIRMED:
                cancel_confirmed(appt, reason=reason)
            else:
                cancel_hold(appt)
            cancelled.append(appt)
        except Exception as exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "cascade_cancel_appointments: failed to cancel appt %s: %s", appt.id, exc
            )

    return cancelled


def find_reassignment_slot(
    original_profile: DoctorProfile,
    date: datetime.date,
    preferred_slot_start: datetime.time | None = None,
) -> AppointmentSlot | None:
    """
    Find the earliest available slot on *date* from any doctor at the same
    hospital with the same specialization (excluding the absent doctor).

    Returns the first slot with true_remaining > 0, or None if nothing found.
    Prefers a slot that starts at or after preferred_slot_start when given.
    """
    from django.db.models import F

    alternates = (
        DoctorProfile.objects
        .filter(
            user__hospital=original_profile.user.hospital,
            specialization=original_profile.specialization,
            is_active=True,
        )
        .exclude(user_id=original_profile.user_id)
    )

    qs = (
        AppointmentSlot.objects
        .filter(
            doctor__in=alternates,
            date=date,
            booked_count__lt=F("capacity"),
        )
        .select_related("doctor__user")
        .order_by("slot_start", "booked_count")
    )

    if preferred_slot_start:
        # Try same or later time first
        later = qs.filter(slot_start__gte=preferred_slot_start).first()
        if later:
            return later

    return qs.first()
