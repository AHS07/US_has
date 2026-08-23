"""
LLM audit log write helper.

Every LLM generation that could reach a patient is logged immutably here.
Rows in llm_audit_log are never mutated after creation.

Usage:
    from common.audit import write_llm_audit
    write_llm_audit(
        appointment_id=appt.id,
        stage="pre_visit",
        raw_input="...",
        llm_output="...",
    )
"""
from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def write_llm_audit(
    appointment_id: UUID | str,
    stage: str,
    raw_input: str,
    llm_output: str,
    approved_by: UUID | str | None = None,
) -> None:
    """Write an immutable audit log entry for an LLM generation.

    Import the model lazily to avoid circular imports at module load time.
    """
    # Deferred import — models are not available until Django is fully set up
    from apps.clinical.models import LLMAuditLog  # noqa: PLC0415

    LLMAuditLog.objects.create(
        appointment_id=appointment_id,
        stage=stage,
        raw_input=raw_input,
        llm_output=llm_output,
        approved_by_id=approved_by,
    )
    logger.info(
        "LLM audit log written: appointment=%s stage=%s",
        appointment_id,
        stage,
    )
