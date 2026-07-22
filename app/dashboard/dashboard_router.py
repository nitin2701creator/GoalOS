"""HTTP endpoint for the CEO dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dashboard.dashboard_models import DashboardModel
from app.dashboard.dashboard_service import DashboardService
from app.db.session import get_db
from app.repositories.goal_repository import GoalRepository
from app.repositories.objective_repository import ObjectiveRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.services.goal_service import GoalService
from app.services.objective_service import ObjectiveService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService

router = APIRouter()


def _get_dashboard_service(db=Depends(get_db)) -> DashboardService:
    """Build the dashboard from the existing application service layer."""

    return DashboardService(
        goal_service=GoalService(GoalRepository(db)),
        objective_service=ObjectiveService(ObjectiveRepository(db)),
        project_service=ProjectService(ProjectRepository(db)),
        task_service=TaskService(TaskRepository(db)),
    )


@router.get("/dashboard", response_model=DashboardModel, tags=["dashboard"])
def get_dashboard(service: DashboardService = Depends(_get_dashboard_service)) -> DashboardModel:
    return service.get_dashboard()
