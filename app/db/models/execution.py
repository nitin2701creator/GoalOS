"""
Execution database model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.task import Task


class ExecutionStatus(str, Enum):
    """Supported lifecycle states for executions."""

    PENDING = "Pending"
    RUNNING = "Running"
    COMPLETED = "Completed"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    RETRYING = "Retrying"


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(
        SQLEnum(
            ExecutionStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="execution_status",
        ),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verification_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Autonomous loop persistence (state machine + artifacts)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_results: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_results: Mapped[str | None] = mapped_column(Text, nullable=True)
    commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    task: Mapped["Task"] = relationship(back_populates="executions")
