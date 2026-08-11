"""
Agent database model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.agents.agent_definitions import AgentStatus
from app.db.base import Base


class Agent(Base):
    """Persisted, validated agent definition managed by the agent factory."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    system_instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    skills: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    tools: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    integrations: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    allowed_actions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    permissions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    dependencies: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[AgentStatus] = mapped_column(
        SQLEnum(
            AgentStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="agent_status",
        ),
        nullable=False,
        default=AgentStatus.DRAFT,
    )
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
