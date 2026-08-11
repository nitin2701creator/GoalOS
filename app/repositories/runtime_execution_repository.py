"""
Runtime execution persistence repository.

Follows the existing repository conventions (session-injected, plain
SQLAlchemy 2.0 ``select`` statements, commit-and-refresh on writes).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.runtime_execution import RuntimeExecution, RuntimeExecutionStatus


class RuntimeExecutionRepository:
    """Database access for capability runtime executions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> RuntimeExecution:
        execution = RuntimeExecution(**values)
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def get(self, execution_id: uuid.UUID) -> RuntimeExecution | None:
        statement = select(RuntimeExecution).where(RuntimeExecution.id == execution_id)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[RuntimeExecution]:
        statement = select(RuntimeExecution).order_by(RuntimeExecution.created_at.desc())
        return self.db.scalars(statement).all()

    def list_by_workflow(self, workflow_id: uuid.UUID) -> Sequence[RuntimeExecution]:
        statement = (
            select(RuntimeExecution)
            .where(RuntimeExecution.workflow_id == workflow_id)
            .order_by(RuntimeExecution.created_at.asc())
        )
        return self.db.scalars(statement).all()

    def list_by_capability(self, capability: str) -> Sequence[RuntimeExecution]:
        statement = (
            select(RuntimeExecution)
            .where(RuntimeExecution.capability == capability)
            .order_by(RuntimeExecution.created_at.desc())
        )
        return self.db.scalars(statement).all()

    def update(self, execution: RuntimeExecution, updates: dict[str, Any]) -> RuntimeExecution:
        for field, value in updates.items():
            setattr(execution, field, value)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def delete(self, execution: RuntimeExecution) -> None:
        self.db.delete(execution)
        self.db.commit()

    def active_for_workflow(self, workflow_id: uuid.UUID) -> RuntimeExecution | None:
        """Return an in-flight execution for a workflow, if any.

        In-flight means ``pending`` or ``running`` — the states in which a
        second submission for the same workflow would duplicate work.
        """
        statement = (
            select(RuntimeExecution)
            .where(RuntimeExecution.workflow_id == workflow_id)
            .where(
                RuntimeExecution.status.in_(
                    (RuntimeExecutionStatus.PENDING, RuntimeExecutionStatus.RUNNING)
                )
            )
            .order_by(RuntimeExecution.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(statement).one_or_none()

    def list_in_flight(self) -> Sequence[RuntimeExecution]:
        """Return every in-flight (pending/running) execution."""
        statement = (
            select(RuntimeExecution)
            .where(
                RuntimeExecution.status.in_(
                    (RuntimeExecutionStatus.PENDING, RuntimeExecutionStatus.RUNNING)
                )
            )
            .order_by(RuntimeExecution.created_at.asc())
        )
        return self.db.scalars(statement).all()

    def cancel_in_flight(self, workflow_id: uuid.UUID) -> Sequence[RuntimeExecution]:
        """Mark every in-flight execution of a workflow as cancelled.

        Returns the executions that were cancelled (an empty sequence when
        there were none). Used when a workflow is cancelled so no orphaned
        in-flight execution can later claim success.
        """
        statement = (
            select(RuntimeExecution)
            .where(RuntimeExecution.workflow_id == workflow_id)
            .where(
                RuntimeExecution.status.in_(
                    (RuntimeExecutionStatus.PENDING, RuntimeExecutionStatus.RUNNING)
                )
            )
        )
        executions = list(self.db.scalars(statement).all())
        for execution in executions:
            execution.status = RuntimeExecutionStatus.CANCELLED
            execution.error = "execution cancelled with its workflow"
            execution.error_code = "CANCELLED"
            execution.completed_at = datetime.now(timezone.utc)
        if executions:
            self.db.commit()
            for execution in executions:
                self.db.refresh(execution)
        return executions
