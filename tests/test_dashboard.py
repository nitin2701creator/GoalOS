"""Tests for the read-only CEO dashboard."""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.dashboard.dashboard_router import _get_dashboard_service
from app.dashboard.dashboard_service import DashboardService
from app.integrations import ConnectorHealth, ConnectorHealthStatus, ConnectorRegistry
from app.integrations.email import EmailConnector
from app.main import app
from app.schemas.goal import GoalResponse
from app.schemas.objective import ObjectiveResponse
from app.schemas.project import ProjectResponse
from app.schemas.task import TaskResponse


class ListingService:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    def list(self) -> list[object]:
        return self.items


def _goal(title: str = "Grow Organigram", status: str = "Active") -> GoalResponse:
    now = datetime.now()
    return GoalResponse(
        id=uuid4(), company_id=None, title=title, description="", executive_owner="CEO",
        department="Executive", priority="High", status=status, target_date=None,
        objective_count=0, completed_objective_count=0, progress_percentage=0,
        created_at=now, updated_at=now,
    )


def _project(goal_id=None, title: str = "Launch dashboard", status: str = "Active") -> ProjectResponse:
    now = datetime.now()
    return ProjectResponse(
        id=uuid4(), goal_id=goal_id, company_id=None, title=title, description="", owner="CEO",
        department="Executive", priority="High", status=status, start_date=None, target_date=None,
        created_at=now, updated_at=now,
    )


def _task(project_id, due_date: date | None, status: str = "Active", priority: str = "High") -> TaskResponse:
    now = datetime.now()
    return TaskResponse(
        id=uuid4(), project_id=project_id, title="Review metrics", description="", assigned_agent=None,
        status=status, priority=priority, workflow_id=None, sequence_number=None,
        depends_on_task_id=None, execution_order=None, estimated_hours=None, actual_hours=None,
        due_date=due_date, result=None, created_at=now, updated_at=now,
    )


def _service(
    goals: list[GoalResponse], projects: list[ProjectResponse], tasks: list[TaskResponse],
    objectives: list[ObjectiveResponse] | None = None, registry: ConnectorRegistry | None = None,
) -> DashboardService:
    return DashboardService(
        ListingService(goals),  # type: ignore[arg-type]
        ListingService(objectives or []),  # type: ignore[arg-type]
        ListingService(projects),  # type: ignore[arg-type]
        ListingService(tasks),  # type: ignore[arg-type]
        registry,
    )


def test_dashboard_aggregates_current_goalos_data_and_recommendations() -> None:
    today = date(2026, 7, 21)
    goal = _goal()
    project = _project(goal.id)
    due_task = _task(project.id, today)
    overdue_task = _task(project.id, date(2026, 7, 20), priority="Critical")

    dashboard = _service([goal], [project], [due_task, overdue_task]).get_dashboard(today)

    assert dashboard.executive_summary.active_goals == 1
    assert dashboard.executive_summary.active_projects == 1
    assert dashboard.executive_summary.tasks_due_today == 1
    assert [task.id for task in dashboard.today_priorities] == [overdue_task.id, due_task.id]
    assert dashboard.tasks_due == [due_task]
    assert dashboard.goal_progress == [goal]
    assert dashboard.project_summary == [project]
    assert "No objectives assigned to Goal Grow Organigram." in dashboard.recommendations
    assert "Project Launch dashboard has overdue tasks." in dashboard.recommendations


def test_dashboard_recommends_active_goal_without_active_projects() -> None:
    goal = _goal()

    dashboard = _service([goal], [], []).get_dashboard(date(2026, 7, 21))

    assert "Goal Grow Organigram has no active projects." in dashboard.recommendations
    assert dashboard.integrations.email == "Not Connected"


def test_dashboard_reports_connected_registered_email_integration() -> None:
    registry = ConnectorRegistry()
    email = EmailConnector()
    email._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY))
    registry.register(email)

    dashboard = _service([], [], [], registry=registry).get_dashboard(date(2026, 7, 21))

    assert dashboard.integrations.email == "Connected"
    assert dashboard.integrations.crm == "Not Connected"


def test_dashboard_endpoint_returns_dashboard_model() -> None:
    service = _service([], [], [])
    app.dependency_overrides[_get_dashboard_service] = lambda: service
    try:
        response = TestClient(app).get("/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["executive_summary"] == {
        "active_goals": 0, "active_projects": 0, "tasks_due_today": 0,
    }
    assert response.json()["integrations"]["email"] == "Not Connected"
