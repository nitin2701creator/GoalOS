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
        vision = request.vision
        mission = request.mission
        goals = request.business_goals
        constraints = request.constraints or []

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
