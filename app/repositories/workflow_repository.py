"""
Workflow persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models.project import Project
from app.db.models.workflow import Workflow
from app.schemas.workflow import WorkflowCreateRequest


class WorkflowRepository:
    """Database access for workflows."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, workflow_data: WorkflowCreateRequest) -> Workflow:
        workflow = Workflow(**workflow_data.model_dump())
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def get(self, workflow_id: uuid.UUID) -> Workflow | None:
        statement = select(Workflow).where(Workflow.id == workflow_id)
        return self.db.scalars(statement).one_or_none()

    def get_with_tasks(self, workflow_id: uuid.UUID) -> Workflow | None:
        statement = (
            select(Workflow)
            .options(selectinload(Workflow.tasks))
            .where(Workflow.id == workflow_id)
        )
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Workflow]:
        statement = select(Workflow).order_by(Workflow.created_at.desc())
        return self.db.scalars(statement).all()

    def list_by_project(self, project_id: uuid.UUID) -> Sequence[Workflow]:
        statement = (
            select(Workflow)
            .where(Workflow.project_id == project_id)
            .order_by(Workflow.created_at.desc())
        )
        return self.db.scalars(statement).all()

    def update(self, workflow: Workflow, updates: dict[str, Any]) -> Workflow:
        for field, value in updates.items():
            setattr(workflow, field, value)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def delete(self, workflow: Workflow) -> None:
        self.db.delete(workflow)
        self.db.commit()

    def project_exists(self, project_id: uuid.UUID) -> bool:
        statement = select(Project.id).where(Project.id == project_id)
        return self.db.scalars(statement).one_or_none() is not None
