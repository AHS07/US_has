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
        logger.error("llm_audit_log write failed for appointment %s: %s", appointment_id, exc)
        return None


# ---------------------------------------------------------------------------
# Read helpers (used by Phase 5 approval gate)
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
            "llm_audit_log read failed for appointment %s: %s", appointment_id, exc
        )
        return None
