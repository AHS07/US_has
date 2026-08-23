"""
integrations/llm/schema.py

Enforced JSON schema for LLM output + validator with retry-on-malformed.

Rules:
  - Raw LLM text is never passed through to the app layer.
  - validate_pre_visit_response() either returns a clean typed dict
    or raises LLMMalformedError so the caller can retry or fall back.
  - The schema is minimal-but-strict: exact keys, correct types, allowed values.
    Extra keys are stripped so the model cannot inject unexpected fields.
"""
from __future__ import annotations

import json
import re
from typing import Any

from apps.integrations.llm.client import LLMMalformedError

# ---------------------------------------------------------------------------
# Pre-visit expected schema
# ---------------------------------------------------------------------------

_ALLOWED_URGENCY   = {"Low", "Medium", "High"}
_MIN_QUESTIONS     = 2
_MAX_QUESTIONS     = 4
_MAX_COMPLAINT_LEN = 200   # generous upper bound after the 20-word guidance


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    """
    Parse JSON from the LLM output. Handles two common failure modes:

    1. Model wraps the JSON in a markdown code block (```json … ```)
    2. Model emits text before/after the JSON object

    Raises LLMMalformedError if no valid JSON object can be found.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back: find the first {...} block
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise LLMMalformedError(
        f"Could not extract a JSON object from LLM output. "
        f"Raw (first 200 chars): {raw[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def validate_pre_visit_response(raw: str) -> dict[str, Any]:
    """
    Parse and validate the pre-visit LLM response.

    Returns a clean dict:
        {
            "urgency":             "Low" | "Medium" | "High",
            "chief_complaint":     str,
            "suggested_questions": [str, str, ...],   # 2–4 items
            "red_flags":           [str, ...],         # may be empty
            "duration_mentioned":  str | None,
        }

    Raises LLMMalformedError with a descriptive message on any violation.
    Extra keys in the model output are silently dropped.
    """
    data = _extract_json(raw)

    errors: list[str] = []

    # urgency
    urgency = data.get("urgency")
    if urgency not in _ALLOWED_URGENCY:
        errors.append(
            f"urgency must be one of {_ALLOWED_URGENCY}, got {urgency!r}"
        )

    # chief_complaint
    complaint = data.get("chief_complaint")
    if not isinstance(complaint, str) or not complaint.strip():
        errors.append("chief_complaint must be a non-empty string")
    elif len(complaint) > _MAX_COMPLAINT_LEN:
        # Truncate rather than reject — we don't want one long sentence
        # to poison the whole response
        data["chief_complaint"] = complaint[:_MAX_COMPLAINT_LEN]

    # suggested_questions
    questions = data.get("suggested_questions")
    if not isinstance(questions, list):
        errors.append("suggested_questions must be a list")
    else:
        questions = [str(q).strip() for q in questions if str(q).strip()]
        if len(questions) < _MIN_QUESTIONS:
            errors.append(
                f"suggested_questions must have at least {_MIN_QUESTIONS} items, "
                f"got {len(questions)}"
            )
        data["suggested_questions"] = questions[:_MAX_QUESTIONS]

    # red_flags — optional, default to []
    red_flags = data.get("red_flags", [])
    if not isinstance(red_flags, list):
        red_flags = []
    data["red_flags"] = [str(f).strip() for f in red_flags if str(f).strip()]

    # duration_mentioned — optional, can be None
    duration = data.get("duration_mentioned")
    if duration is not None and not isinstance(duration, str):
        duration = str(duration)
    data["duration_mentioned"] = duration if duration else None

    if errors:
        raise LLMMalformedError(
            f"Pre-visit response validation failed: {'; '.join(errors)}. "
            f"Raw (first 300 chars): {raw[:300]!r}"
        )

    # Return only the expected keys — strip model noise
    return {
        "urgency":             data["urgency"],
        "chief_complaint":     data["chief_complaint"].strip(),
        "suggested_questions": data["suggested_questions"],
        "red_flags":           data["red_flags"],
        "duration_mentioned":  data["duration_mentioned"],
    }


def validate_pre_visit_response_with_retry(
    raw: str,
    client,
    prompt: str,
    max_schema_retries: int = 2,
) -> dict[str, Any]:
    """
    Attempt to validate; if validation fails, re-call the LLM with the
    original prompt up to max_schema_retries additional times.

    This handles the common case where the model emits valid JSON but with
    a missing or wrong field on the first attempt.

    Raises LLMMalformedError if all retries are exhausted.
    """
    from apps.integrations.llm.client import LLMError

    last_exc: LLMMalformedError | None = None

    # First: try the already-fetched raw text
    try:
        return validate_pre_visit_response(raw)
    except LLMMalformedError as exc:
        last_exc = exc

    # Re-call the LLM
    for attempt in range(1, max_schema_retries + 1):
        try:
            new_raw = client.generate(prompt)
            return validate_pre_visit_response(new_raw)
        except LLMMalformedError as exc:
            last_exc = exc
        except LLMError as exc:
            raise LLMMalformedError(
                f"LLM failed on schema retry {attempt}: {exc}"
            ) from exc

    raise LLMMalformedError(
        f"LLM output did not match schema after {max_schema_retries + 1} attempts. "
        f"Last error: {last_exc}"
    ) from last_exc
