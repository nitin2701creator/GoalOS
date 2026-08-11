"""Scheduler integration: persisted scheduled workflows.

Scheduled jobs are stored on the existing ``Workflow`` model, so they
survive application restart with no laptop process required. The
connector creates, lists, cancels, and queries due runs; the runtime (or
an operator) decides when to actually execute due runs through the
existing workflow orchestrator.

``scheduler.create`` requires explicit ``SCHEDULE_WORKFLOWS``
authorization and is never granted implicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.integration_connector import IntegrationConnector

_SUPPORTED_SCHEDULES = {"hourly", "daily", "weekly"}


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Normalize an ISO datetime string or aware datetime to UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def next_run_at(schedule: str, now: datetime | None = None) -> datetime:
    """Return the first future run time for a supported schedule."""
    schedule = schedule.strip().casefold()
    if schedule not in _SUPPORTED_SCHEDULES:
        raise ValueError(
            f"unsupported schedule '{schedule}'; supported: {', '.join(sorted(_SUPPORTED_SCHEDULES))}"
        )
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if schedule == "hourly":
        return now + timedelta(hours=1)
    if schedule == "daily":
        return now + timedelta(days=1)
    return now + timedelta(weeks=1)


class SchedulerConnector(IntegrationConnector):
    """Persist and query scheduled workflows in the GoalOS database."""

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "scheduler.create": Permission.SCHEDULE_WORKFLOWS,
        "scheduler.list": Permission.READ_ANALYTICS,
        "scheduler.cancel": Permission.READ_ANALYTICS,
        "scheduler.due": Permission.READ_ANALYTICS,
    }

    def __init__(self, db: Session | None = None) -> None:
        super().__init__(
            name="scheduler",
            description="Persisted GoalOS scheduled workflows",
        )
        self.db = db

    def _capabilities(self) -> tuple[str, ...]:
        return ("scheduler.create", "scheduler.list", "scheduler.cancel", "scheduler.due")

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if self.db is None:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "scheduler requires a database session",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "scheduler.create":
            return self.create(
                workflow_id=params["workflow_id"],
                schedule=params["schedule"],
                requirement=params.get("requirement", ""),
            )
        if capability == "scheduler.list":
            return {"scheduled": [self._row(workflow) for workflow in self._scheduled()]}
        if capability == "scheduler.cancel":
            return self.cancel(params["workflow_id"])
        if capability == "scheduler.due":
            return {"due": self.due_runs(_parse_datetime(params.get("now")) or datetime.now(timezone.utc))}
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def create(
        self,
        workflow_id: uuid.UUID,
        schedule: str,
        requirement: str = "",
    ) -> dict[str, Any]:
        """Schedule an existing workflow; persisted across restarts."""
        if self.db is None:
            raise CapabilityUnavailableError("scheduler has no database session")
        from app.db.models.workflow import Workflow

        workflow = self.db.get(Workflow, workflow_id)
        if workflow is None:
            raise ValueError(f"workflow not found: {workflow_id}")
        run_at = next_run_at(schedule)
        workflow.schedule = schedule.strip().casefold()
        workflow.schedule_enabled = True
        workflow.next_run_at = run_at
        workflow.requirement = requirement or workflow.requirement
        self.db.commit()
        self.db.refresh(workflow)
        return {
            "workflow_id": str(workflow.id),
            "schedule": workflow.schedule,
            "next_run_at": run_at.isoformat(),
            "status": workflow.status.value,
        }

    def cancel(self, workflow_id: uuid.UUID) -> dict[str, Any]:
        """Cancel a scheduled workflow (keeps the workflow itself)."""
        if self.db is None:
            raise CapabilityUnavailableError("scheduler has no database session")
        from app.db.models.workflow import Workflow

        workflow = self.db.get(Workflow, workflow_id)
        if workflow is None:
            raise ValueError(f"workflow not found: {workflow_id}")
        workflow.schedule_enabled = False
        workflow.schedule = None
        workflow.next_run_at = None
        self.db.commit()
        return {"workflow_id": str(workflow.id), "cancelled": True}

    def due_runs(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return scheduled workflows whose next run time has arrived."""
        if self.db is None:
            return []
        from app.db.models.workflow import Workflow

        now = now or datetime.now(timezone.utc)
        statement = select(Workflow).where(
            Workflow.schedule_enabled.is_(True),
            Workflow.next_run_at.is_not(None),
            Workflow.next_run_at <= now,
        )
        return [self._row(workflow) for workflow in self.db.scalars(statement).all()]

    def advance(self, workflow_id: uuid.UUID) -> dict[str, Any] | None:
        """Advance a workflow's next run and stamp the last run time."""
        if self.db is None:
            return None
        from app.db.models.workflow import Workflow

        workflow = self.db.get(Workflow, workflow_id)
        if workflow is None or not workflow.schedule_enabled:
            return None
        now = datetime.now(timezone.utc)
        workflow.last_run_at = now
        workflow.next_run_at = next_run_at(workflow.schedule or "daily", now)
        self.db.commit()
        self.db.refresh(workflow)
        return self._row(workflow)

    def _scheduled(self) -> list[Any]:
        if self.db is None:
            return []
        from app.db.models.workflow import Workflow

        statement = select(Workflow).where(Workflow.schedule.is_not(None)).order_by(Workflow.next_run_at)
        return list(self.db.scalars(statement).all())

    @staticmethod
    def _row(workflow: Any) -> dict[str, Any]:
        return {
            "workflow_id": str(workflow.id),
            "name": workflow.name,
            "schedule": workflow.schedule,
            "enabled": workflow.schedule_enabled,
            "next_run_at": workflow.next_run_at.isoformat() if workflow.next_run_at else None,
            "last_run_at": workflow.last_run_at.isoformat() if workflow.last_run_at else None,
            "status": workflow.status.value,
            "requirement": workflow.requirement,
        }
