"""
Workflow database model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.task import Task


class WorkflowStatus(str, Enum):
    """Supported lifecycle states for workflows."""

    PENDING = "Pending"
    RUNNING = "Running"
    PAUSED = "Paused"
    FAILED = "Failed"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(
        SQLEnum(
            WorkflowStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="workflow_status",
        ),
        nullable=False,
        default=WorkflowStatus.PENDING,
    )
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Agent workflow run state: populated by WorkflowService.run_agent_workflow.
    requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_capabilities: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: Ordered goal plan (list of PlanStep dicts) driving sequential,
    #: result-chained execution; populated by the goal planner.
    plan: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    steps: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    results: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    evaluation: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Scheduler state: persisted scheduled runs survive application restart.
    schedule: Mapped[str | None] = mapped_column(String(20), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Run-instance link: when this workflow is a scheduled/retried run
    #: instance, points at the workflow it was cloned from (the template).
    scheduled_from_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tasks: Mapped[list[Task]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
