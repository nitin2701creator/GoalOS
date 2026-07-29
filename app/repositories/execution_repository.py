"""
Execution persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models.execution import Execution
from app.db.models.task import Task
from app.schemas.execution import ExecutionCreateRequest


class ExecutionRepository:
    """Database access for executions."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, execution_data: ExecutionCreateRequest) -> Execution:
        values = execution_data.model_dump()
        if values.get("status") is None:
            values.pop("status")
        execution = Execution(**values)
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def get(self, execution_id: uuid.UUID) -> Execution | None:
        statement = select(Execution).where(Execution.id == execution_id)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Execution]:
        statement = select(Execution).order_by(Execution.created_at.desc())
        return self.db.scalars(statement).all()

    def update(self, execution: Execution, updates: dict[str, Any]) -> Execution:
        for field, value in updates.items():
            setattr(execution, field, value)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def delete(self, execution: Execution) -> None:
        self.db.delete(execution)
        self.db.commit()

    def list_by_task(self, task_id: uuid.UUID) -> Sequence[Execution]:
        statement = (
            select(Execution)
            .where(Execution.task_id == task_id)
            .order_by(Execution.created_at.desc())
        )
        return self.db.scalars(statement).all()

    def latest_execution(self, task_id: uuid.UUID) -> Execution | None:
        statement = (
            select(Execution)
            .where(Execution.task_id == task_id)
            .order_by(desc(Execution.created_at))
            .limit(1)
        )
        return self.db.scalars(statement).one_or_none()

    def task_exists(self, task_id: uuid.UUID) -> bool:
        statement = select(Task.id).where(Task.id == task_id)
        return self.db.scalars(statement).one_or_none() is not None
