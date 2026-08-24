"""
notifications/tests/test_notifications.py

Phase 6 exit-criteria tests (phases.md):
  "Every event type produces both an in-app row and an email job from the
   same trigger, verified they never diverge under a forced email-provider
   failure (email retries; in-app row still exists and is readable)."

Categories:
  1.  fire_notification — in-app + email always created together; no divergence
  2.  Event types — booking_confirmed, booking_cancelled, visit_summary_ready
  3.  send_email_job task — sent, retry on failure, failed after 5 retries
  4.  generate_ics — valid RFC 5545 content, attaches to EmailJob
  5.  sync_google_calendar_event — skips gracefully when no credentials
  6.  Notification API — list (scoped), mark-read, mark-all-read, isolation
  7.  Calendar OAuth API — status, connect returns auth_url, disconnect deletes creds
  8.  expire_stale_holds — cancels expired holds, does not touch fresh ones
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import Appointment, AppointmentStatus
from apps.notifications.models import (
    DoctorGoogleCredentials,
    EmailJob,
    EmailJobStatus,
    Notification,
    NotificationEventType,
)
from apps.scheduling.models import AppointmentSlot, DoctorProfile, ShiftConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _jwt(user: User) -> str:
    t = JWTRefreshToken.for_user(user)
    t["role"]        = user.role
    t["hospital_id"] = str(user.hospital_id) if user.hospital_id else None
    t["user_id"]     = str(user.id)
    return str(t.access_token)


def _auth(user: User) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {_jwt(user)}"}


def _hospital(n: str = "H") -> Hospital:
    return Hospital.objects.create(
        name=n, contact_email=f"{uuid.uuid4().hex[:6]}@h.local"
    )


def _doctor(hospital: Hospital) -> tuple[User, DoctorProfile]:
    u = User.objects.create_user(
        email=f"dr{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Dr Test", role=UserRole.DOCTOR, hospital=hospital,
        must_reset_password=False,
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
        name="Patient", role=UserRole.PATIENT, hospital=None,
        must_reset_password=False,
    )


def _admin(hospital: Hospital) -> User:
    return User.objects.create_user(
        email=f"admin{uuid.uuid4().hex[:6]}@h.local", password="pass",
        name="Admin", role=UserRole.ADMIN, hospital=hospital,
        must_reset_password=False,
    )


def _slot(profile: DoctorProfile) -> AppointmentSlot:
    return AppointmentSlot.objects.create(
        doctor=profile, hospital=profile.user.hospital,
        date=datetime.date.today() + datetime.timedelta(days=5),
        slot_start=datetime.time(9, 0), slot_end=datetime.time(10, 0),
        capacity=5, booked_count=0,
    )


def _confirmed_appt(patient: User, slot: AppointmentSlot) -> Appointment:
    slot.booked_count += 1
    slot.save(update_fields=["booked_count"])
    return Appointment.objects.create(
        patient=patient, doctor=slot.doctor.user,
        slot=slot, hospital=slot.hospital,
        status=AppointmentStatus.CONFIRMED, token=1,
        symptom_text="Cough and fever.", held_until=None,
    )


def _fire(event_type: str, appt: Appointment) -> Notification | None:
    from apps.notifications.events import fire_notification
    return fire_notification(event_type, appt)


# ---------------------------------------------------------------------------
# 1. fire_notification — in-app + email always together
# ---------------------------------------------------------------------------

class TestFireNotification(TestCase):

    def setUp(self):
        self.hospital = _hospital()
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile)
        self.appt = _confirmed_appt(self.patient, self.slot)

    def test_creates_notification_and_email_job_together(self):
        """PHASE 6 EXIT CRITERION: both rows always created in the same call."""
        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)

        self.assertIsNotNone(notif)
        self.assertEqual(Notification.objects.filter(patient=self.patient).count(), 1)
        self.assertEqual(EmailJob.objects.filter(recipient_email=self.patient.email).count(), 1)
        self.assertTrue(EmailJob.objects.filter(recipient_email=self.appt.doctor.email).exists())

    def test_email_job_linked_to_notification(self):
        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        self.assertTrue(hasattr(notif, "email_job"))
        self.assertEqual(notif.email_job.recipient_email, self.patient.email)

    def test_notification_failure_does_not_raise(self):
        """Even if notification creation fails, no exception escapes."""
        with patch("apps.notifications.models.Notification.objects") as mock_mgr:
            mock_mgr.create.side_effect = Exception("DB error")
            result = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        self.assertIsNone(result)

    def test_email_divergence_impossible_notification_deleted_on_rollback(self):
        """
        If EmailJob.create() fails after Notification.create() succeeds,
        the outer transaction rolls back both. We simulate this scenario.
        """
        from django.db import transaction

        n_before = Notification.objects.count()
        e_before = EmailJob.objects.count()

        try:
            with transaction.atomic():
                from apps.notifications.events import fire_notification
                # Force EmailJob creation to fail
                with patch("apps.notifications.models.EmailJob.objects") as mock:
                    mock.create.side_effect = Exception("EmailJob DB failure")
                    fire_notification(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        except Exception:
            pass

        # Both counts unchanged — no orphan Notification without EmailJob
        self.assertEqual(Notification.objects.count(), n_before)
        self.assertEqual(EmailJob.objects.count(), e_before)

    def test_booking_confirmed_sets_correct_event_type(self):
        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        self.assertEqual(notif.event_type, NotificationEventType.BOOKING_CONFIRMED)

    def test_booking_cancelled_sets_correct_event_type(self):
        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CANCELLED, self.appt)
        self.assertEqual(notif.event_type, NotificationEventType.BOOKING_CANCELLED)

    def test_visit_summary_ready_event(self):
        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.VISIT_SUMMARY_READY, self.appt)
        self.assertIsNotNone(notif)
        self.assertEqual(notif.event_type, NotificationEventType.VISIT_SUMMARY_READY)


# ---------------------------------------------------------------------------
# 2. send_email_job task
# ---------------------------------------------------------------------------

class TestSendEmailJob(TestCase):

    def setUp(self):
        self.hospital = _hospital("Email Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile)
        self.appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        self.job = notif.email_job

    def test_successful_send_sets_status_sent(self):
        from apps.notifications.tasks import send_email_job

        with patch("apps.notifications.tasks.EmailMultiAlternatives") as MockMsg:
            MockMsg.return_value.send.return_value = 1
            result = send_email_job(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, EmailJobStatus.SENT)
        self.assertIsNotNone(self.job.sent_at)
        self.assertEqual(result["status"], "sent")

    def test_idempotent_already_sent(self):
        from apps.notifications.tasks import send_email_job

        self.job.status = EmailJobStatus.SENT
        self.job.save(update_fields=["status"])

        result = send_email_job(str(self.job.id))
        self.assertEqual(result["status"], "already_sent")

    def test_failed_after_5_retries(self):
        """
        PHASE 6 EXIT CRITERION:
        After 5 retries, status = failed but in-app notification still exists.
        """
        from apps.notifications.tasks import send_email_job

        self.job.retry_count = 4
        self.job.save(update_fields=["retry_count"])

        with patch("apps.notifications.tasks.EmailMultiAlternatives") as MockMsg:
            MockMsg.return_value.send.side_effect = Exception("SMTP down")
            with patch.object(send_email_job, "retry", side_effect=Exception("MaxRetries")):
                send_email_job(str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, EmailJobStatus.FAILED)

        # In-app notification must still be readable
        notif = Notification.objects.get(id=self.job.notification_id)
        self.assertEqual(notif.event_type, NotificationEventType.BOOKING_CONFIRMED)

    def test_email_failure_does_not_delete_notification(self):
        """
        In-app row survives email provider failure — they never diverge.
        """
        from apps.notifications.tasks import send_email_job

        notif_id = self.job.notification_id

        with patch("apps.notifications.tasks.EmailMultiAlternatives") as MockMsg:
            MockMsg.return_value.send.side_effect = Exception("SMTP error")
            with patch.object(send_email_job, "retry", side_effect=Exception("MaxRetries")):
                for _ in range(5):
                    self.job.refresh_from_db()
                    if self.job.status == EmailJobStatus.SENT:
                        break
                    try:
                        send_email_job(str(self.job.id))
                    except Exception:
                        pass

        # In-app notification still present regardless of email outcome
        self.assertTrue(Notification.objects.filter(id=notif_id).exists())


# ---------------------------------------------------------------------------
# 3. generate_ics
# ---------------------------------------------------------------------------

class TestGenerateICS(TestCase):

    def setUp(self):
        self.hospital = _hospital("ICS Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile)
        self.appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.notifications.events._enqueue_side_tasks"):
            notif = _fire(NotificationEventType.BOOKING_CONFIRMED, self.appt)
        self.job = notif.email_job

    def test_ics_attached_to_email_job(self):
        from apps.notifications.tasks import generate_ics
        generate_ics(str(self.appt.id), str(self.job.id))
        self.job.refresh_from_db()
        self.assertIn("BEGIN:VCALENDAR", self.job.ics_attachment)

    def test_ics_contains_appointment_uid(self):
        from apps.notifications.tasks import generate_ics
        generate_ics(str(self.appt.id), str(self.job.id))
        self.job.refresh_from_db()
        self.assertIn(str(self.appt.id), self.job.ics_attachment)

    def test_ics_contains_dtstart(self):
        from apps.notifications.tasks import generate_ics
        generate_ics(str(self.appt.id), str(self.job.id))
        self.job.refresh_from_db()
        self.assertIn("DTSTART:", self.job.ics_attachment)

    def test_ics_contains_patient_email(self):
        from apps.notifications.tasks import generate_ics
        generate_ics(str(self.appt.id), str(self.job.id))
        self.job.refresh_from_db()
        self.assertIn(self.patient.email, self.job.ics_attachment)

    def test_ics_idempotent(self):
        from apps.notifications.tasks import generate_ics
        generate_ics(str(self.appt.id), str(self.job.id))
        first = EmailJob.objects.get(id=self.job.id).ics_attachment
        generate_ics(str(self.appt.id), str(self.job.id))
        second = EmailJob.objects.get(id=self.job.id).ics_attachment
        self.assertEqual(first, second)


# ---------------------------------------------------------------------------
# 4. sync_google_calendar_event — skips when no credentials
# ---------------------------------------------------------------------------

class TestSyncGoogleCalendar(TestCase):

    def setUp(self):
        self.hospital = _hospital("Cal Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile)
        self.appt = _confirmed_appt(self.patient, self.slot)

    def test_skips_gracefully_when_no_credentials(self):
        from apps.notifications.tasks import sync_google_calendar_event
        result = sync_google_calendar_event(str(self.appt.id), "create")
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_calendar_connected")

    def test_calls_create_when_credentials_exist(self):
        from apps.notifications.tasks import sync_google_calendar_event
        from common.encryption import encrypt_token

        DoctorGoogleCredentials.objects.create(
            doctor=self.profile.user,
            access_token_enc=encrypt_token("fake_access_token"),
            refresh_token_enc=encrypt_token("fake_refresh_token"),
        )

        with patch("apps.integrations.calendar.client.GoogleCalendarClient.create_event",
                   return_value="google_event_123"):
            with patch("apps.integrations.calendar.client.GoogleCalendarClient._get_service",
                       return_value=MagicMock()):
                result = sync_google_calendar_event(str(self.appt.id), "create")

        self.assertEqual(result["status"], "ok")


# ---------------------------------------------------------------------------
# 5. Notification API
# ---------------------------------------------------------------------------

class TestNotificationAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("Notif API Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient  = _patient()
        self.patient2 = _patient()
        self.slot = _slot(self.profile)
        self.appt = _confirmed_appt(self.patient, self.slot)

        # Create two notifications for patient
        with patch("apps.notifications.events._enqueue_side_tasks"):
            self.notif1 = _fire(NotificationEventType.BOOKING_CONFIRMED,  self.appt)
            self.notif2 = _fire(NotificationEventType.VISIT_SUMMARY_READY, self.appt)

    def test_patient_can_list_own_notifications(self):
        resp = self.client.get("/notifications", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["notifications"]), 2)
        self.assertEqual(resp.data["unread_count"], 2)

    def test_other_patient_cannot_see_notifications(self):
        resp = self.client.get("/notifications", **_auth(self.patient2))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["notifications"]), 0)

    def test_mark_single_read(self):
        resp = self.client.patch(
            f"/notifications/{self.notif1.id}/read",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["is_read"])
        self.notif1.refresh_from_db()
        self.assertTrue(self.notif1.is_read)

    def test_mark_all_read(self):
        resp = self.client.post("/notifications/read-all", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["marked_read"], 2)
        self.assertEqual(
            Notification.objects.filter(patient=self.patient, is_read=False).count(), 0
        )

    def test_mark_other_patients_notification_returns_404(self):
        resp = self.client.patch(
            f"/notifications/{self.notif1.id}/read",
            **_auth(self.patient2),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_doctor_cannot_access_notifications(self):
        resp = self.client.get("/notifications", **_auth(self.profile.user))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unread_only_filter(self):
        self.notif1.is_read = True
        self.notif1.save(update_fields=["is_read"])
        resp = self.client.get("/notifications?unread_only=true", **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["notifications"]), 1)


# ---------------------------------------------------------------------------
# 6. Calendar OAuth API
# ---------------------------------------------------------------------------

class TestCalendarOAuthAPI(APITestCase):

    def setUp(self):
        self.hospital = _hospital("OAuth Hospital")
        self.doc_user, _ = _doctor(self.hospital)

    def test_calendar_status_not_connected(self):
        resp = self.client.get("/doctor/calendar/status", **_auth(self.doc_user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["connected"])

    def test_calendar_status_connected(self):
        from common.encryption import encrypt_token
        DoctorGoogleCredentials.objects.create(
            doctor=self.doc_user,
            access_token_enc=encrypt_token("tok"),
            calendar_id="primary",
        )
        resp = self.client.get("/doctor/calendar/status", **_auth(self.doc_user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data["connected"])

    def test_connect_returns_auth_url(self):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://google.com/auth", "state123")

        with patch("apps.integrations.calendar.client.GoogleCalendarClient.build_oauth_flow",
                   return_value=mock_flow):
            resp = self.client.get("/doctor/calendar/connect", **_auth(self.doc_user))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("auth_url", resp.data)

    def test_disconnect_deletes_credentials(self):
        from common.encryption import encrypt_token
        DoctorGoogleCredentials.objects.create(
            doctor=self.doc_user,
            access_token_enc=encrypt_token("old_token"),
        )
        with patch("apps.notifications.views.http_requests") as mock_req:
            mock_req.post.return_value = MagicMock(status_code=200)
            resp = self.client.delete(
                "/doctor/calendar/disconnect", **_auth(self.doc_user)
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["connected"])
        self.assertFalse(
            DoctorGoogleCredentials.objects.filter(doctor=self.doc_user).exists()
        )

    def test_disconnect_no_credentials_still_200(self):
        resp = self.client.delete(
            "/doctor/calendar/disconnect", **_auth(self.doc_user)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["connected"])

    def test_patient_cannot_access_calendar_endpoints(self):
        patient = _patient()
        resp = self.client.get("/doctor/calendar/status", **_auth(patient))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 7. expire_stale_holds
# ---------------------------------------------------------------------------

class TestExpireStaleHolds(TestCase):

    def setUp(self):
        self.hospital = _hospital("Sweep Hospital")
        _, self.profile = _doctor(self.hospital)
        self.patient = _patient()
        self.slot = _slot(self.profile)

    def test_expired_hold_cancelled(self):
        from apps.notifications.tasks import expire_stale_holds

        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=self.slot, hospital=self.hospital,
            status=AppointmentStatus.HELD,
            held_until=timezone.now() - datetime.timedelta(minutes=1),
        )

        with patch("apps.notifications.events._enqueue_side_tasks"):
            result = expire_stale_holds()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.CANCELLED)
        self.assertGreaterEqual(result["cancelled"], 1)

    def test_fresh_hold_not_cancelled(self):
        from apps.notifications.tasks import expire_stale_holds

        appt = Appointment.objects.create(
            patient=self.patient, doctor=self.profile.user,
            slot=self.slot, hospital=self.hospital,
            status=AppointmentStatus.HELD,
            held_until=timezone.now() + datetime.timedelta(minutes=10),
        )

        with patch("apps.notifications.events._enqueue_side_tasks"):
            expire_stale_holds()

        appt.refresh_from_db()
        self.assertEqual(appt.status, AppointmentStatus.HELD)
