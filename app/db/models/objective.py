"""
Objective database model.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.goal import Goal, GoalStatus


class Objective(Base):
    """Objective tracked under a parent Goal."""

    __tablename__ = "objectives"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    goal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(120), nullable=False)
    priority: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[GoalStatus] = mapped_column(
        SQLEnum(
            GoalStatus,
            values_callable=lambda enum_class: [status.value for status in enum_class],
            name="objective_status",
        ),
        nullable=False,
        default=GoalStatus.DRAFT,
    )
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="system",
        server_default="system",
    )
    updated_by: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        default="system",
        server_default="system",
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
    goal: Mapped[Goal] = relationship(back_populates="objectives")
