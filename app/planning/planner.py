"""Planning foundation for GoalOS."""

from __future__ import annotations

from app.planning.objective_generator import ObjectiveGenerator
from app.planning.project_generator import ProjectGenerator
from app.planning.task_generator import TaskGenerator
from app.planning.workflow_generator import WorkflowGenerator
from app.planning.dependency_generator import DependencyGenerator
from app.planning.execution_generator import ExecutionGenerator
from app.planning.kpi_generator import KPIGenerator
from app.planning.agent_generator import AgentGenerator


class Planner:
    """Orchestrates deterministic planning components."""

    def __init__(self) -> None:
        self.objective_generator = ObjectiveGenerator()
        self.project_generator = ProjectGenerator()
        self.task_generator = TaskGenerator()
        self.workflow_generator = WorkflowGenerator()
        self.dependency_generator = DependencyGenerator()
        self.execution_generator = ExecutionGenerator()
        self.kpi_generator = KPIGenerator()
        self.agent_generator = AgentGenerator()

    def generate_objectives(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        return self.objective_generator.generate(vision, mission, goals)

    def generate_kpis(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        return self.kpi_generator.generate(vision, mission, goals)

    def generate_projects(self, objectives: list[dict]) -> list[dict]:
        return self.project_generator.generate(objectives)

    def generate_tasks(self, projects: list[dict]) -> list[dict]:
        return self.task_generator.generate(projects)

    def generate_workflows(self, projects: list[dict], tasks: list[dict]) -> list[dict]:
        return self.workflow_generator.generate(projects, tasks)

    def generate_dependencies(self, tasks: list[dict]) -> list[dict]:
        return self.dependency_generator.generate(tasks)

    def generate_executions(self, tasks: list[dict]) -> list[dict]:
        return self.execution_generator.generate(tasks)

    def generate_agents(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        return self.agent_generator.generate(vision, mission, goals)
