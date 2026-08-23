"""
integrations/llm/client.py

The ONLY place an LLM API call is made in the entire codebase.
Never call the LLM API directly from a view, model method, or ad hoc script.

Interface is model-agnostic: settings determine the backend.
Currently backed by HuggingFace Inference API (text-generation endpoint).
When OpenAI / Azure OpenAI becomes available again, only this file and
settings change — no view, task, or prompt changes needed.

Backend selection (settings.LLM_BACKEND):
  "huggingface"  — HuggingFace Inference API (default, current)
  "openai"       — OpenAI / Azure OpenAI (stub, uncomment when ready)
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Raised when the LLM call fails after all retries."""


class LLMMalformedError(LLMError):
    """Raised when the LLM returns output that does not match the schema."""


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _call_huggingface(prompt: str, max_new_tokens: int) -> str:
    """
    POST to HuggingFace Inference API.

    Endpoint: POST https://api-inference.huggingface.co/models/{MODEL}
    Auth:     Bearer {LLM_API_KEY}
    Response: [{"generated_text": "..."}]  (list, first element)
    """
    model    = getattr(settings, "LLM_MODEL", "mistralai/Mistral-7B-Instruct-v0.2")
    api_key  = getattr(settings, "LLM_API_KEY", "")
    base_url = getattr(
        settings, "LLM_API_BASE",
        "https://api-inference.huggingface.co/models"
    )
    url      = f"{base_url.rstrip('/')}/{model}"
    timeout  = getattr(settings, "LLM_TIMEOUT_SECONDS", 30)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "inputs":      prompt,
        "parameters": {
            "max_new_tokens":    max_new_tokens,
            "return_full_text":  False,
            "temperature":       0.2,    # low — we want consistent structured output
            "do_sample":         True,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()

    data = resp.json()
    # HuggingFace returns a list: [{"generated_text": "..."}]
    if isinstance(data, list) and data:
        return data[0].get("generated_text", "")
    # Some models return {"generated_text": "..."}  directly
    if isinstance(data, dict):
        return data.get("generated_text", "")
    raise LLMError(f"Unexpected HuggingFace response shape: {type(data)}")


def _call_openai(prompt: str, max_new_tokens: int) -> str:
    """
    Stub for OpenAI / Azure OpenAI.
    Uncomment and wire when the endpoint is available.
    """
    raise LLMError(
        "OpenAI backend not active. Set LLM_BACKEND=huggingface in settings "
        "or configure the OpenAI client here."
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class LLMClient:
    """
    Model-agnostic LLM client.

    Usage:
        client = LLMClient()
        text   = client.generate(prompt)   # raises LLMError on all-retry failure

    Retries up to max_retries times with exponential backoff.
    Each attempt is logged with timing for the audit trail.
    """

    def __init__(
        self,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        max_new_tokens: int = 512,
    ) -> None:
        self.max_retries    = max_retries
        self.backoff_base   = backoff_base
        self.max_new_tokens = max_new_tokens
        self.backend        = getattr(settings, "LLM_BACKEND", "huggingface")

    def generate(self, prompt: str) -> str:
        """
        Call the LLM and return the generated text string.
        Raises LLMError after max_retries failed attempts.
        """
        last_exc: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                t0     = time.monotonic()
                result = self._dispatch(prompt)
                elapsed = time.monotonic() - t0
                logger.info(
                    "LLM call succeeded (backend=%s attempt=%d elapsed=%.2fs)",
                    self.backend, attempt, elapsed,
                )
                return result.strip()
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                logger.warning("LLM timeout (attempt %d/%d)", attempt, self.max_retries)
            except requests.exceptions.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "LLM HTTP error %s (attempt %d/%d)",
                    exc.response.status_code if exc.response else "?",
                    attempt,
                    self.max_retries,
                )
                # 4xx (except 429) are not retryable
                if exc.response is not None and exc.response.status_code not in (429, 503, 504):
                    break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM unexpected error (attempt %d/%d): %s",
                    attempt, self.max_retries, exc,
                )

            if attempt < self.max_retries:
                sleep = self.backoff_base ** (attempt - 1)
                logger.info("LLM retry backoff %.1fs", sleep)
                time.sleep(sleep)

        raise LLMError(
            f"LLM call failed after {self.max_retries} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    def _dispatch(self, prompt: str) -> str:
        if self.backend == "huggingface":
            return _call_huggingface(prompt, self.max_new_tokens)
        if self.backend == "openai":
            return _call_openai(prompt, self.max_new_tokens)
        raise LLMError(f"Unknown LLM_BACKEND: {self.backend!r}")


# Module-level singleton — reuse across tasks in the same process
_default_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Return the module-level LLMClient instance (creates on first call)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
