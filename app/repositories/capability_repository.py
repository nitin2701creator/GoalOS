"""
Capability persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.capability import Capability


class CapabilityRepository:
    """Database access for persisted capability definitions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> Capability:
        capability = Capability(**values)
        self.db.add(capability)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(f"capability already exists: {values.get('name')}") from exc
        self.db.refresh(capability)
        return capability

    def get(self, capability_id: uuid.UUID) -> Capability | None:
        statement = select(Capability).where(Capability.id == capability_id)
        return self.db.scalars(statement).one_or_none()

    def get_by_name(self, name: str) -> Capability | None:
        statement = select(Capability).where(Capability.name == name)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Capability]:
        statement = select(Capability).order_by(Capability.name.asc())
        return self.db.scalars(statement).all()

    def update(self, capability: Capability, updates: dict[str, Any]) -> Capability:
        for field, value in updates.items():
            setattr(capability, field, value)
        self.db.commit()
        self.db.refresh(capability)
        return capability

    def delete(self, capability: Capability) -> None:
        self.db.delete(capability)
        self.db.commit()
