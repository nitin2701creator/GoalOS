from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel

from app.schemas.goal import GoalResponse
from app.schemas.objective import ObjectiveResponse
from app.schemas.project import ProjectResponse
from app.schemas.task import TaskResponse
from app.schemas.workflow import WorkflowResponse
from app.schemas.execution import ExecutionResponse


class PlanningRequest(BaseModel):
    vision: str
    mission: str
    business_goals: List[str]
    constraints: Optional[List[str]] = None


class PlanningResponse(BaseModel):
    objectives: List[ObjectiveResponse]
    kpis: List[dict]
    projects: List[ProjectResponse]
    tasks: List[TaskResponse]
    workflows: List[WorkflowResponse]
    dependencies: List[dict]
    executions: List[ExecutionResponse]
    agent_requirements: List[dict]
    constraints: Optional[List[str]]

    model_config = {"from_attributes": True}
