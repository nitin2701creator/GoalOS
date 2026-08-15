"""
Integration database model.

A persisted, executable integration registered with GoalOS. One row per
registered connector captures the integration's identity (name, type,
description), its enabled/disabled state, the capabilities it exposes,
and the *names* of the environment variables that configure it — never
their values, so secrets stay out of the database and the source tree.

Health snapshots are cached here (``last_health_status`` /
``last_health_message`` / ``last_checked_at``) so the API can report the
last-known operational state without re-inspecting the environment on
every request. The runtime connector registry remains the source of
truth for live availability; this row is the durable, queryable
integration registry.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Integration(Base):
    """A registered integration exposed as executable capabilities."""

    __tablename__ = "integrations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Stable registry name (matches the connector registry key).
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    #: Functional type (web, email, crm, analytics, commerce, ...).
    integration_type: Mapped[str] = mapped_column(String(60), nullable=False, default="integration")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    #: Whether the integration may be executed (operator-controlled).
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Capability names the integration exposes (``web.search``, ...).
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    #: Environment variable NAMES configuring the integration (never values).
    required_env_vars: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    #: Cached health snapshot (value of ConnectorHealthStatus).
    last_health_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_health_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
