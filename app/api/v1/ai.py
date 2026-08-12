"""Internal GoalOS AI gateway.

``POST /api/v1/ai/chat`` forwards OpenAI-compatible chat requests to the
configured LLM provider (currently FreeLLMAPI, any OpenAI-compatible
service later) through the existing :class:`LLMGateway`. The upstream
API key is never exposed to the frontend: it lives only in the outbound
request headers, and errors are mapped to generic HTTP responses without
secrets.

``GET /api/v1/ai/health`` is a separate AI readiness endpoint: it reports
provider configuration state and optionally probes the provider without
making the application-level ``/health`` dependent on the LLM.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.ai.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMResponseError,
    LLMTimeoutError,
)
from app.ai.llm_gateway import LLMGateway
from app.llm.provider_factory import ProviderFactory
from app.schemas.ai import AIChatChoice, AIChatMessage, AIChatRequest, AIChatResponse

logger = logging.getLogger("goalos.ai")

router = APIRouter()


def _get_gateway() -> LLMGateway:
    """Build the shared LLM gateway from the environment configuration."""
    return LLMGateway()


def _provider_name() -> str:
    """Return the configured provider name for transparency in responses."""
    try:
        return type(ProviderFactory.create()).__name__
    except ValueError:
        return "OpenAI-compatible"


@router.post("/chat", response_model=AIChatResponse)
def ai_chat(
    payload: AIChatRequest,
    gateway: LLMGateway = Depends(_get_gateway),
) -> AIChatResponse:
    """Forward a chat request to the configured LLM provider.

    Raises:
        HTTPException: 502 for provider/authentication failures, 504 for
            timeouts. Messages are generic and never contain secrets.
    """
    started = time.monotonic()
    messages = [{"role": m.role, "content": m.content} for m in payload.messages]
    try:
        result = gateway.chat(
            messages,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except LLMAuthenticationError as error:
        logger.warning("LLM provider rejected authentication (request refused)")
        raise HTTPException(
            status_code=502, detail="LLM provider authentication failed"
        ) from error
    except LLMTimeoutError as error:
        logger.warning("LLM provider request timed out")
        raise HTTPException(status_code=504, detail="LLM provider request timed out") from error
    except LLMConnectionError as error:
        logger.warning("LLM provider unavailable")
        raise HTTPException(status_code=502, detail="LLM provider unavailable") from error
    except LLMResponseError as error:
        logger.warning("LLM provider returned an invalid response")
        raise HTTPException(
            status_code=502, detail="LLM provider returned an invalid response"
        ) from error

    elapsed_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "ai chat completed model=%s provider=%s elapsed_ms=%d",
        result.model,
        _provider_name(),
        elapsed_ms,
    )
    return AIChatResponse(
        id=f"chatcmpl-{uuid.uuid4().hex[:24]}",
        created=int(time.time()),
        model=result.model,
        provider=_provider_name(),
        choices=[
            AIChatChoice(
                index=0,
                message=AIChatMessage(role="assistant", content=result.text),
                finish_reason="stop",
            )
        ],
        usage=result.usage,
    )


@router.get("/health")
def ai_health(
    probe: bool = False,
    gateway: LLMGateway = Depends(_get_gateway),
) -> dict[str, Any]:
    """Report AI readiness without coupling the app-level health check.

    Args:
        probe: When true, attempt a minimal request against the
            configured provider. Defaults to configuration-only status.
        gateway: Injected gateway (the shared one by default).
    """
    try:
        provider = ProviderFactory.create()
    except ValueError as error:
        return {"status": "error", "llm": {"configured": False, "message": str(error)}}

    configured = _is_configured(provider)
    report: dict[str, Any] = {
        "status": "ok",
        "llm": {
            "configured": configured,
            "provider": type(provider).__name__,
        },
    }

    if probe:
        if not configured:
            report["llm"]["probe"] = "skipped_not_configured"
            return report
        try:
            result = gateway.chat(
                [{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            report["llm"]["probe"] = "ok"
            report["llm"]["model"] = result.model
        except (LLMAuthenticationError, LLMConnectionError, LLMTimeoutError, LLMResponseError):
            report["llm"]["probe"] = "failed"
    return report


def _is_configured(provider: Any) -> bool:
    """Return whether the provider holds the credentials for real calls.

    Never inspects or returns the credential value itself.
    """
    from app.llm.base_provider import provider_configured

    return provider_configured(provider)
