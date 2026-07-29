"""Provider-agnostic language-model gateway for GoalOS agents."""

from __future__ import annotations

from typing import Any

from app.ai.exceptions import LLMResponseError
from app.ai.free_llm_client import FreeLLMClient


class LLMGateway:
    """Expose text generation without leaking provider details to agents."""

    def __init__(self, client: FreeLLMClient | None = None) -> None:
        """Initialize the gateway with an optional client for dependency injection."""

        self._client = client or FreeLLMClient()

    def generate(self, prompt: str, *, model: str | None = None, **parameters: Any) -> str:
        """Generate and return response text for ``prompt``.

        Raises:
            LLMResponseError: If the provider payload contains no response text.
        """

        response = self._client.request(prompt, model=model, **parameters)
        return self._response_text(response)

    def complete(self, prompt: str, *, model: str | None = None, **parameters: Any) -> str:
        """Compatibility alias for :meth:`generate`."""

        return self.generate(prompt, model=model, **parameters)

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        """Extract text from the provider response payload."""

        for key in ("response", "text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value

        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                text = first_choice.get("text")
                if isinstance(text, str):
                    return text
                message = first_choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        raise LLMResponseError("Language-model response does not contain text")
