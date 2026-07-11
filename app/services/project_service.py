"""
Project business service.
"""

from __future__ import annotations

import uuid

from app.db.models.project import Project
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectSummaryResponse, ProjectUpdateRequest


class ProjectService:
    """Business operations for projects."""

    def __init__(self, repository: ProjectRepository):
        self.repository = repository

    def _metrics(self, project: Project) -> int:
        execution_count = len(project.executions)
        return execution_count

    def _to_response(self, project: Project) -> ProjectResponse:
        return ProjectResponse(
            id=project.id,
            company_id=project.company_id,
            goal_id=project.goal_id,
            name=project.name,
            description=project.description,
            executive_owner=project.executive_owner,
            department=project.department,
            priority=project.priority,
            status=project.status,
            start_date=project.start_date,
            target_date=project.target_date,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    def create(self, request: ProjectCreateRequest) -> ProjectResponse:
        return self._to_response(self.repository.create(request))

    def get(self, project_id: uuid.UUID) -> ProjectResponse | None:
        project = self.repository.get(project_id)
        if project is None:
            return None
        return self._to_response(project)

    def list(self) -> list[ProjectResponse]:
        return [self._to_response(project) for project in self.repository.list()]

    def update(self, project_id: uuid.UUID, request: ProjectUpdateRequest) -> ProjectResponse | None:
        project = self.repository.get(project_id)
        if project is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(project)

        return self._to_response(self.repository.update(project, updates))

    def delete(self, project_id: uuid.UUID) -> bool:
        project = self.repository.get(project_id)
        if project is None:
            return False

        self.repository.delete(project)
        return True

    def summary(self, project_id: uuid.UUID) -> ProjectSummaryResponse | None:
        project = self.repository.get(project_id)
        if project is None:
            return None

        execution_count = self._metrics(project)
        return ProjectSummaryResponse(
            project=self._to_response(project),
            execution_count=execution_count,
        )
