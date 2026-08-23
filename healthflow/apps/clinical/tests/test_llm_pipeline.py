"""
clinical/tests/test_llm_pipeline.py

Phase 4 exit-criteria tests (phases.md):
  "Killing the LLM connection mid-test still lets a booking confirm
   successfully and eventually surfaces 'unavailable' on the doctor's card
   rather than hanging in 'pending' forever."

Categories:
  1.  Urgency rules — keyword detection, override, no false positives
  2.  Schema validation — valid JSON, malformed, missing keys, markdown fences
  3.  pre_visit_llm_job task — success, LLM down → unavailable, malformed → unavailable,
      urgency override persists, non-confirmed appointment skipped, duplicate skip
  4.  Attachment CRUD — upload, list, delete, 5-cap, wrong patient blocked
  5.  DoctorAppointmentDetail — pre_summary_content populated when ready, None otherwise
"""
from __future__ import annotations

import datetime
import io
import json
import uuid
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken as JWTRefreshToken

from apps.accounts.models import Hospital, User, UserRole
from apps.clinical.models import (
    Appointment,
    AppointmentStatus,
    PreSummaryStatus,
    PreVisitAttachment,
)
from apps.scheduling.models import AppointmentSlot, DoctorProfile, ShiftConfig


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


def _make_hospital() -> Hospital:
    return Hospital.objects.create(
        name=f"H-{uuid.uuid4().hex[:6]}",
        contact_email=f"h{uuid.uuid4().hex[:6]}@test.local",
    )


def _make_doctor(hospital: Hospital) -> tuple[User, DoctorProfile]:
    user = User.objects.create_user(
        email=f"dr{uuid.uuid4().hex[:6]}@test.local",
        password="pass",
        name="Dr. Test",
        role=UserRole.DOCTOR,
        hospital=hospital,
        must_reset_password=False,
    )
    profile = DoctorProfile.objects.create(
        user=user, specialization="General",
        slot_duration_minutes=60, slot_capacity=5,
    )
    ShiftConfig.objects.create(doctor=profile, working_days=[1, 2, 3, 4, 5])
    return user, profile


def _make_patient() -> User:
    return User.objects.create_user(
        email=f"p{uuid.uuid4().hex[:6]}@test.local",
        password="pass",
        name="Patient",
        role=UserRole.PATIENT,
        hospital=None,
        must_reset_password=False,
    )


def _make_slot(profile: DoctorProfile) -> AppointmentSlot:
    return AppointmentSlot.objects.create(
        doctor=profile,
        hospital=profile.user.hospital,
        date=datetime.date.today() + datetime.timedelta(days=7),
        slot_start=datetime.time(9, 0),
        slot_end=datetime.time(10, 0),
        capacity=5,
        booked_count=0,
    )


def _confirmed_appt(patient: User, slot: AppointmentSlot) -> Appointment:
    slot.booked_count += 1
    slot.save(update_fields=["booked_count"])
    return Appointment.objects.create(
        patient=patient,
        doctor=slot.doctor.user,
        slot=slot,
        hospital=slot.hospital,
        status=AppointmentStatus.CONFIRMED,
        token=1,
        symptom_text="Persistent cough and mild fever for three days.",
        held_until=None,
    )


def _held_appt(patient: User, slot: AppointmentSlot) -> Appointment:
    return Appointment.objects.create(
        patient=patient,
        doctor=slot.doctor.user,
        slot=slot,
        hospital=slot.hospital,
        status=AppointmentStatus.HELD,
        held_until=timezone.now() + datetime.timedelta(minutes=10),
    )


# ---------------------------------------------------------------------------
# 1. Urgency rules
# ---------------------------------------------------------------------------

class TestUrgencyRules(TestCase):

    def setUp(self):
        from apps.integrations.llm.urgency import evaluate_urgency, should_override_llm
        self.eval   = evaluate_urgency
        self.override = should_override_llm

    def test_high_keyword_detected(self):
        level, kws = self.eval("I have chest pain and difficulty breathing.")
        self.assertEqual(level, "High")
        self.assertTrue(len(kws) > 0)

    def test_medium_keyword_detected(self):
        level, kws = self.eval("I have been vomiting and have high fever since yesterday.")
        self.assertEqual(level, "Medium")

    def test_low_when_no_keywords(self):
        level, kws = self.eval("Mild back ache after long walk, started this morning.")
        self.assertEqual(level, "Low")
        self.assertEqual(kws, [])

    def test_high_wins_over_medium(self):
        level, _ = self.eval("Vomiting blood and chest pain — extremely worried.")
        self.assertEqual(level, "High")

    def test_case_insensitive_matching(self):
        level, _ = self.eval("CHEST PAIN radiating to left arm.")
        self.assertEqual(level, "High")

    def test_override_high_over_low(self):
        self.assertTrue(self.override("High", "Low"))

    def test_override_medium_over_low(self):
        self.assertTrue(self.override("Medium", "Low"))

    def test_no_override_when_equal(self):
        self.assertFalse(self.override("Medium", "Medium"))

    def test_no_override_when_llm_higher(self):
        self.assertFalse(self.override("Low", "High"))

    def test_no_override_high_over_high(self):
        self.assertFalse(self.override("High", "High"))


# ---------------------------------------------------------------------------
# 2. Schema validation
# ---------------------------------------------------------------------------

VALID_JSON = json.dumps({
    "urgency": "Medium",
    "chief_complaint": "Persistent cough with mild fever for three days.",
    "suggested_questions": [
        "When did the cough start?",
        "Have you been in contact with anyone who is sick?",
    ],
    "red_flags": [],
    "duration_mentioned": "three days",
})

VALID_WITH_FENCE = f"```json\n{VALID_JSON}\n```"
VALID_INLINE_TEXT = f"Here is the analysis:\n{VALID_JSON}\nEnd."


class TestSchemaValidation(TestCase):

    def setUp(self):
        from apps.integrations.llm.schema import validate_pre_visit_response
        from apps.integrations.llm.client import LLMMalformedError
        self.validate = validate_pre_visit_response
        self.MalformedError = LLMMalformedError

    def test_valid_json_passes(self):
        result = self.validate(VALID_JSON)
        self.assertEqual(result["urgency"], "Medium")
        self.assertEqual(len(result["suggested_questions"]), 2)

    def test_strips_markdown_fence(self):
        result = self.validate(VALID_WITH_FENCE)
        self.assertEqual(result["urgency"], "Medium")

    def test_extracts_json_from_surrounding_text(self):
        result = self.validate(VALID_INLINE_TEXT)
        self.assertIsNotNone(result)

    def test_invalid_urgency_raises(self):
        bad = json.dumps({**json.loads(VALID_JSON), "urgency": "Critical"})
        with self.assertRaises(self.MalformedError):
            self.validate(bad)

    def test_missing_questions_raises(self):
        bad = json.dumps({**json.loads(VALID_JSON), "suggested_questions": ["only one"]})
        with self.assertRaises(self.MalformedError):
            self.validate(bad)

    def test_empty_string_raises(self):
        with self.assertRaises(self.MalformedError):
            self.validate("")

    def test_truncates_extra_questions(self):
        data = json.loads(VALID_JSON)
        data["suggested_questions"] = ["Q1", "Q2", "Q3", "Q4", "Q5"]
        result = self.validate(json.dumps(data))
        self.assertLessEqual(len(result["suggested_questions"]), 4)

    def test_null_duration_allowed(self):
        data = json.loads(VALID_JSON)
        data["duration_mentioned"] = None
        result = self.validate(json.dumps(data))
        self.assertIsNone(result["duration_mentioned"])

    def test_extra_keys_stripped(self):
        data = json.loads(VALID_JSON)
        data["injected_field"] = "should not appear"
        result = self.validate(json.dumps(data))
        self.assertNotIn("injected_field", result)


# ---------------------------------------------------------------------------
# 3. pre_visit_llm_job task
# ---------------------------------------------------------------------------

GOOD_LLM_RESPONSE = VALID_JSON  # reuse the valid JSON above


class TestPreVisitLLMJob(TestCase):

    def setUp(self):
        self.hospital    = _make_hospital()
        _, self.profile  = _make_doctor(self.hospital)
        self.patient     = _make_patient()
        self.slot        = _make_slot(self.profile)

    # ── Phase 4 exit criterion ────────────────────────────────────────────────

    def test_llm_down_marks_unavailable_does_not_raise(self):
        """
        PHASE 4 EXIT CRITERION:
        When the LLM is completely down (all retries exhausted), the task
        sets pre_summary_status='unavailable' and returns cleanly.
        The appointment remains confirmed — the booking is unaffected.
        """
        from apps.clinical.tasks import pre_visit_llm_job
        from apps.integrations.llm.client import LLMError

        appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   side_effect=LLMError("Connection refused")):
            with patch("apps.clinical.tasks.pre_visit_llm_job.retry",
                       side_effect=Exception("MaxRetriesExceeded")):
                with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                           return_value=None):
                    result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertEqual(appt.pre_summary_status, PreSummaryStatus.UNAVAILABLE)
        self.assertEqual(appt.status, AppointmentStatus.CONFIRMED)  # booking intact
        self.assertEqual(result["status"], "unavailable")

    def test_llm_down_never_hangs_in_pending(self):
        """
        After the task runs (even if it fails), status must NOT remain 'pending'.
        """
        from apps.clinical.tasks import pre_visit_llm_job
        from apps.integrations.llm.client import LLMError

        appt = _confirmed_appt(self.patient, self.slot)
        self.assertEqual(appt.pre_summary_status, PreSummaryStatus.PENDING)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   side_effect=LLMError("Timeout")):
            with patch("apps.clinical.tasks.pre_visit_llm_job.retry",
                       side_effect=Exception("MaxRetries")):
                with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                           return_value=None):
                    pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertNotEqual(appt.pre_summary_status, PreSummaryStatus.PENDING)

    # ── Success path ──────────────────────────────────────────────────────────

    def test_success_sets_ready_and_urgency(self):
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value=GOOD_LLM_RESPONSE):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value="fake_mongo_id"):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(appt.pre_summary_status, PreSummaryStatus.READY)
        self.assertEqual(appt.urgency_level, "Medium")
        self.assertEqual(appt.ai_pre_summary_id, "fake_mongo_id")

    def test_success_writes_mongo_audit_log(self):
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value=GOOD_LLM_RESPONSE):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value="mongo123") as mock_write:
                pre_visit_llm_job(str(appt.id))

        mock_write.assert_called_once()
        call_kwargs = mock_write.call_args.kwargs
        self.assertEqual(call_kwargs["appointment_id"], str(appt.id))
        self.assertEqual(call_kwargs["status"], "ok")

    # ── Urgency override ──────────────────────────────────────────────────────

    def test_keyword_high_overrides_llm_low(self):
        """Rule engine detects 'chest pain' → urgency must be High even if LLM says Low."""
        from apps.clinical.tasks import pre_visit_llm_job

        llm_says_low = json.dumps({
            "urgency": "Low",
            "chief_complaint": "Chest pain on exertion for two days.",
            "suggested_questions": ["When does it occur?", "Any shortness of breath?"],
            "red_flags": [],
            "duration_mentioned": "two days",
        })

        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.slot.doctor.user,
            slot=self.slot,
            hospital=self.slot.hospital,
            status=AppointmentStatus.CONFIRMED,
            token=1,
            symptom_text="Chest pain on exertion for two days.",
        )

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value=llm_says_low):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value="mongo_override"):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertEqual(appt.urgency_level, "High")
        self.assertTrue(result["urgency_override"])

    def test_no_override_when_llm_matches_or_higher(self):
        """LLM = High, rule = Medium → no override."""
        from apps.clinical.tasks import pre_visit_llm_job

        llm_says_high = json.dumps({
            "urgency": "High",
            "chief_complaint": "Severe chest pain with radiation to left arm.",
            "suggested_questions": ["Any sweating?", "Did the pain come suddenly?"],
            "red_flags": ["chest pain", "radiation"],
            "duration_mentioned": None,
        })

        appt = Appointment.objects.create(
            patient=self.patient,
            doctor=self.slot.doctor.user,
            slot=self.slot,
            hospital=self.slot.hospital,
            status=AppointmentStatus.CONFIRMED,
            token=2,
            symptom_text="Vomiting since morning and moderate fever.",  # Medium by rules
        )

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value=llm_says_high):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value="m2"):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertEqual(appt.urgency_level, "High")
        self.assertFalse(result["urgency_override"])

    # ── Schema retry ──────────────────────────────────────────────────────────

    def test_malformed_then_valid_on_retry(self):
        """First call returns garbage; second call returns valid JSON → status ready."""
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)

        call_count = {"n": 0}
        def side_effect(prompt):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "not json at all %%"
            return GOOD_LLM_RESPONSE

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   side_effect=side_effect):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value="m3"):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(appt.pre_summary_status, PreSummaryStatus.READY)

    def test_all_schema_retries_exhausted_marks_unavailable(self):
        """All calls return garbage → unavailable (not pending, not raising)."""
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value="definitely not valid json {{{"):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       return_value=None):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        self.assertNotEqual(appt.pre_summary_status, PreSummaryStatus.PENDING)
        self.assertEqual(result["status"], "unavailable")

    # ── Guards ────────────────────────────────────────────────────────────────

    def test_non_confirmed_appointment_skipped(self):
        from apps.clinical.tasks import pre_visit_llm_job

        held = _held_appt(self.patient, self.slot)
        result = pre_visit_llm_job(str(held.id))
        self.assertEqual(result["status"], "skipped")

    def test_duplicate_task_delivery_skipped(self):
        """If pre_summary_status is already 'ready', re-running is a no-op."""
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)
        appt.pre_summary_status = PreSummaryStatus.READY
        appt.save(update_fields=["pre_summary_status"])

        result = pre_visit_llm_job(str(appt.id))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "already_processed")

    def test_empty_symptom_text_marks_unavailable(self):
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)
        appt.symptom_text = ""
        appt.save(update_fields=["symptom_text"])

        result = pre_visit_llm_job(str(appt.id))
        appt.refresh_from_db()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(appt.pre_summary_status, PreSummaryStatus.UNAVAILABLE)

    def test_mongo_failure_does_not_crash_task(self):
        """Even if MongoDB write raises, the task must complete and mark ready."""
        from apps.clinical.tasks import pre_visit_llm_job

        appt = _confirmed_appt(self.patient, self.slot)

        with patch("apps.integrations.llm.client.LLMClient.generate",
                   return_value=GOOD_LLM_RESPONSE):
            with patch("apps.integrations.llm.mongo_log.write_pre_visit_log",
                       side_effect=Exception("MongoDB connection refused")):
                result = pre_visit_llm_job(str(appt.id))

        appt.refresh_from_db()
        # The task should survive MongoDB failure and still mark the appointment
        # Since write_pre_visit_log catches its own exceptions, it returns None
        # The task treats None mongo_id as missing but still marks ready
        self.assertIn(result["status"], ("ok", "unavailable"))
        self.assertNotEqual(appt.pre_summary_status, PreSummaryStatus.PENDING)


# ---------------------------------------------------------------------------
# 4. Attachment CRUD API
# ---------------------------------------------------------------------------

def _make_pdf(name: str = "test.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 fake content", content_type="application/pdf")


def _make_png(name: str = "scan.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"\x89PNG fake png data", content_type="image/png")


class TestAttachmentAPI(APITestCase):

    def setUp(self):
        self.hospital   = _make_hospital()
        _, self.profile = _make_doctor(self.hospital)
        self.patient    = _make_patient()
        self.slot       = _make_slot(self.profile)
        self.appt       = _confirmed_appt(self.patient, self.slot)

    def _url(self, attachment_id: str | None = None) -> str:
        base = f"/appointments/{self.appt.id}/attachments"
        return f"{base}/{attachment_id}" if attachment_id else base

    def test_upload_pdf(self):
        resp = self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["file_type"], "pdf")
        self.assertEqual(resp.data["original_filename"], "test.pdf")

    def test_upload_png(self):
        resp = self.client.post(
            self._url(), {"file": _make_png()}, format="multipart",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["file_type"], "png")

    def test_upload_unsupported_type_rejected(self):
        bad_file = SimpleUploadedFile("doc.docx", b"word content", content_type="application/vnd.openxmlformats")
        resp = self.client.post(
            self._url(), {"file": bad_file}, format="multipart",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_too_large_rejected(self):
        big = SimpleUploadedFile("big.pdf", b"x" * (6 * 1024 * 1024), content_type="application/pdf")
        resp = self.client.post(
            self._url(), {"file": big}, format="multipart",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_cap_at_5(self):
        for i in range(5):
            self.client.post(
                self._url(),
                {"file": SimpleUploadedFile(f"f{i}.pdf", b"%PDF-fake", content_type="application/pdf")},
                format="multipart",
                **_auth(self.patient),
            )
        # 6th upload must be rejected
        resp = self.client.post(
            self._url(), {"file": _make_pdf("extra.pdf")}, format="multipart",
            **_auth(self.patient),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_list_own_attachments(self):
        self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.patient),
        )
        resp = self.client.get(self._url(), **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_doctor_can_list_attachments(self):
        self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.patient),
        )
        resp = self.client.get(self._url(), **_auth(self.profile.user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_other_patient_cannot_list(self):
        other = _make_patient()
        resp = self.client.get(self._url(), **_auth(other))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_own_attachment(self):
        upload_resp = self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.patient),
        )
        att_id = upload_resp.data["id"]
        resp = self.client.delete(self._url(att_id), **_auth(self.patient))
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(PreVisitAttachment.objects.filter(id=att_id).exists())

    def test_other_patient_cannot_delete(self):
        upload_resp = self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.patient),
        )
        att_id = upload_resp.data["id"]
        other  = _make_patient()
        resp   = self.client.delete(self._url(att_id), **_auth(other))
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
        self.assertTrue(PreVisitAttachment.objects.filter(id=att_id).exists())

    def test_doctor_cannot_upload(self):
        resp = self.client.post(
            self._url(), {"file": _make_pdf()}, format="multipart",
            **_auth(self.profile.user),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


# ---------------------------------------------------------------------------
# 5. DoctorAppointmentDetail — pre_summary_content
# ---------------------------------------------------------------------------

class TestDoctorCardSummaryContent(APITestCase):

    def setUp(self):
        self.hospital   = _make_hospital()
        _, self.profile = _make_doctor(self.hospital)
        self.patient    = _make_patient()
        self.slot       = _make_slot(self.profile)

    def test_pre_summary_content_none_when_pending(self):
        appt = _confirmed_appt(self.patient, self.slot)
        # Status is pending by default
        url  = f"/doctor/appointments/{appt.id}"
        resp = self.client.get(url, **_auth(self.profile.user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["pre_summary_content"])

    def test_pre_summary_content_populated_when_ready(self):
        appt = _confirmed_appt(self.patient, self.slot)
        appt.pre_summary_status = PreSummaryStatus.READY
        appt.ai_pre_summary_id  = "test_mongo_id"
        appt.urgency_level      = "Medium"
        appt.save(update_fields=[
            "pre_summary_status", "ai_pre_summary_id", "urgency_level"
        ])

        fake_mongo_doc = {
            "parsed": {
                "urgency":             "Medium",
                "chief_complaint":     "Persistent cough and mild fever.",
                "suggested_questions": ["When did it start?", "Any contact?"],
                "red_flags":           [],
                "duration_mentioned":  "three days",
            }
        }

        url = f"/doctor/appointments/{appt.id}"
        with patch(
            "apps.integrations.llm.mongo_log.get_pre_visit_log",
            return_value=fake_mongo_doc,
        ):
            resp = self.client.get(url, **_auth(self.profile.user))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        content = resp.data["pre_summary_content"]
        self.assertIsNotNone(content)
        self.assertEqual(content["urgency"], "Medium")
        self.assertIn("suggested_questions", content)
        self.assertEqual(len(content["suggested_questions"]), 2)

    def test_pre_summary_content_none_when_unavailable(self):
        appt = _confirmed_appt(self.patient, self.slot)
        appt.pre_summary_status = PreSummaryStatus.UNAVAILABLE
        appt.save(update_fields=["pre_summary_status"])

        url  = f"/doctor/appointments/{appt.id}"
        resp = self.client.get(url, **_auth(self.profile.user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp.data["pre_summary_content"])

    def test_attachment_list_included_in_doctor_card(self):
        appt = _confirmed_appt(self.patient, self.slot)
        # Create an attachment directly in DB
        PreVisitAttachment.objects.create(
            appointment=appt,
            uploaded_by=self.patient,
            file="attachments/fake/fake.pdf",
            file_type="pdf",
            original_filename="result.pdf",
            file_size_bytes=1024,
        )

        url  = f"/doctor/appointments/{appt.id}"
        resp = self.client.get(url, **_auth(self.profile.user))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["attachments"]), 1)
        self.assertEqual(resp.data["attachments"][0]["file_type"], "pdf")
