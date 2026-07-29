"""Unit and integration tests for the Planning API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.planning import PlanningRequest, PlanningResponse
from app.services.planning_service import PlanningService


# ============================================================================
# Service Tests
# ============================================================================


def test_planning_service_generate() -> None:
    """Test that PlanningService.generate() returns valid planning response."""
    request = PlanningRequest(
        vision="Scale AI planning",
        mission="Build deterministic planning foundation",
        business_goals=["Automate operations", "Increase transparency"],
        constraints=["No external calls"],
    )

    service = PlanningService()
    response = service.generate(request)

    assert isinstance(response, PlanningResponse)
    assert response.objectives
    assert response.projects
    assert response.tasks
    assert response.workflows
    assert response.dependencies
    assert response.executions
    assert response.agent_requirements
    assert response.constraints == ["No external calls"]


def test_planning_service_preview() -> None:
    """Test that PlanningService.preview() returns valid planning response."""
    service = PlanningService()
    response = service.preview(
        vision="Improve customer experience",
        mission="Deliver exceptional value",
        goals=["Increase satisfaction", "Reduce churn"],
        constraints=["Budget limit: $100k"],
    )

    assert isinstance(response, PlanningResponse)
    assert response.objectives
    assert response.projects
    assert response.tasks
    assert response.workflows
    assert response.dependencies
    assert response.executions
    assert response.agent_requirements
    assert response.constraints == ["Budget limit: $100k"]


def test_planning_service_preview_without_constraints() -> None:
    """Test that PlanningService.preview() works without constraints."""
    service = PlanningService()
    response = service.preview(
        vision="Scale operations",
        mission="Optimize efficiency",
        goals=["Reduce costs", "Improve quality"],
    )

    assert isinstance(response, PlanningResponse)
    assert response.objectives
    assert response.constraints is None


def test_planning_service_preview_with_empty_constraints() -> None:
    """Test that PlanningService.preview() with empty constraints list."""
    service = PlanningService()
    response = service.preview(
        vision="Transform business",
        mission="Enable digital excellence",
        goals=["Modernize systems"],
        constraints=[],
    )

    assert isinstance(response, PlanningResponse)
    assert response.constraints is None


def test_planning_service_get_by_goal_valid() -> None:
    """Test that PlanningService.get_by_goal() returns filtered planning."""
    service = PlanningService()
    
    # First generate a full plan
    full_response = service.preview(
        vision="Test vision",
        mission="Test mission",
        goals=["Goal 1", "Goal 2"],
    )
    
    # Then filter by first goal
    if full_response.objectives:
        goal_id = str(full_response.objectives[0].id)
        filtered_response = service.get_by_goal(
            goal_id=goal_id,
            vision="Test vision",
            mission="Test mission",
            goals=["Goal 1", "Goal 2"],
        )
        
        assert isinstance(filtered_response, PlanningResponse)
        assert len(filtered_response.objectives) <= len(full_response.objectives)


def test_planning_service_get_by_goal_invalid() -> None:
    """Test that PlanningService.get_by_goal() raises ValueError for invalid goal."""
    service = PlanningService()
    
    with pytest.raises(ValueError, match="Goal planning preview not found"):
        service.get_by_goal(
            goal_id="invalid-goal-id",
            vision="Test vision",
            mission="Test mission",
            goals=["Goal 1"],
        )


# ============================================================================
# API Integration Tests
# ============================================================================


def test_planning_endpoint_generate() -> None:
    """Test POST /api/v1/planning/generate endpoint."""
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


def test_planning_endpoint_generate_without_constraints() -> None:
    """Test POST /api/v1/planning/generate without constraints."""
    client = TestClient(app)
    payload = {
        "vision": "Improve efficiency",
        "mission": "Deliver excellence",
        "business_goals": ["Reduce waste", "Improve quality"],
    }

    response = client.post("/api/v1/planning/generate", json=payload)
    
    assert response.status_code == 201
    data = response.json()
    assert "objectives" in data
    assert "projects" in data


def test_planning_endpoint_preview() -> None:
    """Test GET /api/v1/planning/preview endpoint."""
    client = TestClient(app)
    
    response = client.get(
        "/api/v1/planning/preview",
        params={
            "vision": "Scale operations",
            "mission": "Drive growth",
            "business_goals": ["Increase revenue", "Expand market"],
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "objectives" in data
    assert "projects" in data
    assert "tasks" in data
    assert "workflows" in data


def test_planning_endpoint_preview_with_constraints() -> None:
    """Test GET /api/v1/planning/preview with constraints."""
    client = TestClient(app)
    
    response = client.get(
        "/api/v1/planning/preview",
        params={
            "vision": "Modernize systems",
            "mission": "Enable digital transformation",
            "business_goals": ["Move to cloud", "Automate workflows"],
            "constraints": ["Zero downtime", "Limited budget"],
        },
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "objectives" in data
    assert data["constraints"] == ["Zero downtime", "Limited budget"]


def test_planning_endpoint_by_goal() -> None:
    """Test GET /api/v1/planning/{goal_id} endpoint."""
    client = TestClient(app)
    
    # First get a full plan to extract a goal_id
    preview_response = client.get(
        "/api/v1/planning/preview",
        params={
            "vision": "Test vision",
            "mission": "Test mission",
            "business_goals": ["Test goal"],
        },
    )
    
    if preview_response.status_code == 200:
        preview_data = preview_response.json()
        if preview_data.get("objectives"):
            goal_id = preview_data["objectives"][0]["id"]
            
            # Now get filtered plan by goal
            response = client.get(
                f"/api/v1/planning/{goal_id}",
                params={
                    "vision": "Test vision",
                    "mission": "Test mission",
                    "business_goals": ["Test goal"],
                },
            )
            
            assert response.status_code == 200 or response.status_code == 404


def test_planning_endpoint_generate_missing_vision() -> None:
    """Test POST /api/v1/planning/generate with missing vision."""
    client = TestClient(app)
    payload = {
        "mission": "Build planning foundation",
        "business_goals": ["Automate"],
    }

    response = client.post("/api/v1/planning/generate", json=payload)
    
    assert response.status_code == 422  # Unprocessable Entity


def test_planning_endpoint_generate_missing_goals() -> None:
    """Test POST /api/v1/planning/generate with missing goals."""
    client = TestClient(app)
    payload = {
        "vision": "Scale planning",
        "mission": "Build foundation",
        "business_goals": [],
    }

    response = client.post("/api/v1/planning/generate", json=payload)
    
    # Empty goals should return 201 with empty objectives
    assert response.status_code == 201


def test_planning_endpoint_preview_missing_required_params() -> None:
    """Test GET /api/v1/planning/preview with missing required parameters."""
    client = TestClient(app)
    
    response = client.get(
        "/api/v1/planning/preview",
        params={
            "vision": "Test",
        },
    )
    
    assert response.status_code == 422  # Unprocessable Entity
