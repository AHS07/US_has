"""
test_isolation_phase9.py

Phase 9: Full cross-endpoint isolation + error-envelope audit.

Extends the Phase 1 suite (test_isolation.py) to cover every patient-data
endpoint added in Phases 3–8. Tests are grouped by:
  1. Patient appointment endpoints (Phases 3–7)
  2. Attachment endpoints (Phase 4)
  3. Post-visit summary endpoint (Phase 5)
  4. Notification endpoints (Phase 6)
  5. Dashboard + patient-accounts admin endpoints (Phase 9)
  6. Error envelope shape audit (Phase 9 polish)

Isolation rules verified here:
  - Patient A token against Patient B resource → 404 (never 403 — existence not leaked)
  - Doctor from hospital B cannot see hospital A resources → 404
  - Patient cannot call doctor/admin endpoints → 403
  - Doctor cannot call patient/admin endpoints → 403
  - Every error response uses the { error: { code, message } } envelope
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import (
    Appointment, AppointmentStatus,
    MedicineCatalog, MedicineStatus,
)
from apps.notifications.models import Notification, NotificationEventType
from apps.scheduling.models import AppointmentSlot, DoctorProfile, ShiftConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def hospital_a(db):
    return Hospital.objects.create(
        name="Hospital A", contact_email=f"a{uuid.uuid4().hex[:4]}@h.local"
    )


@pytest.fixture()
def hospital_b(db):
    return Hospital.objects.create(
        name="Hospital B", contact_email=f"b{uuid.uuid4().hex[:4]}@h.local"
    )


@pytest.fixture()
def admin_a(db, hospital_a):
    return User.objects.create_user(
        email="admin_a@h.local", password="Admin@1234",
        name="Admin A", role=UserRole.ADMIN,
        hospital=hospital_a, must_reset_password=False,
    )


@pytest.fixture()
def doctor_a(db, hospital_a):
    u = User.objects.create_user(
        email="dr_a@h.local", password="pass",
        name="Dr A", role=UserRole.DOCTOR,
        hospital=hospital_a, must_reset_password=False,
    )
    p = DoctorProfile.objects.create(
        user=u, specialization="General",
        slot_duration_minutes=60, slot_capacity=5,
    )
    ShiftConfig.objects.create(doctor=p, working_days=[1, 2, 3, 4, 5])
    return u


@pytest.fixture()
def doctor_b(db, hospital_b):
    u = User.objects.create_user(
        email="dr_b@h.local", password="pass",
        name="Dr B", role=UserRole.DOCTOR,
        hospital=hospital_b, must_reset_password=False,
    )
    p = DoctorProfile.objects.create(
        user=u, specialization="General",
        slot_duration_minutes=60, slot_capacity=5,
    )
    ShiftConfig.objects.create(doctor=p, working_days=[1, 2, 3, 4, 5])
    return u


@pytest.fixture()
def patient_a(db):
    return User.objects.create_user(
        email="pat_a@h.local", password="pass",
        name="Patient A", role=UserRole.PATIENT,
        hospital=None, must_reset_password=False,
    )


@pytest.fixture()
def patient_b(db):
    return User.objects.create_user(
        email="pat_b@h.local", password="pass",
        name="Patient B", role=UserRole.PATIENT,
        hospital=None, must_reset_password=False,
    )


@pytest.fixture()
def slot_a(db, doctor_a, hospital_a):
    return AppointmentSlot.objects.create(
        doctor=doctor_a.doctor_profile,
        hospital=hospital_a,
        date=datetime.date.today() + datetime.timedelta(days=5),
        slot_start=datetime.time(9, 0),
        slot_end=datetime.time(10, 0),
        capacity=5,
        booked_count=1,
    )


@pytest.fixture()
def appt_b(db, patient_b, slot_a):
    """A confirmed appointment belonging to Patient B at Hospital A."""
    return Appointment.objects.create(
        patient=patient_b,
        doctor=slot_a.doctor.user,
        slot=slot_a,
        hospital=slot_a.hospital,
        status=AppointmentStatus.CONFIRMED,
        token=1,
        symptom_text="Cough.",
        held_until=None,
    )


@pytest.fixture()
def notif_b(db, patient_b, hospital_a, appt_b):
    return Notification.objects.create(
        patient=patient_b,
        hospital=hospital_a,
        appointment=appt_b,
        event_type=NotificationEventType.BOOKING_CONFIRMED,
        title="Confirmed",
        body="Your appointment is confirmed.",
    )


def _client(user: User) -> APIClient:
    c = APIClient()
    t = RefreshToken.for_user(user)
    t["role"]        = user.role
    t["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    t["user_id"]     = str(user.id)
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {str(t.access_token)}")
    return c


def _assert_envelope(response, expected_status: int) -> None:
    """Assert the response has the correct status and error envelope shape."""
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.data}"
    )
    if expected_status >= 400:
        data = response.json()
        assert "error" in data, f"Missing 'error' key in response: {data}"
        assert "code" in data["error"],    f"Missing 'error.code': {data}"
        assert "message" in data["error"], f"Missing 'error.message': {data}"


# ---------------------------------------------------------------------------
# 1. Patient appointment isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_patient_a_cannot_get_patient_b_appointment(patient_a, appt_b):
    r = _client(patient_a).get(f"/appointments/{appt_b.id}")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_patient_a_cannot_cancel_patient_b_appointment(patient_a, appt_b):
    r = _client(patient_a).post(f"/appointments/{appt_b.id}/cancel", format="json")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_patient_a_cannot_confirm_patient_b_hold(patient_a, patient_b, slot_a):
    held = Appointment.objects.create(
        patient=patient_b, doctor=slot_a.doctor.user,
        slot=slot_a, hospital=slot_a.hospital,
        status=AppointmentStatus.HELD,
        held_until=timezone.now() + datetime.timedelta(minutes=10),
    )
    r = _client(patient_a).post(
        f"/appointments/{held.id}/confirm",
        {"symptom_text": "Trying to access another hold."},
        format="json",
    )
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_patient_a_cannot_delete_patient_b_hold(patient_a, patient_b, slot_a):
    held = Appointment.objects.create(
        patient=patient_b, doctor=slot_a.doctor.user,
        slot=slot_a, hospital=slot_a.hospital,
        status=AppointmentStatus.HELD,
        held_until=timezone.now() + datetime.timedelta(minutes=10),
    )
    r = _client(patient_a).delete(f"/appointments/{held.id}/hold")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_appointments_me_only_returns_own(patient_a, patient_b, appt_b):
    r = _client(patient_a).get("/appointments/me")
    assert r.status_code == status.HTTP_200_OK
    ids = [a["id"] for a in r.json()]
    assert str(appt_b.id) not in ids


@pytest.mark.django_db()
def test_post_visit_summary_only_own(patient_a, appt_b):
    appt_b.summary_status = "approved"
    appt_b.save(update_fields=["summary_status"])
    r = _client(patient_a).get(f"/appointments/{appt_b.id}/post-visit-summary")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


# ---------------------------------------------------------------------------
# 2. Attachment isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_patient_a_cannot_list_patient_b_attachments(patient_a, appt_b):
    r = _client(patient_a).get(f"/appointments/{appt_b.id}/attachments")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_doctor_cannot_upload_attachment(doctor_a, appt_b):
    from django.core.files.uploadedfile import SimpleUploadedFile
    f = SimpleUploadedFile("x.pdf", b"%PDF", content_type="application/pdf")
    r = _client(doctor_a).post(
        f"/appointments/{appt_b.id}/attachments", {"file": f}, format="multipart"
    )
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 3. Doctor appointment isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_doctor_b_cannot_see_hospital_a_appointment(doctor_b, appt_b):
    r = _client(doctor_b).get(f"/doctor/appointments/{appt_b.id}")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_patient_cannot_call_doctor_consultation_endpoint(patient_a, appt_b):
    r = _client(patient_a).post(
        f"/doctor/appointments/{appt_b.id}/consultation",
        {"notes": "Should not reach here.", "prescriptions": []},
        format="json",
    )
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 4. Notification isolation
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_patient_a_cannot_read_patient_b_notification(patient_a, notif_b):
    r = _client(patient_a).patch(f"/notifications/{notif_b.id}/read")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_notifications_list_only_own(patient_a, notif_b):
    r = _client(patient_a).get("/notifications")
    assert r.status_code == status.HTTP_200_OK
    ids = [n["id"] for n in r.json()["notifications"]]
    assert str(notif_b.id) not in ids


@pytest.mark.django_db()
def test_doctor_cannot_access_notifications(doctor_a):
    r = _client(doctor_a).get("/notifications")
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db()
def test_admin_cannot_access_patient_notifications(admin_a):
    r = _client(admin_a).get("/notifications")
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 5. Admin isolation — cross-hospital doctors/patients
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_admin_a_cannot_see_hospital_b_doctor_profile(admin_a, doctor_b):
    r = _client(admin_a).get(f"/admin-api/doctors/{doctor_b.id}/profile")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_patient_cannot_access_admin_dashboard(patient_a):
    r = _client(patient_a).get("/admin-api/dashboard")
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db()
def test_doctor_cannot_access_admin_dashboard(doctor_a):
    r = _client(doctor_a).get("/admin-api/dashboard")
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db()
def test_admin_dashboard_returns_hospital_scoped_stats(admin_a, hospital_a, slot_a, appt_b):
    r = _client(admin_a).get("/admin-api/dashboard")
    assert r.status_code == status.HTTP_200_OK
    data = r.json()
    assert "todays_bookings"     in data
    assert "doctor_count"        in data
    assert "pending_medicines"   in data
    assert "unread_notifications" in data
    assert "recent_appointments"  in data


@pytest.mark.django_db()
def test_admin_patient_list_scoped_to_hospital(admin_a, patient_a, patient_b, appt_b):
    """
    Phase 9: PatientListCreateView.get() now returns only patients with
    appointments at the admin's hospital. patient_a has none; patient_b has one.
    """
    r = _client(admin_a).get("/admin-api/patients")
    assert r.status_code == status.HTTP_200_OK
    ids = [p["id"] for p in r.json()]
    # patient_b has appt_b at hospital_a → should appear
    assert str(patient_b.id) in ids
    # patient_a has no appointments → should NOT appear
    assert str(patient_a.id) not in ids


# ---------------------------------------------------------------------------
# 6. Error envelope shape audit
# ---------------------------------------------------------------------------

@pytest.mark.django_db()
def test_401_has_error_envelope():
    r = APIClient().get("/appointments/me")
    _assert_envelope(r, status.HTTP_401_UNAUTHORIZED)


@pytest.mark.django_db()
def test_404_has_error_envelope(patient_a):
    r = _client(patient_a).get(f"/appointments/{uuid.uuid4()}")
    _assert_envelope(r, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db()
def test_403_has_error_envelope(patient_a):
    r = _client(patient_a).get("/admin-api/dashboard")
    _assert_envelope(r, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db()
def test_400_has_error_envelope_with_detail(patient_a, slot_a):
    """POST /appointments/hold with invalid payload → 400 with detail."""
    r = _client(patient_a).post(
        "/appointments/hold",
        {"slot_id": "not-a-uuid", "doctor_id": str(uuid.uuid4())},
        format="json",
    )
    _assert_envelope(r, status.HTTP_400_BAD_REQUEST)
    data = r.json()
    assert "detail" in data["error"], "400 response must include 'error.detail'"


@pytest.mark.django_db()
def test_response_never_leaks_exception_text(patient_a):
    """
    Ensure raw Python exception text is never returned.
    We hit a 404 endpoint — the message must be the generic string, not a traceback.
    """
    r = _client(patient_a).get(f"/appointments/{uuid.uuid4()}")
    data = r.json()
    message = data.get("error", {}).get("message", "")
    assert "Traceback" not in message
    assert "Exception" not in message
    assert "django" not in message.lower()


@pytest.mark.django_db()
def test_doctor_slot_list_requires_auth():
    r = APIClient().get(f"/doctors/{uuid.uuid4()}/slots")
    _assert_envelope(r, status.HTTP_401_UNAUTHORIZED)
