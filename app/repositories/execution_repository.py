"""
Execution persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select, update
from sqlalchemy.orm import Session

from app.db.models.execution import Execution, ExecutionStatus
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

    def active_execution(self, task_id: uuid.UUID) -> Execution | None:
        """Return an in-flight execution for ``task_id``, if any.

        In-flight means still pending, running, or retrying — exactly the
        states in which a second submission would duplicate work.
        """
        statement = (
            select(Execution)
            .where(Execution.task_id == task_id)
            .where(Execution.status.in_(
                (ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.RETRYING)
            ))
            .order_by(desc(Execution.created_at))
            .limit(1)
        )
        return self.db.scalars(statement).one_or_none()

    def claim(self, execution_id: uuid.UUID) -> Execution | None:
        """Atomically claim a pending execution for a worker.

        Only an execution still in ``Pending`` transitions to ``Running``;
        the conditional ``UPDATE`` prevents two workers from claiming the
        same execution. Returns the claimed execution, or ``None`` when the
        execution no longer exists or was already claimed/completed.
        """
        result = self.db.execute(
            update(Execution)
            .where(Execution.id == execution_id)
            .where(Execution.status == ExecutionStatus.PENDING)
            .values(status=ExecutionStatus.RUNNING, started_at=datetime.now(timezone.utc))
        )
        self.db.commit()
        if result.rowcount == 0:
            return None
        return self.get(execution_id)
