"""API tests for Twenty webhook ingestion.

Proves signature validation (HMAC-SHA256 over ``{timestamp}:{payload}``),
timestamp/replay protection, durable event persistence, safe 2xx
acknowledgment after valid receipt, rejection of invalid signatures, and
the honest 503 when no webhook secret is configured. No real Twenty
deliveries are involved.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app

SECRET = "twenty-webhook-test-secret"


def _sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
    payload_text = body.decode("utf-8", errors="replace")
    return hmac.new(secret.encode(), f"{timestamp}:{payload_text}".encode(), hashlib.sha256).hexdigest()


def _payload(record_id: str = "abc12345", event: str = "person.created") -> bytes:
    body = {
        "event": event,
        "data": {
            "id": record_id,
            "firstName": "Alice",
            "lastName": "Doe",
            "email": "alice@example.com",
            "createdAt": "2026-08-12T10:00:00Z",
        },
        "timestamp": "2026-08-12T10:00:05Z",
    }
    return json.dumps(body, separators=(",", ":")).encode()


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _headers(body: bytes, *, timestamp: str | None = None, secret: str = SECRET, tamper: bool = False) -> dict[str, str]:
    ts = timestamp or _now_timestamp()
    signature = _sign(body, ts, secret) if not tamper else "0" * 64
    return {
        "X-Twenty-Webhook-Timestamp": ts,
        "X-Twenty-Webhook-Signature": signature,
        "Content-Type": "application/json",
    }


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and the webhook secret configured."""
    monkeypatch.setenv("GOALOS_TWENTY_WEBHOOK_SECRET", SECRET)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'webhooks.db'}",
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


def test_valid_webhook_is_acknowledged_and_persisted(api: TestClient) -> None:
    body = _payload()
    response = api.post("/api/v1/webhooks/twenty", content=body, headers=_headers(body))
    assert response.status_code == 202
    result = response.json()
    assert result["accepted"] is True
    assert result["status"] == "received"
    assert result["event_type"] == "person.created"

    events = api.get("/api/v1/webhooks/events").json()
    assert events["total"] == 1
    event = events["events"][0]
    assert event["signature_valid"] is True
    assert event["status"] == "received"
    assert event["object_type"] == "person"
    assert event["object_id"] == "abc12345"
    assert event["payload"]["data"]["firstName"] == "Alice"


def test_invalid_signature_is_rejected(api: TestClient) -> None:
    body = _payload()
    response = api.post("/api/v1/webhooks/twenty", content=body, headers=_headers(body, tamper=True))
    assert response.status_code == 401
    assert "signature" in response.json()["detail"].casefold()

    # The rejected delivery is persisted for audit (signature_valid False).
    events = api.get("/api/v1/webhooks/events").json()
    assert events["total"] == 1
    assert events["events"][0]["signature_valid"] is False
    assert events["events"][0]["status"] == "rejected"


def test_tampered_body_is_rejected(api: TestClient) -> None:
    body = _payload(record_id="abc12345")
    headers = _headers(body)
    tampered = _payload(record_id="CHANGED")
    response = api.post("/api/v1/webhooks/twenty", content=tampered, headers=headers)
    assert response.status_code == 401


def test_stale_timestamp_is_rejected_as_replay(api: TestClient) -> None:
    body = _payload()
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    response = api.post("/api/v1/webhooks/twenty", content=body, headers=_headers(body, timestamp=stale))
    assert response.status_code == 401
    assert "tolerance" in response.json()["detail"].casefold()


def test_duplicate_delivery_is_idempotent(api: TestClient) -> None:
    body = _payload(record_id="dup-1")
    headers = _headers(body)
    first = api.post("/api/v1/webhooks/twenty", content=body, headers=headers)
    assert first.status_code == 202

    second = api.post("/api/v1/webhooks/twenty", content=body, headers=headers)
    assert second.status_code == 200
    result = second.json()
    assert result["accepted"] is False
    assert result["status"] == "duplicate"

    events = api.get("/api/v1/webhooks/events").json()
    assert events["total"] == 1  # only one durable record


def test_missing_signature_headers_is_rejected(api: TestClient) -> None:
    body = _payload()
    response = api.post(
        "/api/v1/webhooks/twenty",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_missing_secret_returns_503(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOALOS_TWENTY_WEBHOOK_SECRET")
    body = _payload()
    response = api.post("/api/v1/webhooks/twenty", content=body, headers=_headers(body))
    assert response.status_code == 503
    assert "GOALOS_TWENTY_WEBHOOK_SECRET" in response.json()["detail"]
