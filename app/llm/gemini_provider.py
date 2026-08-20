"""Google Gemini LLM provider for GoalOS.

Uses the official ``google-genai`` Python SDK.  The API key is read
exclusively from the ``GEMINI_API_KEY`` environment variable and is
never logged or persisted in source code.
"""

from __future__ import annotations

import os
import logging
from typing import Any

from app.llm.base_provider import BaseProvider

logger = logging.getLogger(__name__)

#: Default Gemini model when GEMINI_MODEL is not set.
_DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider(BaseProvider):
    """Google Gemini provider using the official ``google-genai`` SDK."""

    def __init__(self) -> None:
        self.api_key: str | None = os.getenv("GEMINI_API_KEY", "").strip() or None
        self.default_model: str = (
            os.getenv("GEMINI_MODEL", "").strip() or _DEFAULT_MODEL
        )
        self._client: Any = None  # lazy-initialized

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_client(self) -> Any:
        """Lazy-initialize the google-genai client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not configured")
            from google import genai  # noqa: WPS433 — lazy import

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _generate_text(self, prompt: str, **kwargs: Any) -> str:
        """Call Gemini generate_content and return the text."""
        model = kwargs.pop("model", None) or self.default_model
        client = self._get_client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        # response.text is the standard attribute on GenerateContentResponse
        text = getattr(response, "text", None)
        if text:
            return text
        # Fallback: some SDK versions return candidates
        candidates = getattr(response, "candidates", None)
        if candidates:
            parts = getattr(candidates[0], "content", None)
            if parts and hasattr(parts, "parts"):
                return "".join(
                    getattr(p, "text", "") for p in parts.parts if getattr(p, "text", "")
                )
        return ""

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------
    def request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a completion for *prompt* and return its payload.

        Returns:
            A provider payload whose ``response`` key holds the text,
            matching the convention used by
            :class:`~app.llm.openai_compatible_provider.OpenAICompatibleProvider`.
        """
        if not prompt or not prompt.strip():
            from app.ai.exceptions import LLMResponseError

            raise LLMResponseError("Prompt must not be empty")

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not configured")

        model = kwargs.pop("model", None) or self.default_model
        try:
            response_text = self._generate_text(prompt, model=model, **kwargs)
        except Exception as exc:
            from app.ai.exceptions import (
                LLMAuthenticationError,
                LLMConnectionError,
                LLMError,
            )

            error_str = str(exc).lower()
            if "api_key" in error_str or "api key" in error_str or "permission" in error_str:
                raise LLMAuthenticationError(
                    "Gemini API key is invalid or missing"
                ) from exc
            if "timeout" in error_str or "deadline" in error_str:
                raise LLMError(f"Gemini request timed out: {exc}") from exc
            raise LLMConnectionError(
                f"Gemini API request failed: {exc}"
            ) from exc

        if not response_text:
            from app.ai.exceptions import LLMResponseError

            raise LLMResponseError("Gemini response did not contain text")

        return {
            "model": model,
            "prompt": prompt,
            "response": response_text,
        }

    def health_check(self) -> bool:
        """Return whether the provider is configured for real calls.

        Gemini needs an API key before the executor should attempt a run.
        """
        return bool(self.api_key)
