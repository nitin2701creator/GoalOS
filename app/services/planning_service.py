"""Planning service orchestration for GoalOS."""

from __future__ import annotations

from app.llm.base_provider import BaseProvider
from app.planning.planner import Planner
from app.schemas.planning import PlanningRequest, PlanningResponse


class PlanningService:
    """Orchestrates planning generators using a provider abstraction."""

    def __init__(self, provider: BaseProvider | None = None) -> None:
        self.provider = provider
        self.planner = Planner()

    def generate(self, request: PlanningRequest) -> PlanningResponse:
        return self.preview(
            vision=request.vision,
            mission=request.mission,
            goals=request.business_goals,
            constraints=request.constraints,
        )

    def preview(
        self,
        vision: str,
        mission: str,
        goals: list[str],
        constraints: list[str] | None = None,
    ) -> PlanningResponse:
        constraints = constraints or []

        objectives = self.planner.generate_objectives(vision, mission, goals)
        kpis = self.planner.generate_kpis(vision, mission, goals)
        projects = self.planner.generate_projects(objectives)
        tasks = self.planner.generate_tasks(projects)
        workflows = self.planner.generate_workflows(projects, tasks)
        dependencies = self.planner.generate_dependencies(tasks)
        executions = self.planner.generate_executions(tasks)
        agent_requirements = self.planner.generate_agents(vision, mission, goals)

        return PlanningResponse(
            objectives=objectives,
            kpis=kpis,
            projects=projects,
            tasks=tasks,
            workflows=workflows,
            dependencies=dependencies,
            executions=executions,
            agent_requirements=agent_requirements,
            constraints=constraints,
        )

    def get_by_goal(
        self,
        goal_id: str,
        vision: str,
        mission: str,
        goals: list[str],
        constraints: list[str] | None = None,
    ) -> PlanningResponse:
        planning = self.preview(vision=vision, mission=mission, goals=goals, constraints=constraints)
        filtered_objectives = [obj for obj in planning.objectives if str(obj.id) == goal_id]
        if not filtered_objectives:
            raise ValueError("Goal planning preview not found for the requested goal_id")

        filtered_projects = [project for project in planning.projects if str(project.goal_id) == goal_id]
        filtered_tasks = [task for task in planning.tasks if task.project_id in {project.id for project in filtered_projects}]
        filtered_workflows = [workflow for workflow in planning.workflows if workflow.project_id in {project.id for project in filtered_projects}]
        project_ids = {project.id for project in filtered_projects}
        filtered_dependencies = [dependency for dependency in planning.dependencies if dependency["task_id"] in {task.id for task in filtered_tasks}]
        filtered_executions = [execution for execution in planning.executions if execution.task_id in {task.id for task in filtered_tasks}]

        return PlanningResponse(
            objectives=filtered_objectives,
            kpis=planning.kpis,
            projects=filtered_projects,
            tasks=filtered_tasks,
            workflows=filtered_workflows,
            dependencies=filtered_dependencies,
            executions=filtered_executions,
            agent_requirements=planning.agent_requirements,
            constraints=planning.constraints,
        )
