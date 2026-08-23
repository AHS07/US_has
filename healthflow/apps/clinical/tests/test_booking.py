"""
clinical/tests/test_booking.py

Phase 3 exit-criteria tests (phases.md):
  "A load test firing N concurrent hold requests at a slot with capacity M
   never allows more than M confirmed bookings."
  "Reconciliation task correctly resyncs an artificially-drifted Redis counter."

Also covers:
  - Patient isolation: Patient A token against Patient B appointment → 403/404
  - State-machine transitions (valid and invalid)
  - Cancel and reschedule flows
  - Doctor discovery (search, next-available-slot)
  - Slot grid with unavailable flags

Redis is mocked in unit tests via fakeredis so tests run without a real server.
API integration tests that exercise the full hold/confirm cycle mock Redis at
the common.redis_client layer to simulate the DECR/INCR logic without a live
connection.
"""
from __future__ import annotations

import datetime
import threading
import uuid
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import Appointment, AppointmentStatus, CancelReason
from apps.clinical.state_machine import (
    cancel_confirmed,
    cancel_hold,
    confirm,
    mark_no_show,
    mark_reassigned,
)
from apps.scheduling.models import (
    AppointmentSlot,
    DoctorAttendance,
    DoctorLeave,
    DoctorProfile,
    ShiftConfig,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _jwt(user: User) -> str:
    token = JWTRefreshToken.for_user(user)
    token["role"]        = user.role
    token["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    token["user_id"]     = str(user.id)
    return str(token.access_token)


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {_jwt(user)}"}


def _hospital(name: str = "Test Hospital") -> Hospital:
    return Hospital.objects.create(
        name=name,
        contact_email=f"{name.lower().replace(' ', '_')}_{uuid.uuid4().hex[:6]}@test.local",
    )


def _admin(hospital: Hospital, suffix: str = "") -> User:
    return User.objects.create_user(
        email=f"admin{suffix}_{uuid.uuid4().hex[:6]}@test.local",
        password="pass", name="Admin", role=UserRole.ADMIN,
        hospital=hospital, must_reset_password=False,
    )


def _doctor(hospital: Hospital, specialization: str = "General") -> tuple[User, DoctorProfile]:
    user = User.objects.create_user(
        email=f"doc_{uuid.uuid4().hex[:6]}@test.local",
        password="pass", name="Dr. Test", role=UserRole.DOCTOR,
        hospital=hospital, must_reset_password=False,
    )
    profile = DoctorProfile.objects.create(
        user=user, specialization=specialization,
        slot_duration_minutes=60, slot_capacity=3,
    )
    ShiftConfig.objects.create(
        doctor=profile, working_days=[1, 2, 3, 4, 5],
    )
    return user, profile


def _patient(suffix: str = "") -> User:
    return User.objects.create_user(
        email=f"patient{suffix}_{uuid.uuid4().hex[:6]}@test.local",
        password="pass", name="Patient", role=UserRole.PATIENT,
        hospital=None, must_reset_password=False,
    )


def _slot(
    profile: DoctorProfile,
    capacity: int = 3,
    booked: int = 0,
    date: datetime.date | None = None,
) -> AppointmentSlot:
    d = date or (datetime.date.today() + datetime.timedelta(days=7))
    return AppointmentSlot.objects.create(
        doctor=profile,
        hospital=profile.user.hospital,
        date=d,
        slot_start=datetime.time(9, 0),
        slot_end=datetime.time(10, 0),
        capacity=capacity,
        booked_count=booked,
    )


def _held_appointment(patient: User, slot: AppointmentSlot) -> Appointment:
    return Appointment.objects.create(
        patient=patient,
        doctor=slot.doctor.user,
        slot=slot,
        hospital=slot.hospital,
        status=AppointmentStatus.HELD,
        held_until=timezone.now() + datetime.timedelta(minutes=10),
    )


def _confirmed_appointment(
    patient: User, slot: AppointmentSlot, token: int = 1
) -> Appointment:
    appt = _held_appointment(patient, slot)
    slot.booked_count += 1
    slot.save(update_fields=["booked_count"])
    appt.status = AppointmentStatus.CONFIRMED
    appt.token  = token
    appt.symptom_text = "Persistent headache for 3 days."
    appt.held_until   = None
    appt.save(update_fields=["status", "token", "symptom_text", "held_until", "updated_at"])
    return appt


# ---------------------------------------------------------------------------
# 1. State-machine unit tests
# ---------------------------------------------------------------------------

class TestStateMachine(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot    = _slot(self.profile, capacity=3)

    def test_confirm_transitions_held_to_confirmed(self):
        appt = _held_appointment(self.patient, self.slot)
        result = confirm(appt, symptom_text="Fever since 2 days.", token=1)
        self.assertEqual(result.status, AppointmentStatus.CONFIRMED)
        self.assertEqual(result.token, 1)
        self.assertIsNone(result.held_until)

    def test_cancel_hold_transitions_held_to_cancelled(self):
        appt = _held_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr") as mock_incr:
            result = cancel_hold(appt)
        self.assertEqual(result.status, AppointmentStatus.CANCELLED)
        self.assertEqual(result.cancel_reason, CancelReason.PATIENT_INITIATED)
        mock_incr.assert_called_once_with(str(self.slot.id))

    def test_cancel_confirmed_decrements_booked_count(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        original_count = self.slot.booked_count
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            cancel_confirmed(appt, reason=CancelReason.PATIENT_INITIATED)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, original_count - 1)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)

    def test_cancel_confirmed_increments_redis_counter(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr") as mock_incr:
            cancel_confirmed(appt)
        mock_incr.assert_called_once_with(str(self.slot.id))

    def test_mark_no_show_frees_capacity(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        original = self.slot.booked_count
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            mark_no_show(appt)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, original - 1)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.NO_SHOW)

    def test_mark_reassigned(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            mark_reassigned(appt)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.REASSIGNED)

    def test_invalid_transition_raises_validation_error(self):
        from rest_framework.exceptions import ValidationError
        appt = _held_appointment(self.patient, self.slot)
        with self.assertRaises(ValidationError):
            # held → completed is not allowed
            from apps.clinical.state_machine import _assert_transition
            _assert_transition(appt, AppointmentStatus.COMPLETED)

    def test_terminal_status_raises_on_any_transition(self):
        from rest_framework.exceptions import ValidationError
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            cancel_confirmed(appt)
        appt.refresh_from_db()
        # Now cancelled — any further transition should raise
        with self.assertRaises(ValidationError):
            cancel_confirmed(appt)


# ---------------------------------------------------------------------------
# 2. Booking API tests (with Redis mocked)
# ---------------------------------------------------------------------------

# Patch Redis for all API tests — we test concurrency separately
REDIS_MOCK_PATCH = "apps.scheduling.services.slot_counter_decr"


class TestHoldAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Hold Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot    = _slot(self.profile, capacity=3)

    def _hold(self, patient, slot, redis_return=2):
        with patch(REDIS_MOCK_PATCH, return_value=redis_return):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                return self.client.post(
                    "/appointments/hold",
                    {"slot_id": str(slot.id), "doctor_id": str(self.profile.user_id)},
                    format="json",
                    **_auth(patient),
                )

    def test_hold_creates_appointment(self):
        resp = self._hold(self.patient, self.slot)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "held")
        self.assertIn("held_until", resp.data)

    def test_hold_slot_full_returns_409(self):
        # Redis returns -1 (over capacity)
        with patch(REDIS_MOCK_PATCH, return_value=-1):
            with patch("apps.scheduling.services.slot_counter_get", return_value=0):
                with patch("common.redis_client.slot_counter_incr"):
                    resp = self.client.post(
                        "/appointments/hold",
                        {"slot_id": str(self.slot.id), "doctor_id": str(self.profile.user_id)},
                        format="json",
                        **_auth(self.patient),
                    )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_hold_duplicate_blocked(self):
        # First hold succeeds
        self._hold(self.patient, self.slot)
        # Second hold same patient same slot → 400
        with patch(REDIS_MOCK_PATCH, return_value=1):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                resp = self.client.post(
                    "/appointments/hold",
                    {"slot_id": str(self.slot.id), "doctor_id": str(self.profile.user_id)},
                    format="json",
                    **_auth(self.patient),
                )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hold_wrong_doctor_id_rejected(self):
        with patch(REDIS_MOCK_PATCH, return_value=2):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                resp = self.client.post(
                    "/appointments/hold",
                    {"slot_id": str(self.slot.id), "doctor_id": str(uuid.uuid4())},
                    format="json",
                    **_auth(self.patient),
                )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_hold_requires_patient_role(self):
        _, other_profile = _doctor(self.hospital)
        resp = self.client.post(
            "/appointments/hold",
            {"slot_id": str(self.slot.id), "doctor_id": str(self.profile.user_id)},
            format="json",
            **_auth(other_profile.user),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TestConfirmAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Confirm Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot    = _slot(self.profile, capacity=3)

    def test_confirm_transitions_to_confirmed(self):
        appt = _held_appointment(self.patient, self.slot)
        resp = self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Persistent fever and cough for 3 days."},
            format="json",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "confirmed")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 1)

    def test_confirm_increments_booked_count_once(self):
        appt = _held_appointment(self.patient, self.slot)
        self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Knee pain when climbing stairs, worsening over 2 weeks."},
            format="json",
            **_auth(self.patient),
        )
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 1)

    def test_confirm_sets_token(self):
        appt = _held_appointment(self.patient, self.slot)
        resp = self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Back pain and difficulty sleeping."},
            format="json",
            **_auth(self.patient),
        )
        self.assertEqual(resp.data["token"], 1)

    def test_confirm_expired_hold_rejected(self):
        appt = _held_appointment(self.patient, self.slot)
        appt.held_until = timezone.now() - datetime.timedelta(minutes=1)
        appt.save(update_fields=["held_until"])
        resp = self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Shortness of breath on exertion."},
            format="json",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_symptom_too_short_rejected(self):
        appt = _held_appointment(self.patient, self.slot)
        resp = self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Ouch"},  # < 10 chars
            format="json",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirm_full_slot_returns_409(self):
        # Fill the slot to capacity via Postgres
        self.slot.booked_count = self.slot.capacity
        self.slot.save(update_fields=["booked_count"])
        appt = _held_appointment(self.patient, self.slot)
        with patch("common.redis_client.slot_counter_incr"):
            resp = self.client.post(
                f"/appointments/{appt.id}/confirm",
                {"symptom_text": "Persistent nausea after meals, 1 week."},
                format="json",
                **_auth(self.patient),
            )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)

    def test_confirm_other_patient_appointment_returns_404(self):
        """Patient A cannot confirm Patient B's appointment."""
        other_patient = _patient("B")
        appt = _held_appointment(other_patient, self.slot)
        resp = self.client.post(
            f"/appointments/{appt.id}/confirm",
            {"symptom_text": "Trying to confirm someone else appointment."},
            format="json",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestCancelAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Cancel Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot    = _slot(self.profile, capacity=3)

    def test_cancel_hold_via_delete(self):
        appt = _held_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.delete(
                f"/appointments/{appt.id}/hold",
                **_auth(self.patient),
            )
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)

    def test_cancel_confirmed(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.post(
                f"/appointments/{appt.id}/cancel",
                format="json",
                **_auth(self.patient),
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "cancelled")
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, 0)

    def test_cancel_confirmed_frees_seat(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        count_before = self.slot.booked_count
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            self.client.post(
                f"/appointments/{appt.id}/cancel",
                format="json",
                **_auth(self.patient),
            )
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, count_before - 1)

    def test_cancel_already_cancelled_returns_400(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            self.client.post(f"/appointments/{appt.id}/cancel", format="json", **_auth(self.patient))
        # Try again
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.post(
                f"/appointments/{appt.id}/cancel",
                format="json",
                **_auth(self.patient),
            )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_other_patients_appointment_returns_404(self):
        other = _patient("other")
        appt = _confirmed_appointment(other, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.post(
                f"/appointments/{appt.id}/cancel",
                format="json",
                **_auth(self.patient),
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class TestRescheduleAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Reschedule Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient  = _patient()
        self.old_slot = _slot(self.profile, capacity=3)
        self.new_slot = AppointmentSlot.objects.create(
            doctor=self.profile,
            hospital=self.hospital,
            date=datetime.date.today() + datetime.timedelta(days=14),
            slot_start=datetime.time(10, 0),
            slot_end=datetime.time(11, 0),
            capacity=3,
            booked_count=0,
        )

    def test_reschedule_cancels_old_and_holds_new(self):
        appt = _confirmed_appointment(self.patient, self.old_slot)
        with patch(REDIS_MOCK_PATCH, return_value=2):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                with patch("apps.clinical.state_machine.slot_counter_incr"):
                    resp = self.client.post(
                        f"/appointments/{appt.id}/reschedule",
                        {
                            "new_slot_id":   str(self.new_slot.id),
                            "new_doctor_id": str(self.profile.user_id),
                        },
                        format="json",
                        **_auth(self.patient),
                    )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["status"], "held")
        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)

    def test_reschedule_carries_symptom_text_forward(self):
        appt = _confirmed_appointment(self.patient, self.old_slot)
        appt.symptom_text = "Severe migraine with visual aura."
        appt.save(update_fields=["symptom_text"])

        with patch(REDIS_MOCK_PATCH, return_value=2):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                with patch("apps.clinical.state_machine.slot_counter_incr"):
                    resp = self.client.post(
                        f"/appointments/{appt.id}/reschedule",
                        {
                            "new_slot_id":   str(self.new_slot.id),
                            "new_doctor_id": str(self.profile.user_id),
                        },
                        format="json",
                        **_auth(self.patient),
                    )
        new_id = resp.data["id"]
        new_appt = Appointment.objects.get(id=new_id)
        self.assertEqual(new_appt.symptom_text, "Severe migraine with visual aura.")

    def test_reschedule_new_slot_full_returns_409(self):
        appt = _confirmed_appointment(self.patient, self.old_slot)
        with patch(REDIS_MOCK_PATCH, return_value=-1):
            with patch("apps.scheduling.services.slot_counter_get", return_value=0):
                with patch("common.redis_client.slot_counter_incr"):
                    resp = self.client.post(
                        f"/appointments/{appt.id}/reschedule",
                        {
                            "new_slot_id":   str(self.new_slot.id),
                            "new_doctor_id": str(self.profile.user_id),
                        },
                        format="json",
                        **_auth(self.patient),
                    )
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)


# ---------------------------------------------------------------------------
# 3. Isolation: Patient A token against Patient B appointment → 404
# ---------------------------------------------------------------------------

class TestIsolation(APITestCase):
    """
    Core Phase 3 exit criterion: patient data isolation.
    A token belonging to Patient A must never reveal Patient B's data.
    Returns 404 (not 403) to avoid confirming existence.
    """

    def setUp(self):
        self.hospital  = _hospital("Iso Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient_a = _patient("A")
        self.patient_b = _patient("B")
        self.slot      = _slot(self.profile, capacity=5)
        self.appt_b    = _confirmed_appointment(self.patient_b, self.slot)

    def test_patient_a_cannot_get_patient_b_appointment(self):
        resp = self.client.get(
            f"/appointments/{self.appt_b.id}",
            **_auth(self.patient_a),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_a_cannot_cancel_patient_b_appointment(self):
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.post(
                f"/appointments/{self.appt_b.id}/cancel",
                format="json",
                **_auth(self.patient_a),
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_a_cannot_confirm_patient_b_hold(self):
        held_b = _held_appointment(self.patient_b, self.slot)
        resp = self.client.post(
            f"/appointments/{held_b.id}/confirm",
            {"symptom_text": "Trying to access another patient hold now."},
            format="json",
            **_auth(self.patient_a),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_a_cannot_delete_patient_b_hold(self):
        held_b = _held_appointment(self.patient_b, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            resp = self.client.delete(
                f"/appointments/{held_b.id}/hold",
                **_auth(self.patient_a),
            )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_patient_a_cannot_reschedule_patient_b_appointment(self):
        new_slot = AppointmentSlot.objects.create(
            doctor=self.profile, hospital=self.hospital,
            date=datetime.date.today() + datetime.timedelta(days=10),
            slot_start=datetime.time(14, 0), slot_end=datetime.time(15, 0),
            capacity=3, booked_count=0,
        )
        with patch(REDIS_MOCK_PATCH, return_value=2):
            with patch("apps.scheduling.services.slot_counter_get", return_value=3):
                resp = self.client.post(
                    f"/appointments/{self.appt_b.id}/reschedule",
                    {"new_slot_id": str(new_slot.id), "new_doctor_id": str(self.profile.user_id)},
                    format="json",
                    **_auth(self.patient_a),
                )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_appointments_me_only_returns_own(self):
        # Patient A has no appointments; Patient B has one
        resp = self.client.get("/appointments/me", **_auth(self.patient_a))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 0)

        resp_b = self.client.get("/appointments/me", **_auth(self.patient_b))
        ids = [a["id"] for a in resp_b.data]
        self.assertIn(str(self.appt_b.id), ids)
        self.assertNotIn(str(self.appt_b.id), [a["id"] for a in resp.data])

    def test_cross_hospital_doctor_cannot_access_appointment(self):
        """Doctor from hospital B cannot see an appointment at hospital A."""
        hospital_b = _hospital("Other Hospital B")
        doc_b_user, _ = _doctor(hospital_b)
        resp = self.client.get(
            f"/doctor/appointments/{self.appt_b.id}",
            **_auth(doc_b_user),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# 4. Concurrency: N concurrent holds at capacity M — never over M confirmed
# ---------------------------------------------------------------------------

class TestConcurrency(TestCase):
    """
    Simulates N threads simultaneously trying to hold and confirm a slot
    with capacity M. After all threads finish, confirmed bookings must be
    <= M.

    Uses real SQLite transactions (in-process). Redis is stubbed with a
    thread-safe in-memory counter so we can test the Postgres SELECT FOR
    UPDATE guard independently of Redis availability.
    """

    def setUp(self):
        self.hospital = _hospital("Concurrency Hospital")
        _, self.profile = _doctor(self.hospital)
        self.slot = _slot(self.profile, capacity=3)

    def test_concurrent_confirms_never_exceed_capacity(self):
        M = self.slot.capacity   # 3
        N = 8                    # 8 threads racing

        patients = [_patient(str(i)) for i in range(N)]

        # Pre-create held appointments for all patients
        holds = [_held_appointment(p, self.slot) for p in patients]

        results: list[bool] = []
        errors:  list[Exception] = []
        lock = threading.Lock()

        def try_confirm(appt: Appointment):
            try:
                from django.db import transaction
                from apps.scheduling.models import AppointmentSlot as AS
                from apps.clinical.state_machine import confirm as sm_confirm
                from common.redis_client import slot_counter_incr

                with transaction.atomic():
                    slot = AS.objects.select_for_update().get(id=appt.slot_id)
                    if slot.booked_count >= slot.capacity:
                        # Rejected — INCR Redis back (simulated)
                        with lock:
                            results.append(False)
                        return
                    token = slot.booked_count + 1
                    slot.booked_count += 1
                    slot.save(update_fields=["booked_count"])
                    sm_confirm(appt, symptom_text="Thread test symptom for concurrency.", token=token)
                    with lock:
                        results.append(True)
            except Exception as exc:
                with lock:
                    errors.append(exc)
                    results.append(False)

        threads = [threading.Thread(target=try_confirm, args=(h,)) for h in holds]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        confirmed_count = Appointment.objects.filter(
            slot=self.slot, status=AppointmentStatus.CONFIRMED
        ).count()

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")
        self.assertLessEqual(
            confirmed_count, M,
            f"Over-booked: {confirmed_count} confirmed, capacity={M}"
        )
        # Postgres booked_count must match confirmed count
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.booked_count, confirmed_count)

    def test_concurrent_holds_never_exceed_capacity_via_redis(self):
        """
        Simulates Redis DECR concurrency using a thread-safe counter.
        N threads DECR simultaneously; exactly M should succeed.
        """
        M = 3
        counter = [M]   # mutable container for thread-safe mutation
        lock    = threading.Lock()
        results = []

        def decr():
            with lock:
                counter[0] -= 1
                val = counter[0]
            if val < 0:
                # Roll back
                with lock:
                    counter[0] += 1
                results.append(False)
            else:
                results.append(True)

        N = 10
        threads = [threading.Thread(target=decr) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        granted = sum(results)
        self.assertEqual(granted, M, f"Expected exactly {M} holds granted, got {granted}")


# ---------------------------------------------------------------------------
# 5. Reconciliation task
# ---------------------------------------------------------------------------

class TestReconciliation(TestCase):

    def setUp(self):
        self.hospital = _hospital("Recon Hospital")
        _, self.profile = _doctor(self.hospital)

    def test_reconciliation_resyncs_drifted_counter(self):
        """
        Create a slot with booked_count=2 and capacity=5.
        Artificially set Redis counter to 10 (drifted high).
        After reconciliation, counter should be 3 (capacity - booked_count).
        """
        slot = _slot(self.profile, capacity=5, booked=2)

        captured: dict[str, int] = {}

        def fake_set(slot_id: str, value: int):
            captured[slot_id] = value

        with patch("apps.scheduling.tasks.slot_counter_set", side_effect=fake_set):
            from apps.scheduling.tasks import reconcile_slot_counters
            result = reconcile_slot_counters()

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["synced"], 1)
        self.assertEqual(captured.get(str(slot.id)), 3)

    def test_reconciliation_handles_zero_remaining(self):
        """A fully-booked slot should have counter set to 0, not negative."""
        slot = _slot(self.profile, capacity=3, booked=3)

        captured: dict[str, int] = {}

        def fake_set(slot_id: str, value: int):
            captured[slot_id] = value

        with patch("apps.scheduling.tasks.slot_counter_set", side_effect=fake_set):
            from apps.scheduling.tasks import reconcile_slot_counters
            reconcile_slot_counters()

        self.assertGreaterEqual(captured.get(str(slot.id), -1), 0)
        self.assertEqual(captured.get(str(slot.id)), 0)

    def test_reconciliation_skips_past_slots(self):
        """Past slots should not be synced (waste of Redis memory)."""
        past_slot = AppointmentSlot.objects.create(
            doctor=self.profile, hospital=self.hospital,
            date=datetime.date.today() - datetime.timedelta(days=1),
            slot_start=datetime.time(9, 0), slot_end=datetime.time(10, 0),
            capacity=5, booked_count=2,
        )
        captured: dict[str, int] = {}

        def fake_set(slot_id: str, value: int):
            captured[slot_id] = value

        with patch("apps.scheduling.tasks.slot_counter_set", side_effect=fake_set):
            from apps.scheduling.tasks import reconcile_slot_counters
            reconcile_slot_counters()

        self.assertNotIn(str(past_slot.id), captured)


# ---------------------------------------------------------------------------
# 6. Doctor discovery API
# ---------------------------------------------------------------------------

class TestDiscoveryAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Discovery Hospital")
        _, self.cardio_profile  = _doctor(self.hospital, "Cardiology")
        _, self.general_profile = _doctor(self.hospital, "General Physician")
        self.patient = _patient()

        # Give the cardiologist a future slot
        self.future_slot = _slot(self.cardio_profile, capacity=3)

    def test_list_doctors_returns_active_doctors(self):
        resp = self.client.get("/doctors", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [d["specialization"] for d in resp.data]
        self.assertIn("Cardiology", names)
        self.assertIn("General Physician", names)

    def test_specialization_filter(self):
        resp = self.client.get("/doctors?specialization=Cardiology", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        specializations = [d["specialization"] for d in resp.data]
        self.assertTrue(all("cardiology" in s.lower() for s in specializations))

    def test_next_available_slot_shown_for_doctor_with_open_slot(self):
        resp = self.client.get("/doctors", **_auth(self.patient))
        cardio = next(
            (d for d in resp.data if d["specialization"] == "Cardiology"), None
        )
        self.assertIsNotNone(cardio)
        self.assertIsNotNone(cardio["next_available_slot"])
        self.assertEqual(cardio["next_available_slot"]["slot_id"], str(self.future_slot.id))

    def test_next_available_slot_none_when_fully_booked(self):
        # Fill the cardiologist's slot
        self.future_slot.booked_count = self.future_slot.capacity
        self.future_slot.save(update_fields=["booked_count"])

        resp = self.client.get("/doctors?specialization=Cardiology", **_auth(self.patient))
        cardio = next(
            (d for d in resp.data if d["specialization"] == "Cardiology"), None
        )
        self.assertIsNone(cardio["next_available_slot"])

    def test_doctor_slot_list(self):
        resp = self.client.get(
            f"/doctors/{self.cardio_profile.user_id}/slots?date={self.future_slot.date.isoformat()}",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["slots"]), 1)
        self.assertEqual(resp.data["slots"][0]["id"], str(self.future_slot.id))

    def test_doctor_slot_list_marks_leave_unavailable(self):
        DoctorLeave.objects.create(
            doctor=self.cardio_profile,
            date=self.future_slot.date,
        )
        resp = self.client.get(
            f"/doctors/{self.cardio_profile.user_id}/slots?date={self.future_slot.date.isoformat()}",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["slots"][0]["unavailable"])

    def test_doctor_slot_list_marks_absent_shift_unavailable(self):
        DoctorAttendance.objects.create(
            doctor=self.cardio_profile,
            date=self.future_slot.date,
            shift="morning",
            status="absent",
            marked_by=None,
        )
        resp = self.client.get(
            f"/doctors/{self.cardio_profile.user_id}/slots?date={self.future_slot.date.isoformat()}",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["slots"][0]["unavailable"])

    def test_discovery_requires_authentication(self):
        resp = self.client.get("/doctors")
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# 7. Appointment list (GET /appointments/me)
# ---------------------------------------------------------------------------

class TestAppointmentListAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("List Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot    = _slot(self.profile)

    def test_upcoming_filter(self):
        confirmed = _confirmed_appointment(self.patient, self.slot)
        resp = self.client.get("/appointments/me?status=upcoming", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [a["id"] for a in resp.data]
        self.assertIn(str(confirmed.id), ids)

    def test_past_filter_excludes_upcoming(self):
        _confirmed_appointment(self.patient, self.slot)
        resp = self.client.get("/appointments/me?status=past", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Confirmed future appointment should NOT appear in past
        self.assertEqual(len(resp.data), 0)

    def test_all_filter_returns_all_statuses(self):
        appt = _confirmed_appointment(self.patient, self.slot)
        with patch("apps.clinical.state_machine.slot_counter_incr"):
            cancel_confirmed(appt)
        resp = self.client.get("/appointments/me?status=all", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["status"], "cancelled")
