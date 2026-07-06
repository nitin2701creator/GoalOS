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
        "title": "Reach monthly revenue target",
        "description": "Build a permanent operating goal for revenue growth.",
        "executive_owner": "CEO",
        "department": "Executive",
        "priority": "critical",
        "status": "Draft",
        "target_date": "2026-12-31",
    }


def create_goal(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/goals", json=goal_payload())
    assert response.status_code == 201
    return response.json()


def create_objective(client: TestClient, goal_id: str, status: str = "Draft") -> dict[str, object]:
    response = client.post(
        "/api/v1/objectives",
        json={
            "goal_id": goal_id,
            "title": "Objective",
            "description": "Support the goal.",
            "owner": "CEO",
            "department": "Executive",
            "priority": "critical",
            "status": status,
            "target_date": "2026-12-31",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_goal_returns_computed_metrics(client: TestClient):
    response = client.post("/api/v1/goals", json=goal_payload())

    assert response.status_code == 201
    data = response.json()
    assert data["id"]
    assert data["title"] == "Reach monthly revenue target"
    assert data["company_id"] is None
    assert data["status"] == "Draft"
    assert data["objective_count"] == 0
    assert data["completed_objective_count"] == 0
    assert data["progress_percentage"] == 0
    assert data["created_at"]
    assert data["updated_at"]


def test_list_goals_includes_progress_metrics(client: TestClient):
    create_goal(client)

    response = client.get("/api/v1/goals")

    assert response.status_code == 200
    goals = response.json()
    assert len(goals) == 1
    assert goals[0]["objective_count"] == 0
    assert goals[0]["progress_percentage"] == 0


def test_get_goal_includes_progress_metrics(client: TestClient):
    created = create_goal(client)

    response = client.get(f"/api/v1/goals/{created['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == created["id"]
    assert data["objective_count"] == 0
    assert data["completed_objective_count"] == 0
    assert data["progress_percentage"] == 0


def test_update_goal_includes_progress_metrics(client: TestClient):
    created = create_goal(client)

    response = client.put(
        f"/api/v1/goals/{created['id']}",
        json={"status": "Active", "department": "Sales"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Active"
    assert data["department"] == "Sales"
    assert data["objective_count"] == 0
    assert data["progress_percentage"] == 0


def test_delete_goal(client: TestClient):
    created = create_goal(client)

    delete_response = client.delete(f"/api/v1/goals/{created['id']}")
    get_response = client.get(f"/api/v1/goals/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


def test_goal_summary_computes_progress_from_objectives(client: TestClient):
    created = create_goal(client)

    for index in range(5):
        create_objective(client, created["id"], status="Completed" if index < 2 else "Draft")

    response = client.get(f"/api/v1/goals/{created['id']}/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["objective_count"] == 5
    assert data["completed_objective_count"] == 2
    assert data["progress_percentage"] == 40
    assert len(data["objectives"]) == 5
    assert data["goal"]["objective_count"] == 5
    assert data["goal"]["completed_objective_count"] == 2
    assert data["goal"]["progress_percentage"] == 40


def test_goal_objectives_nested_endpoint_lists_objectives(client: TestClient):
    created = create_goal(client)
    create_objective(client, created["id"])

    response = client.get(f"/api/v1/goals/{created['id']}/objectives")

    assert response.status_code == 200
    objectives = response.json()
    assert len(objectives) == 1
    assert objectives[0]["goal_id"] == created["id"]


def test_goal_endpoints_are_in_openapi_schema(client: TestClient):
    response = client.get("/openapi.json")
    paths = response.json()["paths"]

    assert "/api/v1/goals" in paths
    assert "/api/v1/goals/{goal_id}" in paths
    assert "/api/v1/goals/{goal_id}/objectives" in paths
    assert "/api/v1/goals/{goal_id}/summary" in paths


def test_goal_not_found(client: TestClient):
    missing_id = uuid.uuid4()

    response = client.get(f"/api/v1/goals/{missing_id}")

    assert response.status_code == 404
