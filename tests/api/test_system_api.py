"""API tests for Sprint 1 system and memory endpoints."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.api.v1.system import router as system_router
from app.api.v1.memory_api import router as memory_router

# Ensure all models are registered with Base.metadata before create_all
from app.db.models import MemoryRecord  # noqa: F401


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    app = FastAPI()

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(system_router, prefix="/api/v1/system")
    app.include_router(memory_router, prefix="/api/v1/memory")
    return TestClient(app)


# --- System endpoints ---

class TestSystemAPI:
    def test_resource_status(self, client):
        resp = client.get("/api/v1/system/resource-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "metrics" in data
        assert "cpu_percent" in data["metrics"]
        assert "ram_percent" in data["metrics"]
        assert "sustained_averages" in data

    def test_capacity_advisor(self, client):
        resp = client.get("/api/v1/system/capacity-advisor")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert data["status"] in ("HEALTHY", "WARNING", "CAPACITY_RISK", "UPGRADE_RECOMMENDED")
        assert "reasons" in data
        assert "sustained_metrics" in data
        assert "thresholds_applied" in data


# --- Memory endpoints ---

class TestMemoryAPI:
    def test_remember(self, client):
        resp = client.post("/api/v1/memory/remember", json={
            "entity": f"test_user_{uuid.uuid4().hex[:8]}",
            "content": "Test memory",
            "memory_type": "fact",
            "importance": 0.7,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "Test memory"
        assert data["memory_type"] == "fact"

    def test_search(self, client):
        entity = f"search_user_{uuid.uuid4().hex[:8]}"
        client.post("/api/v1/memory/remember", json={
            "entity": entity,
            "content": "Searchable memory",
            "memory_type": "knowledge",
        })
        resp = client.post("/api/v1/memory/search", json={
            "entity": entity,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    def test_get_context(self, client):
        entity = f"ctx_user_{uuid.uuid4().hex[:8]}"
        client.post("/api/v1/memory/remember", json={
            "entity": entity,
            "content": "Context memory",
            "memory_type": "fact",
        })
        resp = client.get(f"/api/v1/memory/context/{entity}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity"] == entity
        assert data["total_count"] >= 1

    def test_forget(self, client):
        entity = f"forget_user_{uuid.uuid4().hex[:8]}"
        create_resp = client.post("/api/v1/memory/remember", json={
            "entity": entity,
            "content": "To forget",
            "memory_type": "fact",
        })
        mem_id = create_resp.json()["id"]
        resp = client.post("/api/v1/memory/forget", json={
            "memory_id": mem_id,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_forget_nonexistent(self, client):
        fake_id = str(uuid.uuid4())
        resp = client.post("/api/v1/memory/forget", json={
            "memory_id": fake_id,
        })
        assert resp.status_code == 404
