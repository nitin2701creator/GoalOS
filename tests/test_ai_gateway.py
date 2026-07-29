"""Unit tests for the shared AI gateway."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.ai.config import LLMConfig
from app.ai.exceptions import LLMAuthenticationError, LLMConnectionError, LLMResponseError
from app.ai.free_llm_client import FreeLLMClient
from app.ai.llm_gateway import LLMGateway


def test_config_loads_environment_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration should load supported environment variables."""

    monkeypatch.setenv("FREELLM_BASE_URL", "https://llm.example.test/generate")
    monkeypatch.setenv("FREELLM_API_KEY", "test-key")
    monkeypatch.setenv("FREELLM_TIMEOUT", "12.5")
    monkeypatch.setenv("FREELLM_DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("FREELLM_MAX_RETRIES", "2")

    config = LLMConfig.from_env()

    assert config == LLMConfig(
        base_url="https://llm.example.test/generate",
        api_key="test-key",
        timeout=12.5,
        default_model="test-model",
        max_retries=2,
    )


def test_gateway_initializes_default_client() -> None:
    """Gateway should create a client when one is not supplied."""

    gateway = LLMGateway()

    assert isinstance(gateway._client, FreeLLMClient)


def test_gateway_returns_text_from_mocked_client() -> None:
    """Gateway should isolate clients and return only response text."""

    client = Mock(spec=FreeLLMClient)
    client.request.return_value = {"response": "Generated plan"}

    result = LLMGateway(client).generate("Create a plan", temperature=0.2)

    assert result == "Generated plan"
    client.request.assert_called_once_with("Create a plan", model=None, temperature=0.2)


def test_client_retries_connection_errors() -> None:
    """Transient connection errors should be retried up to the configured limit."""

    client = FreeLLMClient(LLMConfig(max_retries=1))
    client._send_request = Mock(side_effect=[LLMConnectionError("offline"), {"response": "ok"}])

    assert client.request("Hello") == {"response": "ok"}
    assert client._send_request.call_count == 2


def test_gateway_propagates_client_errors() -> None:
    """Gateway should preserve meaningful client errors for callers."""

    client = Mock(spec=FreeLLMClient)
    client.request.side_effect = LLMAuthenticationError("invalid key")

    with pytest.raises(LLMAuthenticationError, match="invalid key"):
        LLMGateway(client).generate("Hello")


def test_gateway_rejects_response_without_text() -> None:
    """Gateway should reject malformed provider responses."""

    client = Mock(spec=FreeLLMClient)
    client.request.return_value = {"status": "ok"}

    with pytest.raises(LLMResponseError, match="does not contain text"):
        LLMGateway(client).generate("Hello")
