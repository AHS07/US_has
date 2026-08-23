"""
test_isolation.py

Phase 1 exit criterion:
  Patient A's token against Patient B's resource ID returns 404
  (scoped — we return 404, not 403, so the existence of the resource is not leaked).

This suite is kept and extended in EVERY subsequent phase — one test per new
patient-data endpoint added. Never delete tests from this file.
"""
from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import PatientNote

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def hospital(db):
    return Hospital.objects.create(
        name="Test Hospital",
        contact_email="test@hospital.com",
    )


@pytest.fixture()
def patient_a(db, hospital):
    return User.objects.create_user(
        email="patient_a@test.com",
        password="StrongPass1!",
        name="Patient A",
        role=UserRole.PATIENT,
        must_reset_password=False,
    )


@pytest.fixture()
def patient_b(db, hospital):
    return User.objects.create_user(
        email="patient_b@test.com",
        password="StrongPass1!",
        name="Patient B",
        role=UserRole.PATIENT,
        must_reset_password=False,
    )


@pytest.fixture()
def note_for_b(db, patient_b, hospital):
    """A PatientNote that belongs to Patient B."""
    return PatientNote.objects.create(
        patient=patient_b,
        hospital=hospital,
        body="Patient B's private note.",
    )


def _auth_client(user: User) -> APIClient:
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    refresh["user_id"] = str(user.id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


# ─── Core isolation test ──────────────────────────────────────────────────────

@pytest.mark.django_db()
def test_patient_a_cannot_access_patient_b_note(patient_a, note_for_b):
    """
    Patient A's token against Patient B's note ID must not return 200.
    Scoped queries return 404 (not 403) so existence is not confirmed.
    """
    client = _auth_client(patient_a)
    url = f"/clinical/notes/{note_for_b.id}"
    response = client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, (
        f"Expected 404, got {response.status_code}. "
        "Patient A should never see Patient B's resource."
    )


@pytest.mark.django_db()
def test_patient_b_can_access_own_note(patient_b, note_for_b):
    """Patient B's token against their own note returns 200."""
    client = _auth_client(patient_b)
    url = f"/clinical/notes/{note_for_b.id}"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert str(note_for_b.id) in response.json()["id"]


@pytest.mark.django_db()
def test_unauthenticated_cannot_access_note(note_for_b):
    """Unauthenticated request returns 401."""
    client = APIClient()
    url = f"/clinical/notes/{note_for_b.id}"
    response = client.get(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ─── Auth endpoint tests ──────────────────────────────────────────────────────

@pytest.mark.django_db()
def test_login_returns_tokens_with_custom_claims(patient_a):
    client = APIClient()
    response = client.post(
        "/auth/login",
        {"email": "patient_a@test.com", "password": "StrongPass1!"},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "access" in data
    assert "refresh" in data
    assert data["role"] == UserRole.PATIENT
    assert data["must_reset_password"] is False


@pytest.mark.django_db()
def test_login_wrong_password_returns_400(patient_a):
    client = APIClient()
    response = client.post(
        "/auth/login",
        {"email": "patient_a@test.com", "password": "WrongPassword"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db()
def test_must_reset_password_blocks_protected_endpoint(patient_a):
    """A user with must_reset_password=True cannot access protected endpoints."""
    patient_a.must_reset_password = True
    patient_a.save(update_fields=["must_reset_password"])
    client = _auth_client(patient_a)
    response = client.get("/clinical/notes/00000000-0000-0000-0000-000000000000")
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["error"]["code"] == "must_reset_password"


@pytest.mark.django_db()
def test_hospital_bootstrap_creates_hospital_and_admin(db):
    client = APIClient()
    response = client.post(
        "/admin-api/hospitals",
        {
            "hospital_name": "City Care",
            "contact_email": "admin@citycare.com",
            "admin_name": "Anita Shah",
            "admin_email": "anita@citycare.com",
            "admin_password": "Secure@1234",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert "access" in data
    assert data["role"] == UserRole.ADMIN
    assert Hospital.objects.count() == 1
    assert User.objects.filter(role=UserRole.ADMIN).count() == 1


@pytest.mark.django_db()
def test_hospital_bootstrap_blocked_if_hospital_exists(hospital, db):
    client = APIClient()
    response = client.post(
        "/admin-api/hospitals",
        {
            "hospital_name": "Another Hospital",
            "contact_email": "other@hospital.com",
            "admin_name": "Bob",
            "admin_email": "bob@hospital.com",
            "admin_password": "Secure@1234",
        },
        format="json",
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db()
def test_admin_can_create_patient(hospital, db):
    admin = User.objects.create_user(
        email="admin@hospital.com",
        password="Admin@1234",
        name="Admin User",
        role=UserRole.ADMIN,
        hospital=hospital,
        must_reset_password=False,
    )
    client = _auth_client(admin)
    response = client.post(
        "/admin-api/patients",
        {"name": "New Patient", "email": "newpatient@test.com", "phone": "9999999999"},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert User.objects.filter(email="newpatient@test.com", role=UserRole.PATIENT).exists()


@pytest.mark.django_db()
def test_patient_cannot_call_admin_endpoint(patient_a):
    client = _auth_client(patient_a)
    response = client.get("/admin-api/patients")
    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db()
def test_logout_invalidates_refresh_token(patient_a):
    """After logout, the refresh token should be blacklisted."""
    client = _auth_client(patient_a)
    # Get a fresh token pair first
    login_resp = APIClient().post(
        "/auth/login",
        {"email": "patient_a@test.com", "password": "StrongPass1!"},
        format="json",
    )
    refresh_token = login_resp.json()["refresh"]

    # Logout
    logout_resp = client.post("/auth/logout", {"refresh": refresh_token}, format="json")
    assert logout_resp.status_code == status.HTTP_200_OK

    # Try to use the blacklisted refresh token
    refresh_resp = APIClient().post(
        "/auth/refresh", {"refresh": refresh_token}, format="json"
    )
    assert refresh_resp.status_code == status.HTTP_401_UNAUTHORIZED
