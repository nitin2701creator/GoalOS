"""API tests for the internal GoalOS AI gateway (``/api/v1/ai``).

The upstream LLM is mocked with a fake HTTP opener so the whole suite
runs without a real API key. Covers configuration loading, successful
requests, provider errors/timeouts, invalid requests, response
structure, and that the API key never leaks into responses or logs.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.config import LLMConfig
from app.ai.free_llm_client import FreeLLMClient
from app.ai.llm_gateway import LLMGateway
from app.api.v1 import ai as ai_module
from app.db import session as session_module
from app.db.base import Base
from app.main import app

CHAT_URL = "http://llm.test/v1/chat/completions"
API_KEY = "super-secret-test-key"


class FakeChatResponse:
    """Mimic the parts of ``http.client.HTTPResponse`` used by the client."""

    def __init__(self, body: bytes) -> None:
        self._body = io.BytesIO(body)
        self.status = 200
        self.headers = {"Content-Type": "application/json"}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc: object) -> None:
        self._body.close()


class ChatOpener:
    """Fake urlopen: record the request, then serve or raise a fixture."""

    def __init__(self, *, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[tuple[str, bytes]] = []

    def __call__(self, request, timeout: float | None = None) -> FakeChatResponse:
        url = str(getattr(request, "full_url", request))
        data = getattr(request, "data", b"")
        self.requests.append((url, data))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return FakeChatResponse(json.dumps(self.response).encode("utf-8"))


def _gateway(opener: ChatOpener, *, base_url: str = "http://llm.test") -> LLMGateway:
    config = LLMConfig(base_url=base_url, api_key=API_KEY, max_retries=0)
    return LLMGateway(FreeLLMClient(config, opener=opener))


@pytest.fixture
def api(tmp_path: Path):
    """TestClient with an isolated DB; AI gateway is overridden per test."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ai_gateway.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _install_gateway(opener: ChatOpener, **kwargs) -> None:
    app.dependency_overrides[ai_module._get_gateway] = lambda: _gateway(opener, **kwargs)


def _openai_payload(content: str = "Hello from the model") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "free-llm-small",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
    }


# ---------------------------------------------------------------------------
# Configuration loading
# ---------------------------------------------------------------------------


def test_config_loads_llm_base_url_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL / LLM_API_KEY / LLM_MODEL drive the gateway config."""
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", API_KEY)
    monkeypatch.setenv("LLM_MODEL", "free-llm-small")

    config = LLMConfig.from_env()

    assert config.base_url == "http://llm.test"
    assert config.api_key == API_KEY
    assert config.default_model == "free-llm-small"
    assert config.chat_path == "/v1/chat/completions"


def test_chat_url_appends_standard_endpoint() -> None:
    """The client targets the OpenAI-compatible chat completions endpoint."""
    client = FreeLLMClient(LLMConfig(base_url="http://llm.test"))
    assert client.chat_url == "http://llm.test/v1/chat/completions"


def test_chat_url_respects_full_endpoint_and_custom_path() -> None:
    """A fully-qualified base URL and LLM_CHAT_PATH are honoured."""
    client = FreeLLMClient(LLMConfig(base_url="http://llm.test/v1/chat/completions"))
    assert client.chat_url == "http://llm.test/v1/chat/completions"

    custom = FreeLLMClient(LLMConfig(base_url="http://llm.test", chat_path="/v1/completions"))
    assert custom.chat_url == "http://llm.test/v1/completions"


def test_chat_url_does_not_duplicate_v1_segment() -> None:
    """A base URL ending in /v1 must not produce /v1/v1/chat/completions."""
    client = FreeLLMClient(LLMConfig(base_url="http://llm.test/v1"))
    assert client.chat_url == "http://llm.test/v1/chat/completions"

    trailing = FreeLLMClient(LLMConfig(base_url="http://llm.test/v1/"))
    assert trailing.chat_url == "http://llm.test/v1/chat/completions"


# ---------------------------------------------------------------------------
# Successful chat requests
# ---------------------------------------------------------------------------


def test_ai_chat_returns_assistant_response_and_metadata(api) -> None:
    """A valid chat request returns content, model, provider, and usage."""
    opener = ChatOpener(response=_openai_payload())
    _install_gateway(opener)

    response = api.post(
        "/api/v1/ai/chat",
        json={
            "messages": [{"role": "user", "content": "Say hello"}],
            "model": "free-llm-small",
            "temperature": 0.7,
            "max_tokens": 32,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "free-llm-small"
    assert body["provider"] == "FreeLLMProvider"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert body["choices"][0]["message"]["content"] == "Hello from the model"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["total_tokens"] == 9
    assert body["id"].startswith("chatcmpl-")

    url, data = opener.requests[0]
    assert url == CHAT_URL
    sent = json.loads(data)
    assert sent["messages"] == [{"role": "user", "content": "Say hello"}]
    assert sent["model"] == "free-llm-small"
    assert sent["temperature"] == 0.7
    assert sent["max_tokens"] == 32
    assert sent.get("api_key") is None


def test_ai_chat_uses_default_model_when_omitted(api) -> None:
    """Omitting model falls back to the configured provider default."""
    opener = ChatOpener(response=_openai_payload())
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 200
    _, data = opener.requests[0]
    assert json.loads(data)["model"] == "free-llm-small"


def test_ai_chat_production_v1_base_url_and_model(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_BASE_URL ending in /v1 + LLM_MODEL hit /v1/chat/completions once.

    Replicates the production FreeLLMAPI configuration
    (``LLM_BASE_URL=http://127.0.0.1:3001/v1``, ``LLM_MODEL=openai-fast``)
    so the historical double-``/v1`` regression stays covered.
    """
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", API_KEY)
    monkeypatch.setenv("LLM_MODEL", "openai-fast")
    opener = ChatOpener(response=_openai_payload(content="Hello from openai-fast"))
    config = LLMConfig.from_env()
    app.dependency_overrides[ai_module._get_gateway] = lambda: LLMGateway(
        FreeLLMClient(config, opener=opener)
    )

    response = api.post(
        "/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
    )

    assert response.status_code == 200
    assert (
        response.json()["choices"][0]["message"]["content"]
        == "Hello from openai-fast"
    )
    url, data = opener.requests[0]
    assert url == "http://llm.test/v1/chat/completions"
    assert json.loads(data)["model"] == "openai-fast"


def test_ai_chat_parses_content_parts_response(api) -> None:
    """message.content as a list of text parts is parsed (OpenAI multimodal)."""
    payload = _openai_payload()
    payload["choices"][0]["message"]["content"] = [
        {"type": "text", "text": "Part one. "},
        {"type": "text", "text": "Part two."},
        {"type": "image_url", "image_url": {"url": "https://example.test/x.png"}},
    ]
    opener = ChatOpener(response=payload)
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Part one. Part two."


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_ai_chat_provider_authentication_failure(api) -> None:
    """Upstream auth rejection maps to 502 without leaking the key."""
    opener = ChatOpener(error=HTTPError(CHAT_URL, 401, "Unauthorized", {}, None))
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 502
    assert API_KEY not in response.text


def test_ai_chat_provider_error(api) -> None:
    """Upstream 5xx maps to 502 and never fabricates success."""
    opener = ChatOpener(error=HTTPError(CHAT_URL, 500, "Server Error", {}, None))
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 502
    assert API_KEY not in response.text


def test_ai_chat_provider_timeout(api) -> None:
    """A provider timeout maps to 504."""
    opener = ChatOpener(error=TimeoutError("timed out"))
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 504
    assert API_KEY not in response.text


def test_ai_chat_invalid_request(api) -> None:
    """Empty or malformed messages are rejected with 422."""
    response = api.post("/api/v1/ai/chat", json={"messages": []})
    assert response.status_code == 422

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": ""}]})
    assert response.status_code == 422

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "admin", "content": "x"}]})
    assert response.status_code == 422


def test_ai_chat_malformed_provider_response(api) -> None:
    """A provider payload without response text maps to 502."""
    opener = ChatOpener(response={"status": "ok"})
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 502
    assert API_KEY not in response.text


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_api_key_never_logged_or_returned(api, caplog: pytest.LogCaptureFixture) -> None:
    """The API key must not appear in logs or error responses."""
    opener = ChatOpener(error=HTTPError(CHAT_URL, 401, "Unauthorized", {}, None))
    _install_gateway(opener)

    with caplog.at_level(logging.WARNING, logger="goalos.ai"):
        response = api.post(
            "/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]}
        )

    assert response.status_code == 502
    assert API_KEY not in response.text
    assert API_KEY not in caplog.text


def test_ai_chat_success_does_not_echo_key(api) -> None:
    """Successful responses contain no trace of the upstream key."""
    opener = ChatOpener(response=_openai_payload())
    _install_gateway(opener)

    response = api.post("/api/v1/ai/chat", json={"messages": [{"role": "user", "content": "Hi"}]})

    assert response.status_code == 200
    assert API_KEY not in response.text
    url, data = opener.requests[0]
    assert API_KEY.encode() not in data
    assert API_KEY not in url


# ---------------------------------------------------------------------------
# Health / readiness
# ---------------------------------------------------------------------------


def test_ai_health_reports_not_configured(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without credentials the AI health endpoint says so honestly."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    response = api.get("/api/v1/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm"]["configured"] is False


def test_ai_health_reports_configured(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """With credentials configured the AI health endpoint reports so."""
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", API_KEY)
    monkeypatch.setenv("LLM_MODEL", "free-llm-small")

    response = api.get("/api/v1/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm"]["configured"] is True


def test_ai_health_probe_ok(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe=true performs a real (mocked) provider call and reports ok."""
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", API_KEY)
    monkeypatch.setenv("LLM_MODEL", "free-llm-small")
    opener = ChatOpener(response=_openai_payload())
    _install_gateway(opener)

    response = api.get("/api/v1/ai/health?probe=true")

    assert response.status_code == 200
    body = response.json()
    assert body["llm"]["probe"] == "ok"
    assert opener.requests, "probe should have hit the provider"


def test_ai_health_probe_failed_when_provider_down(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe=true reports failed when the provider cannot be reached."""
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
    monkeypatch.setenv("LLM_API_KEY", API_KEY)
    monkeypatch.setenv("LLM_MODEL", "free-llm-small")
    opener = ChatOpener(error=TimeoutError("timed out"))
    _install_gateway(opener)

    response = api.get("/api/v1/ai/health?probe=true")

    assert response.status_code == 200
    assert response.json()["llm"]["probe"] == "failed"


# ---------------------------------------------------------------------------
# App-level health stays independent of the LLM provider
# ---------------------------------------------------------------------------


def test_app_health_independent_of_llm(api) -> None:
    """/health answers without depending on LLM provider state."""
    response = api.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "llm" in body


def test_openapi_documents_ai_gateway(api) -> None:
    """OpenAPI documents the new AI gateway endpoints."""
    spec = api.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/api/v1/ai/chat" in paths
    assert "/api/v1/ai/health" in paths
