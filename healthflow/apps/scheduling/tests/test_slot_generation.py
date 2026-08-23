"""
scheduling/tests/test_slot_generation.py

Phase 2 exit-criteria tests (phases.md):
  "Changing a doctor's shift hours or slot duration and re-running generation
   produces correct future slots without touching any slot that already has
   a booking (guard logic testable in isolation)."

Test categories:
  1. Slot window math — correct start/end times, lunch gap skipped
  2. Working-day filter — non-working days produce no slots
  3. Idempotency — re-running does not duplicate slots
  4. Booked-slot guard — slots with booked_count > 0 are never touched
  5. Capacity update — empty slots get updated capacity when config changes
  6. Date range validation — sensible errors on bad inputs
  7. Missing ShiftConfig — ValueError raised with clear message
"""
from __future__ import annotations

import datetime

import pytest
from django.test import TestCase

from apps.accounts.models import Hospital, User, UserRole
from apps.scheduling.models import (
    AppointmentSlot,
    DoctorProfile,
    ShiftConfig,
)
from apps.scheduling.services import GenerationResult, generate_slots_for_doctor


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_hospital(name: str = "Test Hospital") -> Hospital:
    return Hospital.objects.create(
        name=name,
        contact_email=f"{name.lower().replace(' ', '')}@test.local",
    )


def _make_doctor(hospital: Hospital, specialization: str = "General") -> DoctorProfile:
    user = User.objects.create_user(
        email=f"dr.{hospital.id}@test.local",
        password="testpass123",
        name="Dr. Test",
        role=UserRole.DOCTOR,
        hospital=hospital,
    )
    return DoctorProfile.objects.create(
        user=user,
        specialization=specialization,
        slot_duration_minutes=60,
        slot_capacity=5,
    )


def _make_shift(
    doctor: DoctorProfile,
    shift_1_start: str = "09:00",
    shift_1_end: str   = "13:00",
    shift_2_start: str = "14:00",
    shift_2_end: str   = "17:00",
    working_days: list[int] | None = None,
) -> ShiftConfig:
    return ShiftConfig.objects.create(
        doctor=doctor,
        shift_1_start=shift_1_start,
        shift_1_end=shift_1_end,
        shift_2_start=shift_2_start,
        shift_2_end=shift_2_end,
        working_days=working_days if working_days is not None else [1, 2, 3, 4, 5],
    )


# ---------------------------------------------------------------------------
# 1. Slot window math
# ---------------------------------------------------------------------------

class TestSlotWindowMath(TestCase):
    """Verify the correct slot times are generated for a standard shift config."""

    def setUp(self) -> None:
        self.hospital = _make_hospital("Window Hospital")
        self.doctor   = _make_doctor(self.hospital)
        _make_shift(self.doctor)  # 09:00–13:00 / 14:00–17:00, 1hr slots, Mon–Fri

    def test_standard_1hr_slots_morning(self) -> None:
        """09:00–13:00 with 60-min duration produces 4 slots: 09–10, 10–11, 11–12, 12–13."""
        monday = _next_weekday(1)  # next Monday
        result = generate_slots_for_doctor(self.doctor, monday, monday)

        morning_slots = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=monday
        ).order_by("slot_start")

        starts = [s.slot_start.strftime("%H:%M") for s in morning_slots]
        ends   = [s.slot_end.strftime("%H:%M")   for s in morning_slots]

        self.assertIn("09:00", starts)
        self.assertIn("10:00", starts)
        self.assertIn("11:00", starts)
        self.assertIn("12:00", starts)
        self.assertIn("10:00", ends)
        self.assertIn("13:00", ends)

    def test_lunch_gap_not_filled(self) -> None:
        """No slot should span or fill 13:00–14:00."""
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        # No slot starting at 13:00 or spanning into 14:00
        bad_slots = AppointmentSlot.objects.filter(
            doctor=self.doctor,
            date=monday,
            slot_start__gte=datetime.time(13, 0),
            slot_start__lt=datetime.time(14, 0),
        )
        self.assertEqual(bad_slots.count(), 0, "No slot should start in the lunch gap.")

    def test_standard_1hr_slots_afternoon(self) -> None:
        """14:00–17:00 with 60-min duration produces 3 slots: 14–15, 15–16, 16–17."""
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        afternoon_slots = AppointmentSlot.objects.filter(
            doctor=self.doctor,
            date=monday,
            slot_start__gte=datetime.time(14, 0),
        ).order_by("slot_start")

        self.assertEqual(afternoon_slots.count(), 3)
        self.assertEqual(afternoon_slots[0].slot_start, datetime.time(14, 0))
        self.assertEqual(afternoon_slots[2].slot_end,   datetime.time(17, 0))

    def test_total_slots_for_standard_week(self) -> None:
        """Mon–Fri, 7 slots/day (4 morning + 3 afternoon) = 35 slots for a 5-day week."""
        monday = _next_weekday(1)
        friday = monday + datetime.timedelta(days=4)
        result = generate_slots_for_doctor(self.doctor, monday, friday)

        self.assertEqual(result.created, 35)
        self.assertEqual(result.skipped, 0)

    def test_30min_slots_morning(self) -> None:
        """With 30-min duration, 09:00–13:00 produces 8 slots."""
        hospital = _make_hospital("30min Hospital")
        doctor   = _make_doctor(hospital)
        doctor.slot_duration_minutes = 30
        doctor.save(update_fields=["slot_duration_minutes"])
        _make_shift(doctor)

        monday = _next_weekday(1)
        generate_slots_for_doctor(doctor, monday, monday)

        morning_count = AppointmentSlot.objects.filter(
            doctor=doctor,
            date=monday,
            slot_start__lt=datetime.time(13, 0),
        ).count()
        self.assertEqual(morning_count, 8)

    def test_partial_shift_no_overflow(self) -> None:
        """A 90-min slot that doesn't fit in the last window is not created."""
        hospital = _make_hospital("90min Hospital")
        doctor   = _make_doctor(hospital)
        doctor.slot_duration_minutes = 90
        doctor.save(update_fields=["slot_duration_minutes"])
        # shift_1 = 09:00–12:00 (180 min) → 2 slots of 90min
        _make_shift(doctor, shift_1_start="09:00", shift_1_end="12:00",
                    shift_2_start="14:00", shift_2_end="17:00")

        monday = _next_weekday(1)
        generate_slots_for_doctor(doctor, monday, monday)

        morning_slots = AppointmentSlot.objects.filter(
            doctor=doctor,
            date=monday,
            slot_start__lt=datetime.time(13, 0),
        )
        self.assertEqual(morning_slots.count(), 2)
        ends = sorted(s.slot_end for s in morning_slots)
        self.assertEqual(ends[-1], datetime.time(12, 0))


# ---------------------------------------------------------------------------
# 2. Working-day filter
# ---------------------------------------------------------------------------

class TestWorkingDayFilter(TestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Workday Hospital")
        self.doctor   = _make_doctor(self.hospital)

    def test_weekend_skipped_for_mon_fri_config(self) -> None:
        _make_shift(self.doctor, working_days=[1, 2, 3, 4, 5])
        saturday = _next_weekday(6)  # next Saturday
        sunday   = saturday + datetime.timedelta(days=1)
        result   = generate_slots_for_doctor(self.doctor, saturday, sunday)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(
            AppointmentSlot.objects.filter(doctor=self.doctor).count(), 0
        )

    def test_only_configured_days_get_slots(self) -> None:
        """Configure only Wednesday (3) — one slot day in a Mon–Sun range."""
        _make_shift(self.doctor, working_days=[3])
        monday = _next_weekday(1)
        sunday = monday + datetime.timedelta(days=6)
        result = generate_slots_for_doctor(self.doctor, monday, sunday)

        self.assertEqual(result.created, 7)   # 4 morning + 3 afternoon on 1 day
        self.assertEqual(result.skipped, 6)   # other 6 days skipped
        slots = AppointmentSlot.objects.filter(doctor=self.doctor)
        # All slots on Wednesday only
        for slot in slots:
            self.assertEqual(slot.date.isoweekday(), 3)

    def test_all_days_working(self) -> None:
        _make_shift(self.doctor, working_days=[1, 2, 3, 4, 5, 6, 7])
        monday = _next_weekday(1)
        sunday = monday + datetime.timedelta(days=6)
        result = generate_slots_for_doctor(self.doctor, monday, sunday)

        self.assertEqual(result.created, 49)  # 7 slots * 7 days
        self.assertEqual(result.skipped, 0)


# ---------------------------------------------------------------------------
# 3. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency(TestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Idempotent Hospital")
        self.doctor   = _make_doctor(self.hospital)
        _make_shift(self.doctor)

    def test_rerun_same_range_no_duplicates(self) -> None:
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)
        count_after_first = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=monday
        ).count()

        # Second run
        result2 = generate_slots_for_doctor(self.doctor, monday, monday)

        count_after_second = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=monday
        ).count()
        self.assertEqual(count_after_first, count_after_second,
                         "Re-running should not create duplicate slots.")
        self.assertEqual(result2.created, 0,
                         "No new slots should be created on a second run.")

    def test_overlapping_range_no_duplicates(self) -> None:
        monday = _next_weekday(1)
        tuesday = monday + datetime.timedelta(days=1)
        wednesday = monday + datetime.timedelta(days=2)

        generate_slots_for_doctor(self.doctor, monday, tuesday)
        generate_slots_for_doctor(self.doctor, tuesday, wednesday)

        # tuesday slots should only exist once
        tuesday_count = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=tuesday
        ).count()
        self.assertEqual(tuesday_count, 7)


# ---------------------------------------------------------------------------
# 4. Booked-slot guard (the Phase 2 exit criterion)
# ---------------------------------------------------------------------------

class TestBookedSlotGuard(TestCase):
    """
    Core Phase 2 exit criterion:
    A slot with booked_count > 0 must NEVER be touched by re-generation,
    even if the doctor's shift config has changed.
    """

    def setUp(self) -> None:
        self.hospital = _make_hospital("Guard Hospital")
        self.doctor   = _make_doctor(self.hospital)
        _make_shift(self.doctor)

    def test_booked_slot_not_touched_on_rerun(self) -> None:
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        # Simulate a booking on the 09:00 slot
        slot = AppointmentSlot.objects.get(
            doctor=self.doctor, date=monday, slot_start=datetime.time(9, 0)
        )
        original_capacity = slot.capacity
        slot.booked_count = 2
        slot.save(update_fields=["booked_count"])

        # Change capacity on the doctor profile
        self.doctor.slot_capacity = 10
        self.doctor.save(update_fields=["slot_capacity"])

        result = generate_slots_for_doctor(self.doctor, monday, monday)

        # The booked slot must be untouched
        slot.refresh_from_db()
        self.assertEqual(slot.capacity, original_capacity,
                         "Booked slot capacity must not be changed.")
        self.assertEqual(slot.booked_count, 2,
                         "Booked count must not be changed.")
        self.assertGreaterEqual(result.guarded, 1,
                                "Guarded count must be at least 1.")

    def test_multiple_booked_slots_all_guarded(self) -> None:
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        # Book three different slots
        booked_starts = [datetime.time(9, 0), datetime.time(10, 0), datetime.time(14, 0)]
        for start in booked_starts:
            s = AppointmentSlot.objects.get(
                doctor=self.doctor, date=monday, slot_start=start
            )
            s.booked_count = 1
            s.save(update_fields=["booked_count"])

        self.doctor.slot_capacity = 99
        self.doctor.save(update_fields=["slot_capacity"])

        result = generate_slots_for_doctor(self.doctor, monday, monday)

        self.assertEqual(result.guarded, 3)
        for start in booked_starts:
            s = AppointmentSlot.objects.get(
                doctor=self.doctor, date=monday, slot_start=start
            )
            self.assertNotEqual(s.capacity, 99,
                                f"Booked slot at {start} capacity must not be updated.")

    def test_unbooked_slot_capacity_updated(self) -> None:
        """Unbooked slots DO get their capacity updated on re-generation."""
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        # All slots unbooked — change capacity
        self.doctor.slot_capacity = 8
        self.doctor.save(update_fields=["slot_capacity"])

        generate_slots_for_doctor(self.doctor, monday, monday)

        slots = AppointmentSlot.objects.filter(doctor=self.doctor, date=monday)
        for slot in slots:
            self.assertEqual(slot.capacity, 8,
                             f"Unbooked slot at {slot.slot_start} should have updated capacity.")

    def test_guard_only_affects_booked_not_empty_peers(self) -> None:
        """Booked guard applies per-slot, not per-date. Empty peers on the same date update."""
        monday = _next_weekday(1)
        generate_slots_for_doctor(self.doctor, monday, monday)

        # Book exactly one slot
        booked = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=monday
        ).order_by("slot_start").first()
        booked.booked_count = 1
        booked.save(update_fields=["booked_count"])
        original_capacity = booked.capacity

        self.doctor.slot_capacity = 7
        self.doctor.save(update_fields=["slot_capacity"])

        generate_slots_for_doctor(self.doctor, monday, monday)

        booked.refresh_from_db()
        self.assertEqual(booked.capacity, original_capacity, "Booked slot unchanged.")

        unbooked = AppointmentSlot.objects.filter(
            doctor=self.doctor, date=monday
        ).exclude(id=booked.id)
        for s in unbooked:
            self.assertEqual(s.capacity, 7, f"Unbooked slot {s.slot_start} should update.")


# ---------------------------------------------------------------------------
# 5. Date-range and config validation
# ---------------------------------------------------------------------------

class TestValidation(TestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Validation Hospital")
        self.doctor   = _make_doctor(self.hospital)

    def test_missing_shift_config_raises_value_error(self) -> None:
        monday = _next_weekday(1)
        with self.assertRaises(ValueError, msg="Should raise when no ShiftConfig exists."):
            generate_slots_for_doctor(self.doctor, monday, monday)

    def test_inverted_date_range_raises_value_error(self) -> None:
        _make_shift(self.doctor)
        today     = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        with self.assertRaises(ValueError):
            generate_slots_for_doctor(self.doctor, today, yesterday)

    def test_single_day_range_works(self) -> None:
        _make_shift(self.doctor)
        monday = _next_weekday(1)
        result = generate_slots_for_doctor(self.doctor, monday, monday)
        self.assertEqual(result.created, 7)

    def test_empty_working_days_skips_all(self) -> None:
        """A shift config with no working days should skip every date."""
        doctor2 = _make_doctor(_make_hospital("Empty Days Hospital"))
        _make_shift(doctor2, working_days=[])
        monday = _next_weekday(1)
        friday = monday + datetime.timedelta(days=4)
        result = generate_slots_for_doctor(doctor2, monday, friday)
        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 5)


# ---------------------------------------------------------------------------
# 6. API integration tests
# ---------------------------------------------------------------------------

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken


def _jwt_for(user: User) -> str:
    token = JWTRefreshToken.for_user(user)
    token["role"]        = user.role
    token["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    token["user_id"]     = str(user.id)
    return str(token.access_token)


class TestDoctorProfileAPI(APITestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("API Hospital")
        self.admin    = User.objects.create_user(
            email="admin@api.local",
            password="adminpass123",
            name="Admin User",
            role=UserRole.ADMIN,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.doctor_user = User.objects.create_user(
            email="doctor@api.local",
            password="docpass123",
            name="Dr. API",
            role=UserRole.DOCTOR,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialization="Cardiology",
        )
        ShiftConfig.objects.create(
            doctor=self.profile,
            working_days=[1, 2, 3, 4, 5],
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {_jwt_for(self.admin)}"}

    def test_get_doctor_profile(self) -> None:
        url = f"/admin-api/doctors/{self.doctor_user.id}/profile"
        resp = self.client.get(url, **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["specialization"], "Cardiology")
        self.assertIn("shift_config", resp.data)

    def test_patch_doctor_profile_specialization(self) -> None:
        url = f"/admin-api/doctors/{self.doctor_user.id}/profile"
        resp = self.client.patch(url, {"specialization": "Neurology"}, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.specialization, "Neurology")

    def test_put_shift_config(self) -> None:
        url = f"/admin-api/doctors/{self.doctor_user.id}/shift-config"
        payload = {
            "shift_1_start": "08:00",
            "shift_1_end":   "12:00",
            "shift_2_start": "13:00",
            "shift_2_end":   "16:00",
            "working_days":  [1, 2, 3, 4, 5],
            "slot_duration_minutes": 30,
            "slot_capacity": 8,
        }
        resp = self.client.put(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.slot_duration_minutes, 30)
        self.assertEqual(self.profile.slot_capacity, 8)
        shift = self.profile.shift_config
        self.assertEqual(str(shift.shift_1_start), "08:00:00")

    def test_shift_config_validation_inverted_times(self) -> None:
        url = f"/admin-api/doctors/{self.doctor_user.id}/shift-config"
        payload = {
            "shift_1_start": "12:00",
            "shift_1_end":   "09:00",  # bad
            "shift_2_start": "14:00",
            "shift_2_end":   "17:00",
            "working_days":  [1, 2, 3, 4, 5],
            "slot_duration_minutes": 60,
            "slot_capacity": 5,
        }
        resp = self.client.put(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cross_hospital_doctor_not_found(self) -> None:
        """Admin from hospital A cannot access doctor from hospital B."""
        other_hospital = _make_hospital("Other Hospital")
        other_doctor   = User.objects.create_user(
            email="other@api.local",
            password="otherpass",
            name="Other Doc",
            role=UserRole.DOCTOR,
            hospital=other_hospital,
            must_reset_password=False,
        )
        DoctorProfile.objects.create(user=other_doctor, specialization="Other")
        url  = f"/admin-api/doctors/{other_doctor.id}/profile"
        resp = self.client.get(url, **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestLeaveAPI(APITestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Leave Hospital")
        self.admin = User.objects.create_user(
            email="admin@leave.local",
            password="adminpass",
            name="Leave Admin",
            role=UserRole.ADMIN,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.doctor_user = User.objects.create_user(
            email="doctor@leave.local",
            password="docpass",
            name="Leave Doc",
            role=UserRole.DOCTOR,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialization="General",
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {_jwt_for(self.admin)}"}

    def test_create_leave(self) -> None:
        future_date = datetime.date.today() + datetime.timedelta(days=7)
        url  = f"/admin-api/doctors/{self.doctor_user.id}/leave"
        resp = self.client.post(url, {"date": future_date.isoformat(), "reason": "Conference"}, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["date"], future_date.isoformat())

    def test_duplicate_leave_rejected(self) -> None:
        future_date = datetime.date.today() + datetime.timedelta(days=7)
        url  = f"/admin-api/doctors/{self.doctor_user.id}/leave"
        self.client.post(url, {"date": future_date.isoformat()}, format="json", **self.auth)
        resp = self.client.post(url, {"date": future_date.isoformat()}, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_past_date_leave_rejected(self) -> None:
        past_date = datetime.date.today() - datetime.timedelta(days=1)
        url  = f"/admin-api/doctors/{self.doctor_user.id}/leave"
        resp = self.client.post(url, {"date": past_date.isoformat()}, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_leave(self) -> None:
        future_date = datetime.date.today() + datetime.timedelta(days=7)
        from apps.scheduling.models import DoctorLeave
        DoctorLeave.objects.create(doctor=self.profile, date=future_date)
        url  = f"/admin-api/doctors/{self.doctor_user.id}/leave"
        resp = self.client.get(url, **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_delete_leave(self) -> None:
        future_date = datetime.date.today() + datetime.timedelta(days=7)
        from apps.scheduling.models import DoctorLeave
        leave = DoctorLeave.objects.create(doctor=self.profile, date=future_date)
        url  = f"/admin-api/doctors/{self.doctor_user.id}/leave/{leave.id}"
        resp = self.client.delete(url, **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(DoctorLeave.objects.filter(id=leave.id).exists())


class TestAttendanceAPI(APITestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Attendance Hospital")
        self.admin = User.objects.create_user(
            email="admin@att.local",
            password="adminpass",
            name="Att Admin",
            role=UserRole.ADMIN,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.doctor_user = User.objects.create_user(
            email="doctor@att.local",
            password="docpass",
            name="Att Doc",
            role=UserRole.DOCTOR,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialization="General",
        )
        ShiftConfig.objects.create(doctor=self.profile, working_days=[1, 2, 3, 4, 5])
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {_jwt_for(self.admin)}"}

    def test_get_attendance_sheet_default_present(self) -> None:
        """GET attendance sheet — no records in DB means default present."""
        today = datetime.date.today()
        resp  = self.client.get(
            f"/admin-api/attendance?date={today.isoformat()}", **self.auth
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        doctors = resp.data["doctors"]
        self.assertEqual(len(doctors), 1)
        self.assertEqual(doctors[0]["morning_status"],   "present")
        self.assertEqual(doctors[0]["afternoon_status"], "present")

    def test_mark_morning_absent(self) -> None:
        today = datetime.date.today()
        url   = f"/admin-api/attendance/{self.doctor_user.id}"
        payload = {"date": today.isoformat(), "shift": "morning", "status": "absent"}
        resp = self.client.put(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "absent")

        # Sheet now reflects absent morning
        sheet_resp = self.client.get(
            f"/admin-api/attendance?date={today.isoformat()}", **self.auth
        )
        doctors = sheet_resp.data["doctors"]
        self.assertEqual(doctors[0]["morning_status"],   "absent")
        self.assertEqual(doctors[0]["afternoon_status"], "present")

    def test_mark_present_removes_record(self) -> None:
        """Marking a doctor present after absent should delete the attendance row."""
        from apps.scheduling.models import DoctorAttendance
        today = datetime.date.today()
        DoctorAttendance.objects.create(
            doctor=self.profile,
            date=today,
            shift="afternoon",
            status="absent",
            marked_by=self.admin,
        )
        url     = f"/admin-api/attendance/{self.doctor_user.id}"
        payload = {"date": today.isoformat(), "shift": "afternoon", "status": "present"}
        resp    = self.client.put(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(
            DoctorAttendance.objects.filter(doctor=self.profile, date=today, shift="afternoon").exists()
        )

    def test_attendance_cross_hospital_blocked(self) -> None:
        """Admin cannot mark attendance for a doctor from another hospital."""
        other_hospital = _make_hospital("Blocker Hospital")
        other_doc = User.objects.create_user(
            email="other@att.local",
            password="otherpass",
            name="Other Doc",
            role=UserRole.DOCTOR,
            hospital=other_hospital,
            must_reset_password=False,
        )
        DoctorProfile.objects.create(user=other_doc, specialization="Other")
        url     = f"/admin-api/attendance/{other_doc.id}"
        payload = {"date": datetime.date.today().isoformat(), "shift": "morning", "status": "absent"}
        resp    = self.client.put(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestSlotGenerateAPI(APITestCase):
    def setUp(self) -> None:
        self.hospital = _make_hospital("Gen API Hospital")
        self.admin = User.objects.create_user(
            email="admin@gen.local",
            password="adminpass",
            name="Gen Admin",
            role=UserRole.ADMIN,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.doctor_user = User.objects.create_user(
            email="doctor@gen.local",
            password="docpass",
            name="Gen Doc",
            role=UserRole.DOCTOR,
            hospital=self.hospital,
            must_reset_password=False,
        )
        self.profile = DoctorProfile.objects.create(
            user=self.doctor_user,
            specialization="General",
            slot_duration_minutes=60,
            slot_capacity=5,
        )
        ShiftConfig.objects.create(
            doctor=self.profile,
            working_days=[1, 2, 3, 4, 5],
        )
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {_jwt_for(self.admin)}"}

    def test_generate_slots_returns_summary(self) -> None:
        monday = _next_weekday(1)
        url    = f"/admin-api/doctors/{self.doctor_user.id}/slots/generate"
        payload = {
            "date_from": monday.isoformat(),
            "date_to":   monday.isoformat(),
        }
        resp = self.client.post(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["created"], 7)
        self.assertEqual(resp.data["guarded"], 0)

    def test_generate_guards_booked_slots(self) -> None:
        monday = _next_weekday(1)
        # Pre-create a booked slot
        booked = AppointmentSlot.objects.create(
            doctor=self.profile,
            hospital=self.hospital,
            date=monday,
            slot_start=datetime.time(9, 0),
            slot_end=datetime.time(10, 0),
            capacity=5,
            booked_count=3,
        )
        url    = f"/admin-api/doctors/{self.doctor_user.id}/slots/generate"
        payload = {
            "date_from": monday.isoformat(),
            "date_to":   monday.isoformat(),
        }
        resp = self.client.post(url, payload, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["guarded"], 1)
        booked.refresh_from_db()
        self.assertEqual(booked.booked_count, 3, "Booked slot must be untouched.")

    def test_generate_no_shift_config_returns_400(self) -> None:
        hospital2 = _make_hospital("No Shift Hospital")
        admin2 = User.objects.create_user(
            email="admin2@gen.local", password="adminpass",
            name="Admin2", role=UserRole.ADMIN,
            hospital=hospital2, must_reset_password=False,
        )
        doc2 = User.objects.create_user(
            email="doc2@gen.local", password="docpass",
            name="Doc2", role=UserRole.DOCTOR,
            hospital=hospital2, must_reset_password=False,
        )
        DoctorProfile.objects.create(user=doc2, specialization="General")
        auth2  = {"HTTP_AUTHORIZATION": f"Bearer {_jwt_for(admin2)}"}
        monday = _next_weekday(1)
        url    = f"/admin-api/doctors/{doc2.id}/slots/generate"
        resp   = self.client.post(url, {"date_from": monday.isoformat(), "date_to": monday.isoformat()}, format="json", **auth2)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_inverted_date_range_rejected(self) -> None:
        monday = _next_weekday(1)
        url    = f"/admin-api/doctors/{self.doctor_user.id}/slots/generate"
        resp   = self.client.post(url, {"date_from": monday.isoformat(), "date_to": (monday - datetime.timedelta(days=1)).isoformat()}, format="json", **self.auth)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_weekday(weekday: int) -> datetime.date:
    """Return the next date with the given ISO weekday (1=Mon … 7=Sun)."""
    today = datetime.date.today()
    days_ahead = (weekday - today.isoweekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # always in the future to avoid working with today
    return today + datetime.timedelta(days=days_ahead)
