"""
Agent persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.agent import Agent


class AgentRepository:
    """Database access for persisted agent definitions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> Agent:
        agent = Agent(**values)
        self.db.add(agent)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(f"agent already exists: {values.get('name')}") from exc
        self.db.refresh(agent)
        return agent

    def get(self, agent_id: uuid.UUID) -> Agent | None:
        statement = select(Agent).where(Agent.id == agent_id)
        return self.db.scalars(statement).one_or_none()

    def get_by_name(self, name: str) -> Agent | None:
        statement = select(Agent).where(Agent.name == name)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Agent]:
        statement = select(Agent).order_by(Agent.name.asc())
        return self.db.scalars(statement).all()

    def update(self, agent: Agent, updates: dict[str, Any]) -> Agent:
        for field, value in updates.items():
            setattr(agent, field, value)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def delete(self, agent: Agent) -> None:
        self.db.delete(agent)
        self.db.commit()
