"""API tests for the GoalOS agent factory.

Exercises the public agent endpoints end-to-end: creation, listing,
retrieval, permission enforcement, enable/disable, capability
resolution, and execution of a dynamically created agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app


@pytest.fixture
def api(tmp_path: Path):
    """TestClient whose database dependency points at an isolated file DB."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'agents_e2e.db'}",
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


def test_create_and_list_agents_via_api(api) -> None:
    """POST creates an ACTIVE agent; GET list and GET by id return it."""
    client = api
    response = client.post(
        "/api/v1/agents",
        json={
            "name": "SEO Agent",
            "purpose": "Research SEO keywords and analyze website SEO.",
            "required_capabilities": ["keyword_research", "website_analysis"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["name"] == "SEO Agent"
    assert body["permissions"] == ["READ_WEBSITE"]
    assert body["skills"] == ["keyword_research", "website_analysis"]
    agent_id = body["id"]

    listed = client.get("/api/v1/agents")
    assert listed.status_code == 200
    assert [agent["name"] for agent in listed.json()] == ["SEO Agent"]

    by_id = client.get(f"/api/v1/agents/{agent_id}")
    assert by_id.status_code == 200
    assert by_id.json()["purpose"] == "Research SEO keywords and analyze website SEO."

    missing = client.get("/api/v1/agents/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_permission_enforcement_via_api(api) -> None:
    """Creating a dangerous-capability agent without authorization is rejected."""
    client = api
    response = client.post(
        "/api/v1/agents",
        json={
            "name": "Unauthorized Calculator",
            "purpose": "Calculate sums.",
            "required_capabilities": ["calculation"],
        },
    )

    assert response.status_code == 422
    assert "dangerous permissions require explicit authorization" in response.json()["detail"]

    authorized = client.post(
        "/api/v1/agents",
        json={
            "name": "Authorized Calculator",
            "purpose": "Calculate sums.",
            "required_capabilities": ["calculation"],
            "permissions": ["EXECUTE_CODE"],
        },
    )
    assert authorized.status_code == 201
    assert authorized.json()["status"] == "ACTIVE"
    assert authorized.json()["permissions"] == ["EXECUTE_CODE"]


def test_enable_disable_and_execute_via_api(api) -> None:
    """Disabled agents reject execution; enabling re-activates them."""
    client = api
    created = client.post(
        "/api/v1/agents",
        json={
            "name": "Calculation Agent",
            "purpose": "Calculate sums.",
            "required_capabilities": ["calculation"],
            "permissions": ["EXECUTE_CODE"],
        },
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]

    disabled = client.post(f"/api/v1/agents/{agent_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "DISABLED"

    executed = client.post(
        f"/api/v1/agents/{agent_id}/execute",
        json={"goal": "Sum 2 and 3", "input": {"a": 2, "b": 3}},
    )
    assert executed.status_code == 400
    assert "not ACTIVE" in executed.json()["detail"]

    enabled = client.post(f"/api/v1/agents/{agent_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "ACTIVE"

    executed = client.post(
        f"/api/v1/agents/{agent_id}/execute",
        json={"goal": "Sum 2 and 3", "input": {"a": 2, "b": 3}},
    )
    assert executed.status_code == 200
    assert executed.json()["results"]["calculation"] == {"result": 5.0}
    assert executed.json()["errors"] == []


def test_resolve_and_execute_sum_agent_via_api(api) -> None:
    """Requirement -> resolve -> create -> execute returns the correct result."""
    client = api
    resolved = client.post(
        "/api/v1/agents/resolve",
        json={"requirement": "Create an agent capable of calculating the sum of two numbers."},
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["agent"] is None
    spec = body["specification"]
    assert spec is not None
    assert spec["capabilities"] == ["calculation"]

    created = client.post(
        "/api/v1/agents",
        json={
            "name": spec["name"],
            "purpose": spec["purpose"],
            "required_capabilities": spec["capabilities"],
            "permissions": ["EXECUTE_CODE"],
        },
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]

    executed = client.post(
        f"/api/v1/agents/{agent_id}/execute",
        json={"goal": "Sum 40 and 2", "input": {"a": 40, "b": 2}},
    )
    assert executed.status_code == 200
    assert executed.json()["results"]["calculation"] == {"result": 42.0}

    # A second resolve now finds the existing agent instead of a spec.
    resolved_again = client.post(
        "/api/v1/agents/resolve",
        json={"requirement": "Create an agent capable of calculating the sum of two numbers."},
    )
    assert resolved_again.status_code == 200
    assert resolved_again.json()["agent"]["name"] == "Calculation Agent"


def test_resolve_unresolvable_requirement_via_api(api) -> None:
    """An unresolvable requirement returns a clear 400."""
    client = api
    response = client.post(
        "/api/v1/agents/resolve",
        json={"requirement": "xyzzy zork"},
    )
    assert response.status_code == 400
    assert "no capabilities could be resolved" in response.json()["detail"]
