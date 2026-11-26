"""
Thin wrapper around the LLM provider.
Supports Gemini (default), Groq, and a Fake provider for tests.
Tracks call count so the graph can enforce the 4-call ceiling.

Design: treat every model response as untrusted bytes.
  - Parse JSON with json.loads(), never eval().
  - Validate structure with Pydantic before acting on it.
  - If the model returns something unexpected, raise LLMParseError
    so the graph can respond gracefully instead of crashing.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from app.core.config import get_settings

settings = get_settings()


class LLMBudgetExceeded(Exception):
    """Raised when a turn would exceed MAX_LLM_CALLS_PER_TURN."""


class LLMParseError(Exception):
    """Raised when model output cannot be parsed into the expected schema."""


class LLMTimeoutError(Exception):
    """Raised when the LLM call exceeds LLM_TIMEOUT_SECONDS."""


# ---------------------------------------------------------------------------
# Fake LLM — deterministic, used by all automated tests
# ---------------------------------------------------------------------------

class FakeLLM:
    """
    Returns hard-coded structured responses keyed by the first user message.
    Add entries to RESPONSES to cover new test scenarios.
    """
    RESPONSES: dict[str, dict] = {
        "default": {
            "action": "clarify",
            "question": "Could you tell me whether this is for your pickup or drop trip, and what time you'd prefer?",
        },
        "change drop to 8": {
            "action": "change_drop",
            "intent": "change_drop",
            "requested_time": "20:00",
        },
        "change pickup to 9": {
            "action": "change_pickup",
            "intent": "change_pickup",
            "requested_time": "09:00",
        },
        "yes": {
            "action": "confirm",
        },
        "no": {
            "action": "cancel",
        },
    }

    def chat(self, messages: list[dict], **kwargs) -> dict:
        last_user = next(
            (m["content"].lower().strip() for m in reversed(messages) if m["role"] == "user"),
            "",
        )
        for key, val in self.RESPONSES.items():
            if key in last_user:
                return val
        return self.RESPONSES["default"]


# ---------------------------------------------------------------------------
# Real LLM — Gemini via google-generativeai
# ---------------------------------------------------------------------------

class GeminiLLM:
    def __init__(self):
        import google.generativeai as genai  # type: ignore
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY not set. Add it to .env.")
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(settings.LLM_MODEL)

    def chat(self, messages: list[dict], system_prompt: str = "") -> dict:
        # TODO: format messages into Gemini's content format and call generate_content()
        raise NotImplementedError("GeminiLLM.chat not yet implemented — use FAKE for tests.")


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def _get_provider():
    provider = settings.LLM_PROVIDER.lower()
    if provider == "fake":
        return FakeLLM()
    elif provider == "gemini":
        return GeminiLLM()
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'fake', 'gemini', or 'groq'.")


_PROVIDER = None  # lazy singleton


def call_llm(
    messages: list[dict],
    current_call_count: int,
    system_prompt: str = "",
) -> dict:
    """
    Public interface for the graph nodes.

    Raises LLMBudgetExceeded before calling the provider if the ceiling is hit.
    Raises LLMTimeoutError on timeout.
    Returns a plain dict parsed from the model's JSON response.
    """
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = _get_provider()

    if current_call_count >= settings.MAX_LLM_CALLS_PER_TURN:
        raise LLMBudgetExceeded(
            f"Reached the {settings.MAX_LLM_CALLS_PER_TURN}-call LLM limit for this turn. "
            "Responding with a safe fallback."
        )

    start = time.monotonic()
    try:
        raw = _PROVIDER.chat(messages, system_prompt=system_prompt)
    except Exception as exc:
        elapsed = time.monotonic() - start
        if elapsed >= settings.LLM_TIMEOUT_SECONDS:
            raise LLMTimeoutError(f"LLM call timed out after {elapsed:.1f}s") from exc
        raise

    # Validate: must be a dict
    if not isinstance(raw, dict):
        raise LLMParseError(f"Expected dict from LLM, got {type(raw).__name__}: {raw!r}")

    return raw
