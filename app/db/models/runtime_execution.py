"""
Runtime execution database model.

A :class:`RuntimeExecution` records ONE capability execution through the
GoalOS execution runtime: the requested capability, the granted
permissions, the input parameters, the structured output or error, and
the full lifecycle timestamps. It is the persisted audit trail for the
capability engine — independent from the task-bound
:class:`Execution` model used by the autonomous development loop.

Statuses follow the canonical runtime lifecycle exactly:

``pending`` → ``running`` → ``succeeded`` | ``failed`` | ``blocked`` | ``cancelled``

- ``blocked``: the execution was pre-flighted and refused before any
  dispatch (missing permission, unconfigured integration, or unknown
  capability in a workflow step) — the honest ``INTEGRATION_NOT_CONFIGURED``
  / ``PERMISSION_DENIED`` / ``CAPABILITY_NOT_FOUND`` reason is persisted.
- ``cancelled``: the execution was in-flight (``pending``/``running``)
  when its owning workflow was cancelled.

``error_code`` carries the stable machine-readable failure code
(``INTEGRATION_NOT_CONFIGURED``, ``PERMISSION_DENIED``,
``CAPABILITY_NOT_FOUND``, ``WORKFLOW_INVALID``, ``EXECUTION_FAILED``, ...)
while ``error`` keeps the human-readable reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuntimeExecutionStatus(str, Enum):
    """Canonical lifecycle states of a capability execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RuntimeExecution(Base):
    """One persisted capability execution through the runtime."""

    __tablename__ = "runtime_executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Optional owning workflow; ad-hoc capability executions have none.
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    capability: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[RuntimeExecutionStatus] = mapped_column(
        SQLEnum(
            RuntimeExecutionStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="runtime_execution_status",
        ),
        nullable=False,
        default=RuntimeExecutionStatus.PENDING,
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Stable machine-readable failure code (e.g. INTEGRATION_NOT_CONFIGURED).
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    permissions_required: Mapped[list[Any]] = mapped_column(
        JSON, default=list, nullable=False
    )
    agent_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
