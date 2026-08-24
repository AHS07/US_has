"""
integrations/llm/mongo_log.py

MongoDB audit log for every LLM call.

Collection: llm_audit_log
Every prompt + response pair is written here, regardless of success or failure.
Records are never deleted — they are the audit trail required by Phase 5 approval gating.

Document shape:
    {
        "_id":              ObjectId,
        "appointment_id":   str (UUID),
        "call_type":        "pre_visit" | "post_visit",
        "prompt":           str,                # full prompt sent
        "raw_response":     str,                # raw text from LLM
        "parsed":           dict | None,        # validated output or null
        "urgency_rule":     str | None,         # rule-engine urgency before LLM
        "urgency_override": bool,               # True if rule overrode LLM
        "final_urgency":    str | None,         # urgency written to Appointment
        "status":           "ok" | "malformed" | "llm_error",
        "error_detail":     str | None,
        "duration_ms":      int,                # wall-clock ms for the LLM call
        "model":            str,                # settings.LLM_MODEL at call time
        "backend":          str,                # settings.LLM_BACKEND
        "created_at":       datetime (UTC),
    }
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

import pymongo
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_mongo_client: pymongo.MongoClient | None = None


def _get_collection() -> pymongo.collection.Collection:
    global _mongo_client
    if _mongo_client is None:
        uri  = getattr(settings, "MONGO_URI",     "mongodb://mongo:27017")
        name = getattr(settings, "MONGO_DB_NAME", "healthflow")
        _mongo_client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
    db = _mongo_client[getattr(settings, "MONGO_DB_NAME", "healthflow")]
    return db["llm_audit_log"]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_pre_visit_log(
    *,
    appointment_id: str,
    prompt: str,
    raw_response: str,
    parsed: dict[str, Any] | None,
    urgency_rule: str,
    urgency_override: bool,
    final_urgency: str | None,
    status: str,             # "ok" | "malformed" | "llm_error"
    error_detail: str | None = None,
    duration_ms: int = 0,
) -> str | None:
    """
    Write a pre-visit audit log entry to MongoDB.

    Returns the inserted document _id as a string, or None on failure.
    Failure is logged but never raises — the booking flow must not be
    blocked by a MongoDB outage.
    """
    doc = {
        "appointment_id":   appointment_id,
        "call_type":        "pre_visit",
        "prompt":           prompt,
        "raw_response":     raw_response,
        "parsed":           parsed,
        "urgency_rule":     urgency_rule,
        "urgency_override": urgency_override,
        "final_urgency":    final_urgency,
        "status":           status,
        "error_detail":     error_detail,
        "duration_ms":      duration_ms,
        "model":            getattr(settings, "LLM_MODEL",   "unknown"),
        "backend":          getattr(settings, "LLM_BACKEND", "huggingface"),
        "created_at":       datetime.datetime.utcnow(),
    }
    try:
        result = _get_collection().insert_one(doc)
        return str(result.inserted_id)
    except Exception as exc:
        logger.error("llm_audit_log write failed for appointment %s (pre_visit): %s", appointment_id, exc)
        return None


def write_post_visit_log(
    *,
    appointment_id: str,
    prompt: str,
    raw_response: str,
    parsed: dict[str, Any] | None,
    status: str,             # "ok" | "malformed" | "llm_error"
    error_detail: str | None = None,
    duration_ms: int = 0,
) -> str | None:
    """
    Write a post-visit audit log entry to MongoDB.

    Returns the inserted document _id as a string, or None on failure.
    Preserves audit separation from pre_visit records.
    """
    doc = {
        "appointment_id":   appointment_id,
        "call_type":        "post_visit",
        "prompt":           prompt,
        "raw_response":     raw_response,
        "parsed":           parsed,
        "status":           status,
        "error_detail":     error_detail,
        "duration_ms":      duration_ms,
        "model":            getattr(settings, "LLM_MODEL",   "unknown"),
        "backend":          getattr(settings, "LLM_BACKEND", "huggingface"),
        "created_at":       datetime.datetime.utcnow(),
    }
    try:
        result = _get_collection().insert_one(doc)
        return str(result.inserted_id)
    except Exception as exc:
        logger.error("llm_audit_log write failed for appointment %s (post_visit): %s", appointment_id, exc)
        return None


# ---------------------------------------------------------------------------
# Read & Update helpers (used by Phase 5 approval gate & summary views)
# ---------------------------------------------------------------------------

def get_pre_visit_log(appointment_id: str) -> dict[str, Any] | None:
    """
    Return the most recent successful pre-visit log for the appointment,
    or None if not found.
    """
    try:
        return _get_collection().find_one(
            {"appointment_id": appointment_id, "call_type": "pre_visit", "status": "ok"},
            sort=[("created_at", pymongo.DESCENDING)],
        )
    except Exception as exc:
        logger.error(
            "llm_audit_log read failed for appointment %s (pre_visit): %s", appointment_id, exc
        )
        return None


def log_doctor_summary_approval(
    *,
    appointment_id: str,
    summary_text: str,
    doctor_id: str | None = None,
    follow_up_note: str | None = None,
) -> str | None:
    """
    Write an immutable doctor approval/edit audit record to MongoDB.
    Does NOT mutate the original LLM generation document.
    """
    doc = {
        "appointment_id": appointment_id,
        "call_type":      "doctor_approval",
        "summary_text":   summary_text,
        "follow_up_note": follow_up_note,
        "approved_by_id": str(doctor_id) if doctor_id else None,
        "status":         "ok",
        "created_at":     datetime.datetime.utcnow(),
    }
    try:
        result = _get_collection().insert_one(doc)
        return str(result.inserted_id)
    except Exception as exc:
        logger.error(
            "log_doctor_summary_approval write failed for appointment %s: %s",
            appointment_id, exc,
        )
        return None


def get_post_visit_log(appointment_id: str) -> dict[str, Any] | None:
    """
    Return the most recent post-visit summary for the appointment.
    Checks doctor approval audit events first, falling back to the raw LLM draft.
    """
    try:
        # Check for doctor approved/edited document first
        approved_doc = _get_collection().find_one(
            {"appointment_id": appointment_id, "call_type": "doctor_approval", "status": "ok"},
            sort=[("created_at", pymongo.DESCENDING)],
        )
        if approved_doc:
            return {
                "_id": approved_doc.get("_id"),
                "appointment_id": appointment_id,
                "call_type": "doctor_approval",
                "parsed": {
                    "summary_text":   approved_doc.get("summary_text", ""),
                    "follow_up_note": approved_doc.get("follow_up_note"),
                },
                "status": "ok",
            }

        # Fallback to LLM post_visit draft document
        return _get_collection().find_one(
            {"appointment_id": appointment_id, "call_type": "post_visit", "status": "ok"},
            sort=[("created_at", pymongo.DESCENDING)],
        )
    except Exception as exc:
        logger.error(
            "llm_audit_log read failed for appointment %s (post_visit): %s", appointment_id, exc
        )
        return None


def update_post_visit_summary(appointment_id: str, edited_text: str, doctor_id: str | None = None) -> bool:
    """
    Backward-compatible wrapper that creates an immutable doctor approval audit log.
    """
    inserted_id = log_doctor_summary_approval(
        appointment_id=appointment_id,
        summary_text=edited_text,
        doctor_id=doctor_id,
    )
    return inserted_id is not None
