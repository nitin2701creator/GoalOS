"""Planning service orchestration for GoalOS."""

from __future__ import annotations

from app.llm.base_provider import BaseProvider
from app.planning.planner import Planner
from app.schemas.planning import PlanningRequest, PlanningResponse


class PlanningService:
    """Orchestrates planning generators using a provider abstraction.
    
    This service generates comprehensive plans from business vision, mission,
    goals, and constraints using deterministic planning generators.
    
    Attributes:
        provider: LLM provider for enriching planning outputs (optional).
        planner: Deterministic planner instance.
    """

    def __init__(self, provider: BaseProvider | None = None) -> None:
        """Initialize the planning service.
        
        Args:
            provider: Optional LLM provider for enriching outputs.
        """
        self.provider = provider
        self.planner = Planner()

    def generate(self, request: PlanningRequest) -> PlanningResponse:
        """Generate a complete plan from a planning request.
        
        Args:
            request: Planning request with vision, mission, goals, and constraints.
            
        Returns:
            Planning response with all generated artifacts.
        """
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
        """Generate a preview plan from individual parameters.
        
        Args:
            vision: Long-term business vision.
            mission: Operating mission.
            goals: List of business goals.
            constraints: Optional list of constraints.
            
        Returns:
            Planning response with all generated artifacts.
        """
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
            constraints=constraints if constraints else None,
        )

    def get_by_goal(
        self,
        goal_id: str,
        vision: str,
        mission: str,
        goals: list[str],
        constraints: list[str] | None = None,
    ) -> PlanningResponse:
        """Get planning filtered by a specific goal ID.
        
        Args:
            goal_id: The goal ID to filter by.
            vision: Long-term business vision.
            mission: Operating mission.
            goals: List of business goals.
            constraints: Optional list of constraints.
            
        Returns:
            Planning response filtered to the specified goal.
            
        Raises:
            ValueError: If the goal_id is not found in the planning.
        """
        planning = self.preview(vision=vision, mission=mission, goals=goals, constraints=constraints)
        filtered_objectives = [obj for obj in planning.objectives if str(obj.id) == goal_id]
        if not filtered_objectives:
            raise ValueError("Goal planning preview not found for the requested goal_id")

        filtered_projects = [project for project in planning.projects if str(project.goal_id) == goal_id]
        filtered_tasks = [
            task for task in planning.tasks
            if task.project_id in {project.id for project in filtered_projects}
        ]
        filtered_workflows = [
            workflow for workflow in planning.workflows
            if workflow.project_id in {project.id for project in filtered_projects}
        ]
        filtered_dependencies = [
            dependency for dependency in planning.dependencies
            if dependency["task_id"] in {task.id for task in filtered_tasks}
        ]
        filtered_executions = [
            execution for execution in planning.executions
            if execution.task_id in {task.id for task in filtered_tasks}
        ]

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
