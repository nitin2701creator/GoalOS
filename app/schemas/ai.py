"""API schemas for the internal GoalOS AI gateway.

The request shape follows the OpenAI chat-completions convention
(``messages``, optional ``model``/``temperature``/``max_tokens``) so the
gateway contract stays stable even when the upstream provider changes.
The response returns the assistant text plus useful metadata (model,
provider, token usage when reported).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AIChatMessage(BaseModel):
    """One conversation message sent to the AI gateway."""

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class AIChatRequest(BaseModel):
    """Request body for ``POST /api/v1/ai/chat``.

    Attributes:
        messages: Conversation messages; the last one usually carries the
            current instruction.
        model: Optional model override. Falls back to the configured
            provider default when omitted.
        temperature: Optional sampling temperature.
        max_tokens: Optional cap on completion tokens.
    """

    messages: list[AIChatMessage] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class AIChatChoice(BaseModel):
    """One completion choice in the gateway response."""

    index: int = 0
    message: AIChatMessage
    finish_reason: str = "stop"


class AIChatResponse(BaseModel):
    """Response body from ``POST /api/v1/ai/chat``.

    Attributes:
        id: Unique completion id.
        model: Model that produced the response.
        provider: Provider name reported for transparency.
        choices: Completion choices (normally exactly one).
        usage: Token usage as reported by the provider, when available.
    """

    id: str
    object: str = "chat.completion"
    created: int
    model: str
    provider: str
    choices: list[AIChatChoice]
    usage: dict[str, int] = Field(default_factory=dict)
