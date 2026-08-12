"""
Capability database model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CapabilityStatus(str, Enum):
    """Lifecycle states of a registered capability."""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class Capability(Base):
    """Persisted capability registered with the GoalOS capability engine.

    The registry is the source of truth for what GoalOS can resolve and
    execute: every row carries its provider/implementation reference and
    permission requirements so resolution is honest (a row without a
    configured implementation reports INTEGRATION_NOT_CONFIGURED).
    """

    __tablename__ = "capabilities"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="general", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    status: Mapped[CapabilityStatus] = mapped_column(
        SQLEnum(
            CapabilityStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="capability_status",
        ),
        nullable=False,
        default=CapabilityStatus.ACTIVE,
    )
    required_permissions: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    provider_type: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    implementation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    execution_capability: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keywords: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
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
