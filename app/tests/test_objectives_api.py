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
        "title": "Grow recurring revenue",
        "description": "Parent goal for objectives.",
        "executive_owner": "CEO",
        "department": "Executive",
        "priority": "critical",
        "status": "Draft",
        "target_date": "2026-12-31",
    }


def objective_payload(goal_id: str, status: str = "Draft") -> dict[str, str]:
    return {
        "goal_id": goal_id,
        "title": "Reduce churn",
        "description": "Improve retention through customer success.",
        "owner": "COO",
        "department": "Customer Success",
        "priority": "high",
        "status": status,
        "target_date": "2026-12-31",
    }


def create_goal(client: TestClient) -> dict[str, object]:
    response = client.post("/api/v1/goals", json=goal_payload())
    assert response.status_code == 201
    return response.json()


def test_create_objective_defaults_audit_fields(client: TestClient):
    goal = create_goal(client)

    response = client.post("/api/v1/objectives", json=objective_payload(goal["id"]))

    assert response.status_code == 201
    data = response.json()
    assert data["goal_id"] == goal["id"]
    assert data["created_by"] == "system"
    assert data["updated_by"] == "system"


def test_create_objective_requires_valid_goal(client: TestClient):
    response = client.post(
        "/api/v1/objectives",
        json=objective_payload(str(uuid.uuid4())),
    )

    assert response.status_code == 404


def test_list_objectives(client: TestClient):
    goal = create_goal(client)
    client.post("/api/v1/objectives", json=objective_payload(goal["id"]))

    response = client.get("/api/v1/objectives")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_objective(client: TestClient):
    goal = create_goal(client)
    created = client.post("/api/v1/objectives", json=objective_payload(goal["id"])).json()

    response = client.get(f"/api/v1/objectives/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_update_objective_updates_audit_user(client: TestClient):
    goal = create_goal(client)
    created = client.post("/api/v1/objectives", json=objective_payload(goal["id"])).json()

    response = client.put(
        f"/api/v1/objectives/{created['id']}",
        json={"status": "Active", "updated_by": "planner"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Active"
    assert data["updated_by"] == "planner"


def test_delete_objective(client: TestClient):
    goal = create_goal(client)
    created = client.post("/api/v1/objectives", json=objective_payload(goal["id"])).json()

    delete_response = client.delete(f"/api/v1/objectives/{created['id']}")
    get_response = client.get(f"/api/v1/objectives/{created['id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


def test_objective_belongs_to_goal(client: TestClient):
    goal = create_goal(client)
    created = client.post("/api/v1/objectives", json=objective_payload(goal["id"])).json()

    response = client.get(f"/api/v1/goals/{goal['id']}/objectives")

    assert response.status_code == 200
    objectives = response.json()
    assert len(objectives) == 1
    assert objectives[0]["goal_id"] == goal["id"]
    assert objectives[0]["id"] == created["id"]


def test_goal_delete_cascades_objectives(client: TestClient):
    goal = create_goal(client)
    created = client.post("/api/v1/objectives", json=objective_payload(goal["id"])).json()

    delete_goal_response = client.delete(f"/api/v1/goals/{goal['id']}")
    get_objective_response = client.get(f"/api/v1/objectives/{created['id']}")

    assert delete_goal_response.status_code == 204
    assert get_objective_response.status_code == 404


def test_objective_endpoints_are_in_openapi_schema(client: TestClient):
    response = client.get("/openapi.json")
    paths = response.json()["paths"]

    assert "/api/v1/objectives" in paths
    assert "/api/v1/objectives/{objective_id}" in paths
