"""OpenAI-compatible API for OpenWebUI.

GoalOS exposes ``GET /v1/models``, ``POST /v1/chat/completions`` and
``GET /v1/health`` in the OpenAI wire format so OpenWebUI (deployed on
the same KVM) can talk to GoalOS directly. The endpoints never answer
from a prompt: they route through the existing GoalOS autonomous system
(agent factory → skills → integrations → workflow orchestrator) exactly
as the rest API does.

Authentication: every ``/v1/*`` endpoint requires ``Authorization:
Bearer <GOALOS_OPENWEBUI_API_KEY>`` using a constant-time comparison.
The key is never logged.
"""

from __future__ import annotations

import hmac
import json
import os
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from app.db.session import get_db
from app.integrations.factory import build_default_registry
from app.llm.provider_factory import ProviderFactory
from app.schemas.chat import GOALOS_MODEL_ID, ChatCompletionRequest
from app.services.chat_service import ChatService, llm_configured

router = APIRouter()

#: GoalOS version reported by the health endpoints.
_GOALOS_VERSION = "0.5.0"


def _api_key() -> str | None:
    """Return the configured OpenWebUI API key, if any."""
    value = os.getenv("GOALOS_OPENWEBUI_API_KEY")
    return value.strip() if value and value.strip() else None


def _authenticate(request: Request) -> None:
    """Require a valid bearer token for every /v1 request.

    Raises:
        HTTPException: 503 when the key is not configured at all, 401 for
            a missing or invalid token.
    """
    configured = _api_key()
    if configured is None:
        raise HTTPException(
            status_code=503,
            detail="GOALOS_OPENWEBUI_API_KEY is not configured",
        )
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not hmac.compare_digest(token, configured):
        raise HTTPException(status_code=401, detail="invalid API key")


def _get_chat_service(db=Depends(get_db)) -> ChatService:
    """Compose the chat service per request (existing conventions).

    The LLM provider comes from the existing :class:`ProviderFactory`;
    without configuration the deterministic response path is used.
    """
    provider = None
    try:
        provider = ProviderFactory.create()
    except ValueError:
        provider = None
    return ChatService(db=db, llm_provider=provider)


@router.get("/models")
def list_models(request: Request) -> dict[str, Any]:
    """Return the GoalOS model in OpenAI models-list format."""
    _authenticate(request)
    return {
        "object": "list",
        "data": [
            {
                "id": GOALOS_MODEL_ID,
                "object": "model",
                "created": 1700000000,
                "owned_by": "goalos",
            }
        ],
    }


@router.post("/chat/completions")
def chat_completions(
    request: Request,
    payload: ChatCompletionRequest,
    service: ChatService = Depends(_get_chat_service),
):
    """Handle an OpenWebUI chat completion request through GoalOS.

    The request is routed through the GoalOS autonomous system
    (agent/workflow orchestration); the response is OpenAI-compatible.
    ``stream`` returns a single-chunk server-sent event stream.
    """
    _authenticate(request)
    result = service.handle(payload)
    completion = _build_completion(payload, result.content)
    if payload.stream:
        return _stream_completion(completion)
    return completion


@router.get("/health")
def v1_health(request: Request, db=Depends(get_db)) -> dict[str, Any]:
    """Structured health for GoalOS, database, LLM, and integrations.

    Only configuration *state* is reported — never credentials.
    """
    _authenticate(request)
    return build_health_payload(db)


def build_health_payload(db) -> dict[str, Any]:
    """Build the structured health payload shared by /health and /v1/health."""
    try:
        db.execute(text("SELECT 1"))
        database = {"status": "healthy"}
    except Exception as exc:  # noqa: BLE001 - health must never 500
        database = {"status": "unhealthy", "error": str(exc)}

    try:
        provider = ProviderFactory.create()
        llm = {
            "status": "configured" if llm_configured(provider) else "not_configured",
            "provider": type(provider).__name__,
        }
    except ValueError as exc:
        llm = {"status": "error", "message": str(exc)}

    registry = build_default_registry(session=db)
    integrations = []
    for name in registry.list_connectors():
        connector = registry.get_connector(name)
        assert connector is not None
        health = connector.health_check()
        integrations.append(
            {
                "name": name,
                "status": health.status.value,
                "message": health.message,
            }
        )

    return {
        "status": "ok",
        "goalos": {"status": "running", "version": _GOALOS_VERSION},
        "database": database,
        "llm": llm,
        "integrations": {"total": len(integrations), "items": integrations},
    }


def _build_completion(payload: ChatCompletionRequest, content: str) -> dict[str, Any]:
    """Build the OpenAI-compatible non-streaming completion payload."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _stream_completion(completion: dict[str, Any]) -> StreamingResponse:
    """Emit the completion as a single-chunk SSE stream."""

    def generate():
        content = completion["choices"][0]["message"]["content"]
        first = {
            "id": completion["id"],
            "object": "chat.completion.chunk",
            "created": completion["created"],
            "model": completion["model"],
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(first)}\n\n"
        final = {
            "id": completion["id"],
            "object": "chat.completion.chunk",
            "created": completion["created"],
            "model": completion["model"],
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
