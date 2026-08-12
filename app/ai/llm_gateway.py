"""Provider-agnostic language-model gateway for GoalOS agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.exceptions import LLMResponseError
from app.ai.free_llm_client import FreeLLMClient


@dataclass(frozen=True, slots=True)
class LLMChatResult:
    """Structured outcome of an OpenAI-compatible chat request.

    Attributes:
        text: The assistant message content.
        model: The model that produced the response.
        usage: Token usage reported by the provider (may be empty).
    """

    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


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

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **parameters: Any,
    ) -> LLMChatResult:
        """Send an OpenAI-compatible chat request and return a structured result.

        Args:
            messages: Conversation messages as ``{role, content}`` dicts.
            model: Optional model override.
            temperature: Optional sampling temperature.
            max_tokens: Optional completion token cap.
            **parameters: Additional provider request parameters.

        Raises:
            LLMError: If communication or response processing fails.
        """

        response = self._client.chat(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **parameters,
        )
        text = self._response_text(response)
        resolved_model = response.get("model") or model or self._client.config.default_model
        usage = response.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return LLMChatResult(text=text, model=resolved_model, usage=usage)

    @staticmethod
    def extract_text(response: dict[str, Any]) -> str:
        """Public alias for :meth:`_response_text`."""

        return LLMGateway._response_text(response)

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
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        text = "".join(
                            part.get("text", "")
                            for part in content
                            if isinstance(part, dict)
                            and isinstance(part.get("text"), str)
                        )
                        if text:
                            return text
        raise LLMResponseError("Language-model response does not contain text")
