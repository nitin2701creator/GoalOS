"""
Integration persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.integration import Integration


class IntegrationRepository:
    """Database access for the persisted integration registry."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> Integration:
        integration = Integration(**values)
        self.db.add(integration)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(f"integration already exists: {values.get('name')}") from exc
        self.db.refresh(integration)
        return integration

    def get(self, integration_id: uuid.UUID) -> Integration | None:
        statement = select(Integration).where(Integration.id == integration_id)
        return self.db.scalars(statement).one_or_none()

    def get_by_name(self, name: str) -> Integration | None:
        statement = select(Integration).where(Integration.name == name)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Integration]:
        statement = select(Integration).order_by(Integration.name.asc())
        return self.db.scalars(statement).all()

    def update(self, integration: Integration, updates: dict[str, Any]) -> Integration:
        for field, value in updates.items():
            setattr(integration, field, value)
        self.db.commit()
        self.db.refresh(integration)
        return integration

    def delete(self, integration: Integration) -> None:
        self.db.delete(integration)
        self.db.commit()
