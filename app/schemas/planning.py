"""Planning request and response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.schemas.execution import ExecutionResponse
from app.schemas.objective import ObjectiveResponse
from app.schemas.project import ProjectResponse
from app.schemas.task import TaskResponse
from app.schemas.workflow import WorkflowResponse


class PlanningRequest(BaseModel):
    """Request model for generating a plan from vision, mission, and goals.
    
    Attributes:
        vision: Long-term business vision for the planning.
        mission: Operating mission for the planning.
        business_goals: List of business goals to achieve.
        constraints: Optional list of constraints that limit the plan.
    """

    vision: str
    mission: str
    business_goals: list[str]
    constraints: list[str] | None = None


class PlanningResponse(BaseModel):
    """Response model containing generated planning artifacts.
    
    Attributes:
        objectives: List of generated objectives.
        kpis: List of key performance indicators.
        projects: List of generated projects.
        tasks: List of generated tasks.
        workflows: List of generated workflows.
        dependencies: List of task dependencies.
        executions: List of execution plans.
        agent_requirements: List of required agents.
        constraints: List of applied constraints.
    """

    objectives: list[ObjectiveResponse]
    kpis: list[dict[str, Any]]
    projects: list[ProjectResponse]
    tasks: list[TaskResponse]
    workflows: list[WorkflowResponse]
    dependencies: list[dict[str, Any]]
    executions: list[ExecutionResponse]
    agent_requirements: list[dict[str, Any]]
    constraints: list[str] | None = None

    model_config = {"from_attributes": True}
