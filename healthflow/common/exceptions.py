"""
Centralized DRF exception handler.

All API error responses pass through here so the shape is consistent:
    {
        "error": {
            "code": "validation_error",
            "message": "Human-readable summary",
            "detail": { ... }   # only for validation errors; omitted otherwise
        }
    }

Never expose raw exception messages, stack traces, or internal identifiers
in the response — log the detail server-side, return a generic message to
the client.
"""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def healthflow_exception_handler(exc, context):
    """Custom exception handler that wraps DRF responses in a consistent shape."""
    response = exception_handler(exc, context)

    if response is not None:
        error_payload: dict = {
            "error": {
                "code": _get_code(response),
                "message": _get_message(response),
            }
        }
        # Include field-level detail only for validation (400) errors
        if response.status_code == status.HTTP_400_BAD_REQUEST:
            error_payload["error"]["detail"] = response.data

        response.data = error_payload

    return response


def _get_code(response: Response) -> str:
    if isinstance(response.data, dict):
        code = response.data.get("code") or response.data.get("detail", {})
        if hasattr(code, "code"):
            return str(code.code)
    return f"http_{response.status_code}"


def _get_message(response: Response) -> str:
    if isinstance(response.data, dict):
        detail = response.data.get("detail")
        if detail:
            return str(detail)
    return _default_message(response.status_code)


def _default_message(status_code: int) -> str:
    messages = {
        400: "Invalid request data.",
        401: "Authentication required.",
        403: "You do not have permission to perform this action.",
        404: "The requested resource was not found.",
        405: "Method not allowed.",
        429: "Too many requests.",
        500: "An unexpected error occurred.",
    }
    return messages.get(status_code, "An error occurred.")
