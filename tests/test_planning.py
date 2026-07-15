from fastapi.testclient import TestClient

from app.main import app
from app.services.planning_service import PlanningService
from app.schemas.planning import PlanningRequest


def test_planning_service_generate():
    request = PlanningRequest(
        vision="Scale AI planning",
        mission="Build deterministic planning foundation",
        business_goals=["Automate operations", "Increase transparency"],
        constraints=["No external calls"],
    )

    service = PlanningService()
    response = service.generate(request)

    assert response.objectives
    assert response.projects
    assert response.tasks
    assert response.workflows
    assert response.dependencies
    assert response.executions
    assert response.agent_requirements
    assert response.constraints == ["No external calls"]


def test_planning_endpoint():
    client = TestClient(app)
    payload = {
        "vision": "Scale AI planning",
        "mission": "Build deterministic planning foundation",
        "business_goals": ["Automate operations", "Increase transparency"],
        "constraints": ["No external calls"],
    }

    response = client.post("/api/v1/planning/generate", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "objectives" in data
    assert "projects" in data
    assert "tasks" in data
    assert "workflows" in data
    assert "dependencies" in data
    assert "executions" in data
    assert "agent_requirements" in data
    assert data["constraints"] == ["No external calls"]
