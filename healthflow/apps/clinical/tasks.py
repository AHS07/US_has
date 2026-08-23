"""
clinical/tasks.py

Phase 4: pre_visit_llm_job

Pipeline per confirmed appointment:
  1. Run keyword urgency rules (always, never skipped)
  2. Call LLM with locked pre-visit prompt
  3. Validate JSON schema (retry-on-malformed, up to 2 extra attempts)
  4. If rule urgency > LLM urgency → override
  5. Write audit log to MongoDB (best-effort, never blocks)
  6. Update Appointment: urgency_level, ai_pre_summary_id, pre_summary_status

On ANY unrecoverable failure (LLM down, all retries exhausted, schema invalid
after all retries) → pre_summary_status = "unavailable".
The booking is NEVER affected — this task runs after confirm() returns.

Exit criterion (phases.md Phase 4):
  "Killing the LLM connection mid-test still lets a booking confirm
   successfully and eventually surfaces 'unavailable' on the doctor's card
   rather than hanging in 'pending' forever."
"""
from __future__ import annotations

import logging
import time

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="clinical.pre_visit_llm_job",
    # acks_late=True so a worker crash does not silently drop the job
    acks_late=True,
)
def pre_visit_llm_job(self, appointment_id: str) -> dict:
    """
    Run the pre-visit AI summary pipeline for one confirmed appointment.

    Returns a summary dict suitable for logging / admin inspection.
    Never raises — any unhandled exception sets status to unavailable.
    """
    from apps.clinical.models import Appointment, PreSummaryStatus
    from apps.integrations.llm.client import LLMError, LLMMalformedError, get_client
    from apps.integrations.llm.mongo_log import write_pre_visit_log
    from apps.integrations.llm.prompts import build_pre_visit_prompt
    from apps.integrations.llm.schema import validate_pre_visit_response_with_retry
    from apps.integrations.llm.urgency import evaluate_urgency, should_override_llm

    # ── 1. Load appointment ──────────────────────────────────────────────────
    try:
        appointment = Appointment.objects.get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error("pre_visit_llm_job: appointment %s not found", appointment_id)
        return {"status": "error", "detail": "Appointment not found."}

    # Guard: only process confirmed appointments
    if appointment.status != "confirmed":
        logger.warning(
            "pre_visit_llm_job: appointment %s is not confirmed (status=%s) — skipping",
            appointment_id, appointment.status,
        )
        return {"status": "skipped", "reason": "not_confirmed"}

    # Guard: already processed (e.g. duplicate task delivery)
    if appointment.pre_summary_status != PreSummaryStatus.PENDING:
        logger.info(
            "pre_visit_llm_job: appointment %s already has status=%s — skipping",
            appointment_id, appointment.pre_summary_status,
        )
        return {"status": "skipped", "reason": "already_processed"}

    symptom_text = appointment.symptom_text.strip()
    if not symptom_text:
        _mark_unavailable(appointment, "No symptom text.")
        return {"status": "unavailable", "reason": "empty_symptom_text"}

    # ── 2. Keyword urgency rules (always runs, never skipped) ────────────────
    rule_urgency, matched_keywords = evaluate_urgency(symptom_text)

    # ── 3. LLM call ──────────────────────────────────────────────────────────
    prompt      = build_pre_visit_prompt(symptom_text)
    client      = get_client()
    raw_text    = ""
    parsed      = None
    llm_status  = "llm_error"
    error_detail: str | None = None
    duration_ms = 0

    try:
        t0       = time.monotonic()
        raw_text = client.generate(prompt)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # ── 4. Schema validation (with retry-on-malformed) ───────────────────
        parsed     = validate_pre_visit_response_with_retry(raw_text, client, prompt)
        llm_status = "ok"

    except LLMMalformedError as exc:
        error_detail = str(exc)
        logger.warning(
            "pre_visit_llm_job: malformed response for %s after retries: %s",
            appointment_id, exc,
        )
    except LLMError as exc:
        error_detail = str(exc)
        logger.error(
            "pre_visit_llm_job: LLM failure for %s: %s",
            appointment_id, exc,
        )
        # Retry the Celery task (not the LLM call — that already retried internally)
        try:
            raise self.retry(exc=exc)
        except (self.MaxRetriesExceededError, Exception):
            logger.error(
                "pre_visit_llm_job: max retries exceeded for %s — marking unavailable",
                appointment_id,
            )
    except Exception as exc:
        error_detail = str(exc)
        logger.exception(
            "pre_visit_llm_job: unexpected error for %s: %s",
            appointment_id, exc,
        )

    # ── 5. Urgency override ──────────────────────────────────────────────────
    llm_urgency      = (parsed or {}).get("urgency", "Low")
    urgency_override = False
    final_urgency    = llm_urgency

    if parsed and should_override_llm(rule_urgency, llm_urgency):
        parsed["urgency"] = rule_urgency
        final_urgency     = rule_urgency
        urgency_override  = True
        logger.info(
            "pre_visit_llm_job: urgency override for %s: LLM=%s -> rule=%s (keywords=%s)",
            appointment_id, llm_urgency, rule_urgency, matched_keywords,
        )

    # ── 6. MongoDB audit log (best-effort) ───────────────────────────────────
    mongo_id = None
    try:
        mongo_id = write_pre_visit_log(
            appointment_id   = appointment_id,
            prompt           = prompt,
            raw_response     = raw_text,
            parsed           = parsed,
            urgency_rule     = rule_urgency,
            urgency_override = urgency_override,
            final_urgency    = final_urgency if parsed else None,
            status           = llm_status,
            error_detail     = error_detail,
            duration_ms      = duration_ms,
        )
    except Exception as mongo_exc:
        logger.error("pre_visit_llm_job: mongo write failed for %s: %s", appointment_id, mongo_exc)

    # ── 7. Update Appointment ────────────────────────────────────────────────
    if parsed:
        appointment.urgency_level      = final_urgency
        appointment.ai_pre_summary_id  = mongo_id or ""
        appointment.pre_summary_status = PreSummaryStatus.READY
        appointment.save(update_fields=[
            "urgency_level", "ai_pre_summary_id", "pre_summary_status", "updated_at"
        ])
        logger.info(
            "pre_visit_llm_job: OK for %s (urgency=%s override=%s)",
            appointment_id, final_urgency, urgency_override,
        )
        return {
            "status":           "ok",
            "urgency":          final_urgency,
            "urgency_override": urgency_override,
            "mongo_id":         mongo_id,
        }

    # LLM failed or schema invalid — mark unavailable
    # Rule-based urgency is still stored so the doctor sees *something*
    appointment.urgency_level      = rule_urgency  # at minimum the keyword result
    appointment.pre_summary_status = PreSummaryStatus.UNAVAILABLE
    appointment.save(update_fields=[
        "urgency_level", "pre_summary_status", "updated_at"
    ])
    logger.warning(
        "pre_visit_llm_job: marked unavailable for %s (rule_urgency=%s)",
        appointment_id, rule_urgency,
    )
    return {
        "status":        "unavailable",
        "rule_urgency":  rule_urgency,
        "error_detail":  error_detail,
    }


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _mark_unavailable(appointment, reason: str) -> None:
    """Set pre_summary_status = unavailable without touching urgency."""
    from apps.clinical.models import PreSummaryStatus
    appointment.pre_summary_status = PreSummaryStatus.UNAVAILABLE
    appointment.save(update_fields=["pre_summary_status", "updated_at"])
    logger.warning(
        "pre_visit_llm_job: unavailable for appointment %s — %s",
        appointment.id, reason,
    )


# ---------------------------------------------------------------------------
# Phase 5 — post_visit_llm_job
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="clinical.post_visit_llm_job",
    acks_late=True,
)
def post_visit_llm_job(self, appointment_id: str) -> dict:
    """
    Run the post-visit AI summary pipeline for one completed appointment.

    Pipeline:
      1. Load appointment, visit_note, prescriptions
      2. Build prompt from notes + structured rx rows (NO free-text medicine names)
      3. LLM call + schema validation
      4. Write audit log to MongoDB
      5. Update Appointment: post_summary_id, summary_status = draft

    Phase 5 exit criterion:
      Adversarial text in visit_notes cannot inject a medicine not in
      prescription_rows — the prompt builder only sends structured FK rows.
      The schema validator strips any medications key mismatch.

    On failure → summary_status = unavailable (raw notes still available to doctor).
    """
    from apps.clinical.models import Appointment, Prescription, SummaryStatus
    from apps.integrations.llm.client import LLMError, LLMMalformedError, get_client
    from apps.integrations.llm.prompts import build_post_visit_prompt
    from apps.integrations.llm.mongo_log import write_pre_visit_log  # reused for post-visit

    # ── Load appointment ─────────────────────────────────────────────────────
    try:
        appointment = Appointment.objects.select_related(
            "visit_note"
        ).prefetch_related("prescriptions__medicine").get(id=appointment_id)
    except Appointment.DoesNotExist:
        logger.error("post_visit_llm_job: appointment %s not found", appointment_id)
        return {"status": "error", "detail": "Appointment not found."}

    if appointment.status != "completed":
        logger.warning(
            "post_visit_llm_job: appointment %s is not completed (status=%s) — skipping",
            appointment_id, appointment.status,
        )
        return {"status": "skipped", "reason": "not_completed"}

    if appointment.summary_status not in (SummaryStatus.PENDING, SummaryStatus.UNAVAILABLE):
        return {"status": "skipped", "reason": "already_processed"}

    # ── Check visit note exists ──────────────────────────────────────────────
    try:
        visit_note = appointment.visit_note
    except Exception:
        _mark_summary_unavailable(appointment)
        return {"status": "unavailable", "reason": "no_visit_note"}

    # ── Build structured prescription rows from FK-resolved data only ────────
    prescription_rows = [
        {
            "name":         rx.medicine.name,
            "dosage":       rx.dosage,
            "frequency":    rx.get_frequency_display(),
            "duration":     rx.duration,
            "instructions": rx.instructions,
        }
        for rx in appointment.prescriptions.select_related("medicine").order_by("sort_order")
    ]

    prompt      = build_post_visit_prompt(
        visit_note.notes, prescription_rows, appointment.follow_up_days
    )
    client      = get_client()
    raw_text    = ""
    parsed      = None
    llm_status  = "llm_error"
    error_detail: str | None = None
    duration_ms = 0

    try:
        t0       = time.monotonic()
        raw_text = client.generate(prompt)
        duration_ms = int((time.monotonic() - t0) * 1000)

        parsed = _validate_post_visit(raw_text, prescription_rows)
        llm_status = "ok"

    except _PostVisitMalformed as exc:
        error_detail = str(exc)
        logger.warning("post_visit_llm_job: malformed for %s: %s", appointment_id, exc)
    except LLMError as exc:
        error_detail = str(exc)
        try:
            raise self.retry(exc=exc)
        except (self.MaxRetriesExceededError, Exception):
            logger.error("post_visit_llm_job: max retries for %s", appointment_id)
    except Exception as exc:
        error_detail = str(exc)
        logger.exception("post_visit_llm_job: unexpected error for %s", appointment_id)

    # ── Audit log ────────────────────────────────────────────────────────────
    mongo_id = None
    try:
        mongo_id = write_pre_visit_log(
            appointment_id   = appointment_id,
            prompt           = prompt,
            raw_response     = raw_text,
            parsed           = parsed,
            urgency_rule     = "",
            urgency_override = False,
            final_urgency    = None,
            status           = llm_status,
            error_detail     = error_detail,
            duration_ms      = duration_ms,
        )
    except Exception as mongo_exc:
        logger.error("post_visit_llm_job: mongo write failed for %s: %s", appointment_id, mongo_exc)

    # ── Update appointment ───────────────────────────────────────────────────
    if parsed:
        appointment.post_summary_id  = mongo_id or ""
        appointment.summary_status   = SummaryStatus.DRAFT
        appointment.save(update_fields=["post_summary_id", "summary_status", "updated_at"])
        logger.info("post_visit_llm_job: draft ready for %s", appointment_id)
        return {"status": "draft", "mongo_id": mongo_id}

    _mark_summary_unavailable(appointment)
    return {"status": "unavailable", "error_detail": error_detail}


def _mark_summary_unavailable(appointment) -> None:
    from apps.clinical.models import SummaryStatus
    appointment.summary_status = SummaryStatus.UNAVAILABLE
    appointment.save(update_fields=["summary_status", "updated_at"])


class _PostVisitMalformed(Exception):
    pass


def _validate_post_visit(raw: str, prescription_rows: list[dict]) -> dict:
    """
    Validate post-visit LLM JSON output.

    Key Phase 5 security check: the medications list in the response MUST
    contain only medicines whose names appear in prescription_rows.
    Any extra medicine name → raise _PostVisitMalformed (adversarial injection guard).
    """
    import json, re

    # Extract JSON (handles markdown fences)
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    data = None
    for candidate in [cleaned, re.search(r"\{.*\}", cleaned, re.DOTALL)]:
        if candidate is None:
            continue
        text = candidate if isinstance(candidate, str) else candidate.group(0)
        try:
            data = json.loads(text)
            break
        except json.JSONDecodeError:
            pass

    if data is None:
        raise _PostVisitMalformed(f"No valid JSON found in: {raw[:200]!r}")

    # Require summary_text
    if not isinstance(data.get("summary_text"), str) or not data["summary_text"].strip():
        raise _PostVisitMalformed("summary_text missing or empty")

    # Medication injection guard — the ONLY security-critical check in Phase 5
    allowed_names = {row["name"].lower().strip() for row in prescription_rows}
    returned_meds = data.get("medications", [])
    if not isinstance(returned_meds, list):
        raise _PostVisitMalformed("medications must be a list")

    for med in returned_meds:
        med_name = str(med.get("name", "")).lower().strip()
        if med_name and med_name not in allowed_names:
            raise _PostVisitMalformed(
                f"Medication injection detected: '{med['name']}' not in prescription rows. "
                f"Allowed: {sorted(allowed_names)}"
            )

    return {
        "summary_text":  data["summary_text"].strip(),
        "medications":   prescription_rows,  # use canonical DB rows, not LLM output
        "follow_up_note": data.get("follow_up_note"),
    }
