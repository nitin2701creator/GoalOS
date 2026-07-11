"""
Project persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.project import Project
from app.schemas.project import ProjectCreateRequest


class ProjectRepository:
    """Database access for projects."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, project_data: ProjectCreateRequest) -> Project:
        project = Project(**project_data.model_dump())
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def get(self, project_id: uuid.UUID) -> Project | None:
        statement = select(Project).where(Project.id == project_id)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Project]:
        statement = select(Project).order_by(Project.created_at.desc())
        return self.db.scalars(statement).all()

    def update(self, project: Project, updates: dict[str, Any]) -> Project:
        for field, value in updates.items():
            setattr(project, field, value)
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project: Project) -> None:
        self.db.delete(project)
        self.db.commit()
