"""
scheduling/tests/test_cascade.py

Phase 7 exit-criteria tests (phases.md):
  "Marking only a doctor's morning absent affects only morning bookings,
   leaves afternoon untouched, and a reassigned patient's doctor card
   correctly shows 'reassigned from Dr. X's morning list' with the
   original symptoms intact."

Categories:
  1.  cascade_cancel_appointments — morning only, afternoon only, full day
  2.  find_reassignment_slot — finds same-spec, excludes absent doctor, prefers time
  3.  cascade_absence_task — reassignment created with original_request,
      DOCTOR_ABSENT when no alternate, RESCHEDULE_OFFER when alternate found
  4.  AttendanceMarkView — enqueues cascade on absent, does NOT cascade on present
  5.  DoctorLeaveListView — enqueues full-day cascade on new leave
  6.  Isolation — cascade only affects the marked doctor, not others
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import Appointment, AppointmentStatus, CancelReason
from apps.scheduling.models import (
    AppointmentSlot, AttendanceStatus,
    DoctorAttendance, DoctorLeave, DoctorProfile, ShiftConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jwt(user: User) -> str:
    t = JWTRefreshToken.for_user(user)
    t["role"]        = user.role
    t["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    t["user_id"]     = str(user.id)
    return str(t.access_token)


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {_jwt(user)}"}


def _hospital() -> Hospital:
    return Hospital.objects.create(
        name=f"H-{uuid.uuid4().hex[:6]}",
        contact_email=f"{uuid.uuid4().hex[:6]}@h.local",
    )


def _doctor(hospital: Hospital, spec: str = "General") -> tuple[User, DoctorProfile]:
    u = User.objects.create_user(
        email=f"dr{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name=f"Dr-{uuid.uuid4().hex[:4]}", role=UserRole.DOCTOR,
        hospital=hospital, must_reset_password=False,
    )
    p = DoctorProfile.objects.create(
        user=u, specialization=spec,
        slot_duration_minutes=60, slot_capacity=5,
    )
    ShiftConfig.objects.create(
        doctor=p,
        shift_1_start=datetime.time(9,  0),
        shift_1_end=  datetime.time(13, 0),
        shift_2_start=datetime.time(14, 0),
        shift_2_end=  datetime.time(17, 0),
        working_days=[1, 2, 3, 4, 5],
    )
    return u, p


def _admin(hospital: Hospital) -> User:
    return User.objects.create_user(
        email=f"admin{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Admin", role=UserRole.ADMIN,
        hospital=hospital, must_reset_password=False,
    )


def _patient() -> User:
    return User.objects.create_user(
        email=f"p{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Patient", role=UserRole.PATIENT,
        hospital=None, must_reset_password=False,
    )


TARGET_DATE = datetime.date.today() + datetime.timedelta(days=3)


def _slot(profile: DoctorProfile, start: datetime.time,
          end: datetime.time, capacity: int = 5, booked: int = 0) -> AppointmentSlot:
    return AppointmentSlot.objects.create(
        doctor=profile, hospital=profile.user.hospital,
        date=TARGET_DATE,
        slot_start=start, slot_end=end,
        capacity=capacity, booked_count=booked,
    )


def _confirmed(patient: User, slot: AppointmentSlot) -> Appointment:
    slot.booked_count += 1
    slot.save(update_fields=["booked_count"])
    return Appointment.objects.create(
        patient=patient, doctor=slot.doctor.user,
        slot=slot, hospital=slot.hospital,
        status=AppointmentStatus.CONFIRMED, token=1,
        symptom_text="Cough and fever for two days.", held_until=None,
    )


def _held(patient: User, slot: AppointmentSlot) -> Appointment:
    return Appointment.objects.create(
        patient=patient, doctor=slot.doctor.user,
        slot=slot, hospital=slot.hospital,
        status=AppointmentStatus.HELD,
        held_until=timezone.now() + datetime.timedelta(minutes=10),
    )


# ---------------------------------------------------------------------------
# 1. cascade_cancel_appointments
# ---------------------------------------------------------------------------

class TestCascadeCancel(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()

        # Morning slots: 09:00–10:00, 10:00–11:00
        self.slot_am1 = _slot(self.profile, datetime.time(9,  0), datetime.time(10, 0))
        self.slot_am2 = _slot(self.profile, datetime.time(10, 0), datetime.time(11, 0))
        # Afternoon slots: 14:00–15:00, 15:00–16:00
        self.slot_pm1 = _slot(self.profile, datetime.time(14, 0), datetime.time(15, 0))
        self.slot_pm2 = _slot(self.profile, datetime.time(15, 0), datetime.time(16, 0))

        self.appt_am1 = _confirmed(_patient(), self.slot_am1)
        self.appt_am2 = _confirmed(_patient(), self.slot_am2)
        self.appt_pm1 = _confirmed(_patient(), self.slot_pm1)
        self.appt_pm2 = _confirmed(_patient(), self.slot_pm2)

    def test_morning_cascade_only_affects_morning(self):
        """
        PHASE 7 EXIT CRITERION:
        Marking morning absent cancels only morning bookings.
        Afternoon appointments are untouched.
        """
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cancelled = cascade_cancel_appointments(self.profile, TARGET_DATE, shift="morning")

        cancelled_ids = {a.id for a in cancelled}
        self.assertIn(self.appt_am1.id, cancelled_ids)
        self.assertIn(self.appt_am2.id, cancelled_ids)
        self.assertNotIn(self.appt_pm1.id, cancelled_ids)
        self.assertNotIn(self.appt_pm2.id, cancelled_ids)

        # DB check
        self.appt_am1.refresh_from_db()
        self.appt_pm1.refresh_from_db()
        self.assertEqual(self.appt_am1.status, AppointmentStatus.CANCELLED)
        self.assertEqual(self.appt_pm1.status, AppointmentStatus.CONFIRMED)   # untouched

    def test_afternoon_cascade_only_affects_afternoon(self):
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cancelled = cascade_cancel_appointments(self.profile, TARGET_DATE, shift="afternoon")

        cancelled_ids = {a.id for a in cancelled}
        self.assertNotIn(self.appt_am1.id, cancelled_ids)
        self.assertNotIn(self.appt_am2.id, cancelled_ids)
        self.assertIn(self.appt_pm1.id, cancelled_ids)
        self.assertIn(self.appt_pm2.id, cancelled_ids)

        self.appt_am1.refresh_from_db()
        self.assertEqual(self.appt_am1.status, AppointmentStatus.CONFIRMED)  # untouched

    def test_full_day_cascade_cancels_all(self):
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cancelled = cascade_cancel_appointments(self.profile, TARGET_DATE, shift=None)

        self.assertEqual(len(cancelled), 4)

    def test_cancel_reason_set_to_affected_by_absent(self):
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cascade_cancel_appointments(
                self.profile, TARGET_DATE, shift="morning", reason="affected_by_absent"
            )
        self.appt_am1.refresh_from_db()
        self.assertEqual(self.appt_am1.cancel_reason, CancelReason.AFFECTED_BY_ABSENT)

    def test_cancel_reason_set_to_affected_by_leave(self):
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cascade_cancel_appointments(
                self.profile, TARGET_DATE, shift=None, reason="affected_by_leave"
            )
        self.appt_am1.refresh_from_db()
        self.assertEqual(self.appt_am1.cancel_reason, CancelReason.AFFECTED_BY_LEAVE)

    def test_booked_count_freed_after_cascade(self):
        from apps.scheduling.services import cascade_cancel_appointments
        count_before = self.slot_am1.booked_count
        with patch("apps.notifications.events.fire_notification"):
            cascade_cancel_appointments(self.profile, TARGET_DATE, shift="morning")
        self.slot_am1.refresh_from_db()
        self.assertEqual(self.slot_am1.booked_count, count_before - 1)

    def test_held_appointments_also_cancelled(self):
        from apps.scheduling.services import cascade_cancel_appointments
        held_appt = _held(_patient(), self.slot_am1)
        with patch("apps.notifications.events.fire_notification"):
            cancelled = cascade_cancel_appointments(self.profile, TARGET_DATE, shift="morning")
        held_appt.refresh_from_db()
        self.assertEqual(held_appt.status, AppointmentStatus.CANCELLED)

    def test_no_appointments_cascade_returns_empty(self):
        from apps.scheduling.services import cascade_cancel_appointments
        # Different doctor — no appointments for them
        _, profile2 = _doctor(self.hospital)
        result = cascade_cancel_appointments(profile2, TARGET_DATE, shift="morning")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# 2. find_reassignment_slot
# ---------------------------------------------------------------------------

class TestFindReassignmentSlot(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.absent_profile   = _doctor(self.hospital, "Cardiology")
        _, self.alt_profile      = _doctor(self.hospital, "Cardiology")  # same spec
        _, self.diff_spec_profile = _doctor(self.hospital, "Neurology")  # different spec

        # Alt doctor has an open morning slot
        self.alt_slot = _slot(
            self.alt_profile,
            datetime.time(9, 0), datetime.time(10, 0),
            capacity=5, booked=0,
        )
        # Different-spec doctor also has a slot — should NOT be returned
        _slot(self.diff_spec_profile, datetime.time(9, 0), datetime.time(10, 0))

    def test_finds_same_spec_alternate(self):
        from apps.scheduling.services import find_reassignment_slot
        slot = find_reassignment_slot(self.absent_profile, TARGET_DATE)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.doctor, self.alt_profile)

    def test_excludes_absent_doctor(self):
        from apps.scheduling.services import find_reassignment_slot
        slot = find_reassignment_slot(self.absent_profile, TARGET_DATE)
        self.assertNotEqual(slot.doctor, self.absent_profile)

    def test_returns_none_when_no_same_spec_available(self):
        from apps.scheduling.services import find_reassignment_slot
        _, solo_profile = _doctor(self.hospital, "Rare Specialty")
        result = find_reassignment_slot(solo_profile, TARGET_DATE)
        self.assertIsNone(result)

    def test_returns_none_when_alternate_slot_full(self):
        from apps.scheduling.services import find_reassignment_slot
        self.alt_slot.booked_count = self.alt_slot.capacity
        self.alt_slot.save(update_fields=["booked_count"])
        result = find_reassignment_slot(self.absent_profile, TARGET_DATE)
        self.assertIsNone(result)

    def test_prefers_same_or_later_start_time(self):
        from apps.scheduling.services import find_reassignment_slot
        # Add another slot at 10:00
        later_slot = _slot(
            self.alt_profile,
            datetime.time(10, 0), datetime.time(11, 0),
            capacity=5, booked=0,
        )
        result = find_reassignment_slot(
            self.absent_profile, TARGET_DATE,
            preferred_slot_start=datetime.time(10, 0),
        )
        self.assertEqual(result.id, later_slot.id)


# ---------------------------------------------------------------------------
# 3. cascade_absence_task
# ---------------------------------------------------------------------------

class TestCascadeAbsenceTask(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital, "General")
        _, self.alt_profile = _doctor(self.hospital, "General")  # same spec

        self.patient = _patient()
        self.slot_am = _slot(self.profile, datetime.time(9, 0), datetime.time(10, 0))
        self.appt    = _confirmed(self.patient, self.slot_am)

    def test_reassignment_creates_new_held_with_original_request(self):
        """
        PHASE 7 EXIT CRITERION:
        Reassigned patient's appointment has original_request pointing back
        with symptoms intact.
        """
        from apps.scheduling.tasks import cascade_absence_task
        alt_slot = _slot(
            self.alt_profile,
            datetime.time(9, 0), datetime.time(10, 0),
            capacity=5, booked=0,
        )

        with patch("apps.notifications.events.fire_notification"):
            with patch("apps.scheduling.services.try_hold_slot", return_value=True):
                result = cascade_absence_task(
                    str(self.profile.user_id),
                    TARGET_DATE.isoformat(),
                    "morning",
                    "affected_by_absent",
                )

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["reassigned"], 1)

        new_appt = Appointment.objects.filter(original_request=self.appt).first()
        self.assertIsNotNone(new_appt, "New appointment must reference original via original_request")
        self.assertEqual(new_appt.status, AppointmentStatus.HELD)
        self.assertEqual(new_appt.symptom_text, self.appt.symptom_text)

    def test_reassignment_note_contains_original_doctor_name(self):
        from apps.scheduling.tasks import cascade_absence_task
        _slot(self.alt_profile, datetime.time(9, 0), datetime.time(10, 0), capacity=5)

        with patch("apps.notifications.events.fire_notification"):
            with patch("apps.scheduling.services.try_hold_slot", return_value=True):
                cascade_absence_task(
                    str(self.profile.user_id),
                    TARGET_DATE.isoformat(),
                    "morning",
                )

        new_appt = Appointment.objects.filter(original_request=self.appt).first()
        self.assertIsNotNone(new_appt)
        self.assertIn(self.profile.user.name, new_appt.reassignment_note)

    def test_doctor_absent_notification_fired_when_no_alternate(self):
        """When no alternate doctor is available, DOCTOR_ABSENT notification is fired."""
        from apps.scheduling.tasks import cascade_absence_task

        fired_events = []
        def capture(event_type, appt, **kw):
            fired_events.append(event_type)

        with patch("apps.notifications.events.fire_notification", side_effect=capture):
            cascade_absence_task(
                str(self.profile.user_id),
                TARGET_DATE.isoformat(),
                "morning",
            )

        from apps.notifications.models import NotificationEventType
        self.assertIn(NotificationEventType.DOCTOR_ABSENT, fired_events)

    def test_reschedule_offer_notification_fired_when_alternate_found(self):
        from apps.scheduling.tasks import cascade_absence_task
        _slot(self.alt_profile, datetime.time(9, 0), datetime.time(10, 0), capacity=5)

        fired_events = []
        def capture(event_type, appt, **kw):
            fired_events.append(event_type)

        with patch("apps.notifications.events.fire_notification", side_effect=capture):
            with patch("apps.scheduling.services.try_hold_slot", return_value=True):
                cascade_absence_task(
                    str(self.profile.user_id),
                    TARGET_DATE.isoformat(),
                    "morning",
                )

        from apps.notifications.models import NotificationEventType
        self.assertIn(NotificationEventType.RESCHEDULE_OFFER, fired_events)

    def test_afternoon_appointments_untouched_when_morning_cascaded(self):
        """
        PHASE 7 EXIT CRITERION (exact):
        After morning cascade, afternoon appointments remain CONFIRMED.
        """
        from apps.scheduling.tasks import cascade_absence_task
        slot_pm = _slot(self.profile, datetime.time(14, 0), datetime.time(15, 0))
        appt_pm = _confirmed(_patient(), slot_pm)

        with patch("apps.notifications.events.fire_notification"):
            with patch("apps.scheduling.services.try_hold_slot", return_value=True):
                cascade_absence_task(
                    str(self.profile.user_id),
                    TARGET_DATE.isoformat(),
                    "morning",
                )

        appt_pm.refresh_from_db()
        self.assertEqual(appt_pm.status, AppointmentStatus.CONFIRMED)
        # Morning was cancelled
        self.appt.refresh_from_db()
        self.assertEqual(self.appt.status, AppointmentStatus.CANCELLED)


# ---------------------------------------------------------------------------
# 4. AttendanceMarkView — cascade trigger
# ---------------------------------------------------------------------------

class TestAttendanceMarkViewCascade(APITestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.admin = _admin(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile, datetime.time(9, 0), datetime.time(10, 0))
        self.appt = _confirmed(self.patient, self.slot)

    def test_absent_enqueues_cascade_task(self):
        with patch("apps.scheduling.tasks.cascade_absence_task.delay") as mock_delay:
            resp = self.client.put(
                f"/admin-api/attendance/{self.profile.user_id}",
                {"date": TARGET_DATE.isoformat(), "shift": "morning", "status": "absent"},
                format="json", **_auth(self.admin),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_delay.assert_called_once_with(
            str(self.profile.user_id),
            TARGET_DATE.isoformat(),
            "morning",
            "affected_by_absent",
        )

    def test_present_does_not_enqueue_cascade(self):
        # First mark absent
        DoctorAttendance.objects.create(
            doctor=self.profile, date=TARGET_DATE, shift="morning",
            status="absent", marked_by=self.admin,
        )
        with patch("apps.scheduling.tasks.cascade_absence_task.delay") as mock_delay:
            resp = self.client.put(
                f"/admin-api/attendance/{self.profile.user_id}",
                {"date": TARGET_DATE.isoformat(), "shift": "morning", "status": "present"},
                format="json", **_auth(self.admin),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# 5. DoctorLeaveListView — cascade trigger
# ---------------------------------------------------------------------------

class TestDoctorLeaveListViewCascade(APITestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.admin = _admin(self.hospital)

    def test_adding_leave_enqueues_full_day_cascade(self):
        future_date = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()
        with patch("apps.scheduling.tasks.cascade_absence_task.delay") as mock_delay:
            resp = self.client.post(
                f"/admin-api/doctors/{self.profile.user_id}/leave",
                {"date": future_date, "reason": "Conference"},
                format="json", **_auth(self.admin),
            )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        mock_delay.assert_called_once_with(
            str(self.profile.user_id),
            future_date,
            None,
            "affected_by_leave",
        )


# ---------------------------------------------------------------------------
# 6. Isolation — cascade does not bleed across doctors
# ---------------------------------------------------------------------------

class TestCascadeIsolation(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile_a = _doctor(self.hospital, "General")
        _, self.profile_b = _doctor(self.hospital, "General")
        p_a = _patient()
        p_b = _patient()
        slot_a = _slot(self.profile_a, datetime.time(9, 0), datetime.time(10, 0))
        slot_b = _slot(self.profile_b, datetime.time(9, 0), datetime.time(10, 0))
        self.appt_a = _confirmed(p_a, slot_a)
        self.appt_b = _confirmed(p_b, slot_b)

    def test_cascade_on_doctor_a_does_not_affect_doctor_b(self):
        from apps.scheduling.services import cascade_cancel_appointments
        with patch("apps.notifications.events.fire_notification"):
            cancelled = cascade_cancel_appointments(
                self.profile_a, TARGET_DATE, shift="morning"
            )

        cancelled_ids = {a.id for a in cancelled}
        self.assertIn(self.appt_a.id, cancelled_ids)
        self.assertNotIn(self.appt_b.id, cancelled_ids)

        self.appt_b.refresh_from_db()
        self.assertEqual(self.appt_b.status, AppointmentStatus.CONFIRMED)
