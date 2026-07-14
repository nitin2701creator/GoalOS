"""
Task persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.project import Project
from app.db.models.task import Task
from app.schemas.task import TaskCreateRequest


class TaskRepository:
    """Database access for tasks."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, task_data: TaskCreateRequest) -> Task:
        values = task_data.model_dump()
        if values.get("status") is None:
            values.pop("status")
        task = Task(**values)
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def get(self, task_id: uuid.UUID) -> Task | None:
        statement = select(Task).where(Task.id == task_id)
        return self.db.scalars(statement).one_or_none()

    def project_exists(self, project_id: uuid.UUID) -> bool:
        statement = select(Project.id).where(Project.id == project_id)
        return self.db.scalars(statement).one_or_none() is not None

    def list(self) -> Sequence[Task]:
        statement = select(Task).order_by(Task.created_at.desc())
        return self.db.scalars(statement).all()

    def update(self, task: Task, updates: dict[str, Any]) -> Task:
        for field, value in updates.items():
            setattr(task, field, value)
        self.db.commit()
        self.db.refresh(task)
        return task

    def delete(self, task: Task) -> None:
        self.db.delete(task)
        self.db.commit()

    def list_by_project(self, project_id: uuid.UUID) -> Sequence[Task]:
        statement = (
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.created_at.desc())
        )
        return self.db.scalars(statement).all()
