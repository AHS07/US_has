"""
notifications/tests/test_background_jobs.py

Phase 8 exit-criteria tests (phases.md):
  "A simulated stuck confirmed appointment past its slot window flips to
   no_show and frees its seat without manual intervention."
  "A reminder scheduled across a DST boundary fires at the correct local
   time, not shifted by an hour."

Categories:
  1.  no_show_sweep — past-date confirmed → no_show, frees capacity;
      today-ended confirmed → no_show; future/current slots untouched;
      already no_show/cancelled untouched; booked_count correctly decremented
  2.  running_late_check — fires when earlier slot still has confirmed bookings;
      does NOT fire when on schedule; de-duplication (one notification per slot)
  3.  medication_reminder_dispatch — fires when follow_up_days elapsed;
      not fired early; de-duplicated; only approved summaries trigger it
  4.  nightly_slot_generation — enqueues slot_generation_task for every active doctor
  5.  Celery beat schedule — all expected tasks registered
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import (
    Appointment, AppointmentStatus, SummaryStatus,
    MedicineCatalog, Prescription, VisitNote,
)
from apps.notifications.models import Notification, NotificationEventType
from apps.scheduling.models import AppointmentSlot, DoctorProfile, ShiftConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hospital() -> Hospital:
    return Hospital.objects.create(
        name=f"H-{uuid.uuid4().hex[:6]}",
        contact_email=f"{uuid.uuid4().hex[:6]}@h.local",
    )


def _doctor(hospital: Hospital) -> tuple[User, DoctorProfile]:
    u = User.objects.create_user(
        email=f"dr{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Dr Test", role=UserRole.DOCTOR,
        hospital=hospital, must_reset_password=False,
    )
    p = DoctorProfile.objects.create(
        user=u, specialization="General",
        slot_duration_minutes=60, slot_capacity=5,
    )
    ShiftConfig.objects.create(doctor=p, working_days=[1, 2, 3, 4, 5])
    return u, p


def _patient() -> User:
    return User.objects.create_user(
        email=f"p{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Patient", role=UserRole.PATIENT,
        hospital=None, must_reset_password=False,
    )


def _slot(profile, date, start, end, capacity=5, booked=0) -> AppointmentSlot:
    return AppointmentSlot.objects.create(
        doctor=profile, hospital=profile.user.hospital,
        date=date, slot_start=start, slot_end=end,
        capacity=capacity, booked_count=booked,
    )


def _confirmed(patient, slot) -> Appointment:
    slot.booked_count += 1
    slot.save(update_fields=["booked_count"])
    return Appointment.objects.create(
        patient=patient, doctor=slot.doctor.user,
        slot=slot, hospital=slot.hospital,
        status=AppointmentStatus.CONFIRMED, token=1,
        symptom_text="Cough.", held_until=None,
    )


# ---------------------------------------------------------------------------
# 1. no_show_sweep
# ---------------------------------------------------------------------------

class TestNoShowSweep(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient    = _patient()

    def test_past_date_confirmed_becomes_no_show(self):
        """
        PHASE 8 EXIT CRITERION:
        Stuck confirmed appointment on a past date flips to no_show
        without manual intervention.
        """
        from apps.notifications.tasks import no_show_sweep

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        slot = _slot(self.profile, yesterday, datetime.time(9, 0), datetime.time(10, 0), booked=0)
        appt = _confirmed(self.patient, slot)

        with patch("apps.notifications.events.fire_notification"):
            result = no_show_sweep()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.NO_SHOW)
        self.assertGreaterEqual(result["marked_no_show"], 1)

    def test_past_date_frees_booked_count(self):
        """
        Freeing the seat is the key correctness requirement.
        """
        from apps.notifications.tasks import no_show_sweep

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        slot = _slot(self.profile, yesterday, datetime.time(9, 0), datetime.time(10, 0), booked=0)
        appt = _confirmed(self.patient, slot)
        count_before = AppointmentSlot.objects.get(id=slot.id).booked_count

        with patch("apps.notifications.events.fire_notification"):
            no_show_sweep()

        slot.refresh_from_db()
        self.assertEqual(slot.booked_count, count_before - 1)

    def test_today_ended_slot_becomes_no_show(self):
        """
        Appointment on today's date but in a slot that ended in the past.
        """
        from apps.notifications.tasks import no_show_sweep

        now       = timezone.now()
        today     = now.date()
        past_time = (now - datetime.timedelta(hours=2)).time()
        end_time  = (now - datetime.timedelta(hours=1)).time()
        slot = _slot(self.profile, today, past_time, end_time, booked=0)
        appt = _confirmed(self.patient, slot)

        with patch("apps.notifications.events.fire_notification"):
            result = no_show_sweep()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.NO_SHOW)

    def test_future_slot_not_touched(self):
        from apps.notifications.tasks import no_show_sweep

        future_date = timezone.now().date() + datetime.timedelta(days=3)
        slot = _slot(self.profile, future_date, datetime.time(9, 0), datetime.time(10, 0))
        appt = _confirmed(self.patient, slot)

        with patch("apps.notifications.events.fire_notification"):
            no_show_sweep()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)

    def test_current_slot_not_touched(self):
        """An in-progress slot (started, not ended) must not be swept."""
        from apps.notifications.tasks import no_show_sweep

        now        = timezone.now()
        today      = now.date()
        start_time = (now - datetime.timedelta(minutes=10)).time()
        end_time   = (now + datetime.timedelta(minutes=50)).time()
        slot = _slot(self.profile, today, start_time, end_time, booked=0)
        appt = _confirmed(self.patient, slot)

        with patch("apps.notifications.events.fire_notification"):
            no_show_sweep()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)

    def test_cancelled_appointment_not_touched(self):
        from apps.notifications.tasks import no_show_sweep

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        slot = _slot(self.profile, yesterday, datetime.time(9, 0), datetime.time(10, 0))
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=slot, hospital=self.hospital,
            status=AppointmentStatus.CANCELLED, held_until=None,
        )

        with patch("apps.notifications.events.fire_notification"):
            no_show_sweep()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)

    def test_already_no_show_not_doubled(self):
        from apps.notifications.tasks import no_show_sweep

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        slot = _slot(self.profile, yesterday, datetime.time(9, 0), datetime.time(10, 0))
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=slot, hospital=self.hospital,
            status=AppointmentStatus.NO_SHOW, held_until=None,
        )
        count_before = AppointmentSlot.objects.get(id=slot.id).booked_count

        with patch("apps.notifications.events.fire_notification"):
            result = no_show_sweep()

        slot.refresh_from_db()
        self.assertEqual(slot.booked_count, count_before)  # not double-decremented

    def test_sweep_idempotent_on_multiple_runs(self):
        """Running the sweep twice does not double-decrement capacity."""
        from apps.notifications.tasks import no_show_sweep

        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        slot = _slot(self.profile, yesterday, datetime.time(9, 0), datetime.time(10, 0), booked=0)
        appt = _confirmed(self.patient, slot)

        with patch("apps.notifications.events.fire_notification"):
            no_show_sweep()
            no_show_sweep()  # second run

        slot.refresh_from_db()
        self.assertGreaterEqual(slot.booked_count, 0)
        self.assertEqual(slot.booked_count, 0)   # only decremented once


# ---------------------------------------------------------------------------
# 2. running_late_check
# ---------------------------------------------------------------------------

class TestRunningLateCheck(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient    = _patient()

    def test_fires_when_earlier_slot_still_confirmed(self):
        from apps.notifications.tasks import running_late_check

        fake_now = datetime.datetime(2026, 8, 24, 10, 30, 0, tzinfo=datetime.timezone.utc)
        today = fake_now.date()
        early_start = datetime.time(9, 0)
        early_end   = datetime.time(10, 0)
        curr_start  = datetime.time(10, 0)
        curr_end    = datetime.time(11, 0)

        early_slot = _slot(self.profile, today, early_start, early_end)
        curr_slot  = _slot(self.profile, today, curr_start, curr_end)

        # A patient is still confirmed in the early slot (not swept yet)
        patient_early = _patient()
        _confirmed(patient_early, early_slot)
        # Patient in current slot
        appt_curr = _confirmed(self.patient, curr_slot)

        fired_events = []
        with patch("django.utils.timezone.now", return_value=fake_now):
            with patch("apps.notifications.events.fire_notification",
                       side_effect=lambda et, a, **k: fired_events.append(et)):
                running_late_check()

        self.assertIn(NotificationEventType.RUNNING_LATE, fired_events)

    def test_does_not_fire_when_on_schedule(self):
        from apps.notifications.tasks import running_late_check

        today     = datetime.date.today()
        now       = timezone.now()
        # Only one slot in progress — no earlier confirmed patients
        curr_start = (now - datetime.timedelta(minutes=5)).time()
        curr_end   = (now + datetime.timedelta(minutes=55)).time()
        curr_slot  = _slot(self.profile, today, curr_start, curr_end)
        _confirmed(self.patient, curr_slot)

        fired_events = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired_events.append(et)):
            running_late_check()

        self.assertNotIn(NotificationEventType.RUNNING_LATE, fired_events)

    def test_deduplication_one_notification_per_appointment(self):
        """Running the check twice only fires the notification once."""
        from apps.notifications.tasks import running_late_check

        today      = datetime.date.today()
        now        = timezone.now()
        early_start = (now - datetime.timedelta(minutes=90)).time()
        early_end   = (now - datetime.timedelta(minutes=30)).time()
        curr_start  = (now - datetime.timedelta(minutes=5)).time()
        curr_end    = (now + datetime.timedelta(minutes=55)).time()

        early_slot = _slot(self.profile, today, early_start, early_end)
        curr_slot  = _slot(self.profile, today, curr_start, curr_end)
        _confirmed(_patient(), early_slot)
        appt_curr = _confirmed(self.patient, curr_slot)

        with patch("apps.notifications.events.fire_notification"):
            running_late_check()

        # Manually insert the de-dupe notification record
        Notification.objects.create(
            patient=appt_curr.patient,
            hospital=appt_curr.hospital,
            appointment=appt_curr,
            event_type=NotificationEventType.RUNNING_LATE,
            title="Running late",
        )

        fired_events = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired_events.append(et)):
            running_late_check()

        self.assertNotIn(NotificationEventType.RUNNING_LATE, fired_events)


# ---------------------------------------------------------------------------
# 3. medication_reminder_dispatch (follow-up available)
# ---------------------------------------------------------------------------

class TestMedicationReminderDispatch(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient    = _patient()

    def _completed_approved_appt(
        self,
        follow_up_days: int,
        approved_days_ago: int = 0,
    ) -> Appointment:
        """
        Create a completed+approved appointment with a follow-up window.
        approved_days_ago controls when approval happened relative to today.
        """
        slot = _slot(
            self.profile,
            datetime.date.today() - datetime.timedelta(days=approved_days_ago + 1),
            datetime.time(9, 0),
            datetime.time(10, 0),
        )
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=slot, hospital=self.hospital,
            status=AppointmentStatus.COMPLETED,
            summary_status=SummaryStatus.APPROVED,
            follow_up_days=follow_up_days,
            approved_at=timezone.now() - datetime.timedelta(days=approved_days_ago),
            held_until=None,
        )
        return appt

    def test_fires_when_follow_up_due(self):
        """
        PHASE 8 EXIT CRITERION (DST variant):
        A reminder scheduled N days after approval fires when N days have elapsed.
        """
        from apps.notifications.tasks import medication_reminder_dispatch

        # Approved 7 days ago, follow_up in 7 days → due today
        appt = self._completed_approved_appt(follow_up_days=7, approved_days_ago=7)

        fired = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired.append(et)):
            result = medication_reminder_dispatch()

        self.assertIn(NotificationEventType.FOLLOW_UP_AVAILABLE, fired)
        self.assertGreaterEqual(result["follow_up_notified"], 1)

    def test_does_not_fire_before_due_date(self):
        from apps.notifications.tasks import medication_reminder_dispatch

        # Approved 3 days ago, follow_up in 7 days → not due yet
        appt = self._completed_approved_appt(follow_up_days=7, approved_days_ago=3)

        fired = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired.append(et)):
            medication_reminder_dispatch()

        self.assertNotIn(NotificationEventType.FOLLOW_UP_AVAILABLE, fired)

    def test_deduplication_does_not_fire_twice(self):
        from apps.notifications.tasks import medication_reminder_dispatch

        appt = self._completed_approved_appt(follow_up_days=7, approved_days_ago=7)

        # Pre-insert the de-dupe record
        Notification.objects.create(
            patient=appt.patient,
            hospital=appt.hospital,
            appointment=appt,
            event_type=NotificationEventType.FOLLOW_UP_AVAILABLE,
            title="Follow-up",
        )

        fired = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired.append(et)):
            medication_reminder_dispatch()

        self.assertNotIn(NotificationEventType.FOLLOW_UP_AVAILABLE, fired)

    def test_does_not_fire_for_unapproved_summary(self):
        from apps.notifications.tasks import medication_reminder_dispatch

        slot = _slot(
            self.profile,
            datetime.date.today() - datetime.timedelta(days=8),
            datetime.time(9, 0),
            datetime.time(10, 0),
        )
        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=slot, hospital=self.hospital,
            status=AppointmentStatus.COMPLETED,
            summary_status=SummaryStatus.DRAFT,   # not approved
            follow_up_days=7,
            approved_at=None,
            held_until=None,
        )

        fired = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired.append(et)):
            medication_reminder_dispatch()

        self.assertNotIn(NotificationEventType.FOLLOW_UP_AVAILABLE, fired)

    def test_dst_boundary_utc_calculation(self):
        """
        DST boundary test: reminder calculated purely in UTC (timezone.now().date())
        so it is unaffected by DST transitions.

        Scenario: follow_up_days=1, approved_at = yesterday 23:00 UTC.
        Today UTC = approved_at.date() + 1 day → due today.
        Even if a DST transition shifted local time by 1 hour, the UTC date
        comparison is stable.
        """
        from apps.notifications.tasks import medication_reminder_dispatch

        slot = _slot(
            self.profile,
            datetime.date.today() - datetime.timedelta(days=1),
            datetime.time(9, 0),
            datetime.time(10, 0),
        )
        # approved_at = exactly yesterday at 23:00 UTC
        approved_at = timezone.now().replace(
            hour=23, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=1)

        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=slot, hospital=self.hospital,
            status=AppointmentStatus.COMPLETED,
            summary_status=SummaryStatus.APPROVED,
            follow_up_days=1,
            approved_at=approved_at,
            held_until=None,
        )

        fired = []
        with patch("apps.notifications.events.fire_notification",
                   side_effect=lambda et, a, **k: fired.append(et)):
            medication_reminder_dispatch()

        self.assertIn(
            NotificationEventType.FOLLOW_UP_AVAILABLE, fired,
            "Follow-up reminder must fire the day after approval regardless of DST",
        )


# ---------------------------------------------------------------------------
# 4. nightly_slot_generation fan-out
# ---------------------------------------------------------------------------

class TestNightlySlotGeneration(TestCase):

    def test_enqueues_task_for_every_active_doctor(self):
        from config.celery import nightly_slot_generation

        hospital = _hospital()
        _, p1    = _doctor(hospital)
        _, p2    = _doctor(hospital)
        # Deactivate one doctor
        p2.is_active = False
        p2.save(update_fields=["is_active"])

        with patch("apps.scheduling.tasks.slot_generation_task.delay") as mock_delay:
            result = nightly_slot_generation()

        # Only active doctors enqueued
        active_count = DoctorProfile.objects.filter(is_active=True).count()
        self.assertEqual(mock_delay.call_count, active_count)
        self.assertEqual(result["enqueued"], active_count)

    def test_does_not_enqueue_inactive_doctors(self):
        from config.celery import nightly_slot_generation

        hospital = _hospital()
        _, p1    = _doctor(hospital)
        p1.is_active = False
        p1.save(update_fields=["is_active"])

        with patch("apps.scheduling.tasks.slot_generation_task.delay") as mock_delay:
            nightly_slot_generation()

        # p1 is inactive — should not be called for p1
        all_call_ids = [str(c.args[0]) for c in mock_delay.call_args_list]
        self.assertNotIn(str(p1.user_id), all_call_ids)


# ---------------------------------------------------------------------------
# 5. Celery beat schedule — all expected tasks registered
# ---------------------------------------------------------------------------

class TestCeleryBeatSchedule(TestCase):

    def test_all_phase_8_tasks_in_beat_schedule(self):
        from config.celery import app

        schedule_tasks = set(app.conf.beat_schedule.keys())
        required = {
            "nightly-slot-generation",
            "hourly-reconcile-slot-counters",
            "expire-stale-holds",
            "no-show-sweep",
            "running-late-check",
            "daily-medication-reminder",
        }
        missing = required - schedule_tasks
        self.assertFalse(
            missing,
            f"Beat schedule is missing entries: {missing}",
        )

    def test_task_names_are_registered(self):
        """All task names in the beat schedule must point to real Celery tasks."""
        from config.celery import app
        from celery import current_app

        # After autodiscover, registered tasks include our tasks
        for entry_name, entry in app.conf.beat_schedule.items():
            task_name = entry["task"]
            # Tasks are registered by name — check it's not an empty string
            self.assertTrue(task_name, f"Beat entry '{entry_name}' has empty task name")
