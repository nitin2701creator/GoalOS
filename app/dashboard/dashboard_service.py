"""Read-only aggregation service for the CEO dashboard."""

from __future__ import annotations

from datetime import date

from app.dashboard.dashboard_models import (
    DashboardModel,
    ExecutiveSummaryModel,
    IntegrationStatusModel,
)
from app.integrations.connector_registry import ConnectorRegistry
from app.schemas.goal import GoalResponse
from app.schemas.objective import ObjectiveResponse
from app.schemas.project import ProjectResponse
from app.schemas.task import TaskResponse
from app.services.goal_service import GoalService
from app.services.objective_service import ObjectiveService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService


class DashboardService:
    """Compose existing GoalOS services into a single executive view."""

    _COMPLETED_STATUSES = {"completed", "cancelled"}
    _ACTIVE_STATUS = "active"
    _KNOWN_INTEGRATIONS = ("email", "woocommerce", "crm", "meta", "ga4")
    _PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(
        self,
        goal_service: GoalService,
        objective_service: ObjectiveService,
        project_service: ProjectService,
        task_service: TaskService,
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self.goal_service = goal_service
        self.objective_service = objective_service
        self.project_service = project_service
        self.task_service = task_service
        self.connector_registry = connector_registry

    def get_dashboard(self, today: date | None = None) -> DashboardModel:
        """Return an immediately useful dashboard from current GoalOS data."""

        current_day = today or date.today()
        goals = self.goal_service.list()
        objectives = self.objective_service.list()
        projects = self.project_service.list()
        tasks = self.task_service.list()

        due_today = [task for task in tasks if task.due_date == current_day]
        priorities = sorted(
            (
                task for task in tasks
                if task.due_date is not None
                and task.due_date <= current_day
                and not self._is_completed(task.status)
            ),
            key=lambda task: (
                task.due_date or current_day,
                self._PRIORITY_ORDER.get(task.priority.casefold(), len(self._PRIORITY_ORDER)),
                task.title.casefold(),
            ),
        )

        return DashboardModel(
            executive_summary=ExecutiveSummaryModel(
                active_goals=sum(self._is_active(goal.status) for goal in goals),
                active_projects=sum(self._is_active(project.status) for project in projects),
                tasks_due_today=len(due_today),
            ),
            today_priorities=priorities,
            goal_progress=goals,
            objectives_progress=objectives,
            project_summary=projects,
            tasks_due=due_today,
            integrations=self._integration_statuses(),
            recommendations=self._recommendations(goals, objectives, projects, tasks, current_day),
        )

    def _integration_statuses(self) -> IntegrationStatusModel:
        statuses: dict[str, str] = {}
        for name in self._KNOWN_INTEGRATIONS:
            connector = self.connector_registry.get_connector(name) if self.connector_registry else None
            statuses[name] = "Connected" if connector is not None and connector.is_connected() else "Not Connected"
        return IntegrationStatusModel(**statuses)

    def _recommendations(
        self,
        goals: list[GoalResponse],
        objectives: list[ObjectiveResponse],
        projects: list[ProjectResponse],
        tasks: list[TaskResponse],
        current_day: date,
    ) -> list[str]:
        recommendations: list[str] = []
        active_projects_by_goal = {
            project.goal_id for project in projects if self._is_active(project.status) and project.goal_id is not None
        }
        objectives_by_goal = {objective.goal_id for objective in objectives}
        project_titles = {project.id: project.title for project in projects}

        for goal in goals:
            if self._is_active(goal.status) and goal.id not in active_projects_by_goal:
                recommendations.append(f"Goal {goal.title} has no active projects.")
            if goal.id not in objectives_by_goal:
                recommendations.append(f"No objectives assigned to Goal {goal.title}.")

        overdue_project_ids = {
            task.project_id
            for task in tasks
            if task.due_date is not None and task.due_date < current_day and not self._is_completed(task.status)
        }
        for project in projects:
            if project.id in overdue_project_ids:
                recommendations.append(f"Project {project_titles[project.id]} has overdue tasks.")
        return recommendations

    @classmethod
    def _is_active(cls, status: str) -> bool:
        return status.casefold() == cls._ACTIVE_STATUS

    @classmethod
    def _is_completed(cls, status: str) -> bool:
        return status.casefold() in cls._COMPLETED_STATUSES
