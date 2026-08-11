"""
Skill database model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Skill(Base):
    """Persisted, reusable skill definition managed by the agent factory."""

    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    required_tools: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    required_integrations: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    permissions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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
