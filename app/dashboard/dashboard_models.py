"""Read models returned by the CEO dashboard."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.goal import GoalResponse
from app.schemas.objective import ObjectiveResponse
from app.schemas.project import ProjectResponse
from app.schemas.task import TaskResponse


class ExecutiveSummaryModel(BaseModel):
    """Top-level counts that executives need at a glance."""

    active_goals: int
    active_projects: int
    tasks_due_today: int


class IntegrationStatusModel(BaseModel):
    """Current connection state for the dashboard's known integrations."""

    email: str = "Not Connected"
    woocommerce: str = "Not Connected"
    crm: str = "Not Connected"
    meta: str = "Not Connected"
    ga4: str = "Not Connected"


class DashboardModel(BaseModel):
    """Complete read-only CEO dashboard response."""

    executive_summary: ExecutiveSummaryModel
    today_priorities: list[TaskResponse] = Field(default_factory=list)
    goal_progress: list[GoalResponse] = Field(default_factory=list)
    objectives_progress: list[ObjectiveResponse] = Field(default_factory=list)
    project_summary: list[ProjectResponse] = Field(default_factory=list)
    tasks_due: list[TaskResponse] = Field(default_factory=list)
    integrations: IntegrationStatusModel = Field(default_factory=IntegrationStatusModel)
    recommendations: list[str] = Field(default_factory=list)
