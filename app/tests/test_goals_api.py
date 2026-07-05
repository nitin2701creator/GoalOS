import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def database() -> Generator[None, None, None]:
    Base.metadata.create_all(bind=engine)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def goal_payload() -> dict[str, str]:
    return {
        "title": "Reach ₹1 crore monthly revenue",
        "description": "Build a permanent operating goal for revenue growth.",
        "executive_owner": "CEO",
        "department": "Executive",
        "priority": "critical",
        "status": "Draft",
        "target_date": "2026-12-31",
    }


def test_create_goal(client: TestClient):
    response = client.post("/api/v1/goals", json=goal_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["title"] == "Reach ₹1 crore monthly revenue"
    assert data["company_id"] is None
    assert data["status"] == "Draft"
    assert data["created_at"]
    assert data["updated_at"]


def test_list_goals(client: TestClient):
    client.post("/api/v1/goals", json=goal_payload())

    response = client.get("/api/v1/goals")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_goal(client: TestClient):
    created = client.post("/api/v1/goals", json=goal_payload()).json()

    response = client.get(f"/api/v1/goals/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_update_goal(client: TestClient):
    created = client.post("/api/v1/goals", json=goal_payload()).json()

    response = client.put(
        f"/api/v1/goals/{created['id']}",
        json={"status": "Active", "department": "Sales"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Active"
    assert data["department"] == "Sales"


def test_delete_goal(client: TestClient):
    created = client.post("/api/v1/goals", json=goal_payload()).json()

    delete_response = client.delete(f"/api/v1/goals/{created['id']}")
    get_response = client.get(f"/api/v1/goals/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


def test_goal_not_found(client: TestClient):
    missing_id = uuid.uuid4()

    response = client.get(f"/api/v1/goals/{missing_id}")

    assert response.status_code == 404


def test_goals_endpoints_are_in_openapi_schema(client: TestClient):
    response = client.get("/openapi.json")
    paths = response.json()["paths"]

    assert "/api/v1/goals" in paths
    assert "/api/v1/goals/{goal_id}" in paths
