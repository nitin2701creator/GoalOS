"""API schemas for the OpenWebUI-compatible chat interface.

The request shape mirrors the OpenAI chat-completions contract so
OpenWebUI can talk to GoalOS without a proxy: ``model``, ``messages``,
``temperature``, ``stream``, ``tools`` and ``tool_choice`` are all
accepted. GoalOS drives the actual work through the existing agent
factory and workflow orchestrator — never through free-form prompts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: The logical GoalOS model id exposed to OpenWebUI. It is a routing
#: handle for the GoalOS autonomous system, not a hosted LLM.
GOALOS_MODEL_ID = "goalos-autonomous"


class ChatMessage(BaseModel):
    """One conversation message from OpenWebUI."""

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request accepted by GoalOS.

    Attributes:
        model: Ignored for routing (GoalOS always uses the autonomous
            pipeline) but echoed back in the response for compatibility.
        messages: Conversation messages; the last user message drives
            intent, earlier messages provide context.
        temperature: Accepted for OpenAI compatibility; passed through to
            LLM summarization when an LLM provider is configured.
        stream: Whether to return a server-sent event stream.
        tools: Accepted for compatibility; GoalOS capabilities are
            resolved from the message, not from tool declarations.
        tool_choice: Accepted for compatibility (single tool selection
            semantics do not apply to the GoalOS pipeline).
    """

    model: str = GOALOS_MODEL_ID
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
