"""GoalOS persisted scheduler service.

The scheduler accepts schedules on existing workflows (persisted, so they
survive restart), and executes each due run through the SAME canonical
path as manual execution: the :class:`ExecutionRuntimeService` resolves
capabilities through the registry, checks permissions, dispatches through
the connectors/skills, and persists every step as a runtime execution.

Each scheduled/retried run is a NEW workflow run instance cloned from the
scheduled template (``scheduled_from_id``), so:

- every run keeps its own persisted state, start/end times, success or
  failure, and execution history;
- the template is never clobbered and keeps its schedule cadence;
- duplicate execution is prevented at three levels: an atomic DB claim on
  the template (multiple worker processes cannot double-run), an in-flight
  run-instance guard (a crash mid-run is not re-cloned), and the runtime's
  own in-flight execution guard;
- enabled/disabled/cancelled state is respected (disabled and cancelled
  workflows are never due);
- retries are safe: a failed run is retried as a fresh instance.

Permissions are never bypassed: ``scheduler.create`` requires explicit
``SCHEDULE_WORKFLOWS`` authorization, and every executed run goes through
the runtime's permission gates (or the agent factory, which refuses
dangerous self-authorization).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.agents.permissions import Permission
from app.db.models.workflow import WorkflowStatus
from app.integrations.scheduler import SchedulerConnector
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.runtime_execution import RuntimeWorkflowRunResponse
from app.schemas.workflow import WorkflowCreateRequest
from app.services.agent_factory import AgentFactoryService
from app.services.execution_runtime import ExecutionRuntimeService, RuntimeErrorCode

logger = logging.getLogger(__name__)


class SchedulerService:
    """Persisted schedule management + due-run execution for GoalOS."""

    def __init__(
        self,
        connector: SchedulerConnector,
        workflow_repository: WorkflowRepository,
        runtime: ExecutionRuntimeService,
        agent_factory: AgentFactoryService,
        claim_horizon: timedelta | None = None,
    ) -> None:
        self.connector = connector
        self.workflow_repository = workflow_repository
        self.runtime = runtime
        self.agent_factory = agent_factory
        self.claim_horizon = claim_horizon or timedelta(minutes=15)

    # ------------------------------------------------------------------
    # Schedule management
    # ------------------------------------------------------------------
    def list_schedules(self) -> list[dict[str, Any]]:
        """List every scheduled workflow with its run history summary."""
        return [
            self._schedule_row(workflow)
            for workflow in self.workflow_repository.list_scheduled()
        ]

    def create_schedule(
        self,
        workflow_id: UUID,
        schedule: str,
        requirement: str | None = None,
        permissions: set[Permission] | list[Permission] | None = None,
    ) -> dict[str, Any]:
        """Create (or update) a schedule — requires SCHEDULE_WORKFLOWS."""
        granted = set(permissions or ())
        if Permission.SCHEDULE_WORKFLOWS not in granted:
            raise ValueError(
                f"{RuntimeErrorCode.PERMISSION_DENIED}: scheduler.create requires the "
                "SCHEDULE_WORKFLOWS permission"
            )
        self.connector.create(
            workflow_id,
            schedule,
            requirement=requirement or "",
        )
        return self._schedule_row(self._require_workflow(workflow_id))

    def disable_schedule(self, workflow_id: UUID) -> dict[str, Any]:
        """Pause a schedule (definition kept; resume via enable_schedule)."""
        self.connector.disable(workflow_id)
        return self._schedule_row(self._require_workflow(workflow_id))

    def enable_schedule(self, workflow_id: UUID) -> dict[str, Any]:
        """Resume a paused schedule."""
        self.connector.enable(workflow_id)
        return self._schedule_row(self._require_workflow(workflow_id))

    def cancel_schedule(self, workflow_id: UUID) -> dict[str, Any]:
        """Hard-cancel a schedule (definition cleared; workflow kept)."""
        self.connector.cancel(workflow_id)
        return self._schedule_row(self._require_workflow(workflow_id))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _require_workflow(self, workflow_id: UUID) -> Any:
        workflow = self.workflow_repository.get(workflow_id)
        if workflow is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow not found: {workflow_id}"
            )
        return workflow

    def _schedule_row(self, workflow: Any) -> dict[str, Any]:
        """Build the schedule response dict for a workflow + run history."""
        runs = self.workflow_repository.list_runs_of(workflow.id)
        return {
            "workflow_id": workflow.id,
            "name": workflow.name,
            "schedule": workflow.schedule,
            "enabled": workflow.schedule_enabled,
            "next_run_at": workflow.next_run_at,
            "last_run_at": workflow.last_run_at,
            "status": workflow.status.value,
            "requirement": workflow.requirement,
            "run_count": len(runs),
            "last_run_status": runs[0].status.value if runs else None,
        }

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_due(self, now: datetime | None = None) -> dict[str, Any]:
        """Execute every due scheduled workflow through the runtime.

        Returns a summary of what was processed. Each due template is
        atomically claimed first (duplicate-loop safe); a run instance is
        cloned and executed; the template is advanced to its next run in
        ``finally`` so a crash never wedges the schedule.
        """
        now = now or datetime.now(timezone.utc)
        due = self.connector.due_runs(now)
        processed: list[dict[str, Any]] = []
        for row in due:
            workflow_id = UUID(row["workflow_id"])
            summary: dict[str, Any] = {
                "workflow_id": str(workflow_id),
                "name": row.get("name"),
                "scheduled": True,
            }
            if not self.connector.claim(
                workflow_id, now=now, horizon=self.claim_horizon
            ):
                summary["status"] = "skipped_claimed"
                processed.append(summary)
                continue
            try:
                if self.workflow_repository.has_in_flight_run(workflow_id):
                    summary["status"] = "skipped_in_flight"
                else:
                    run = self._create_run_instance_and_execute(workflow_id, row)
                    summary["status"] = run.workflow.status
                    summary["run_workflow_id"] = str(run.workflow.id)
                    summary["executions"] = len(run.executions)
                    summary["evaluation"] = run.workflow.evaluation
            except Exception as exc:
                logger.exception("scheduled run failed for workflow %s", workflow_id)
                summary["status"] = "error"
                summary["error"] = str(exc)
            finally:
                try:
                    self.connector.advance(workflow_id)
                except Exception:
                    logger.exception("could not advance schedule for workflow %s", workflow_id)
            processed.append(summary)
        return {"due": len(due), "processed": processed}

    def run_now(self, workflow_id: UUID) -> RuntimeWorkflowRunResponse:
        """Manually trigger one scheduled workflow through the runtime.

        Executes immediately as a fresh run instance (same canonical path,
        same duplicate/in-flight guards, same persisted history).
        """
        template = self.workflow_repository.get(workflow_id)
        if template is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow not found: {workflow_id}"
            )
        if not template.schedule:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow is not scheduled: "
                f"{workflow_id}"
            )
        requirement = template.requirement
        if not requirement:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow has no requirement to run"
            )
        if self.workflow_repository.has_in_flight_run(workflow_id):
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: a scheduled run is already in "
                f"flight for workflow {workflow_id}"
            )
        return self._create_run_instance_and_execute(
            workflow_id,
            {
                "name": template.name,
                "requirement": requirement,
                "schedule": template.schedule,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _create_run_instance_and_execute(
        self,
        template_id: UUID,
        row: dict[str, Any],
    ) -> RuntimeWorkflowRunResponse:
        """Clone the template into a run instance and execute it via the runtime.

        The clone carries the template's requirement and capability plan
        (resolving through the capability engine when the template has no
        plan yet) and is linked back via ``scheduled_from_id``.
        """
        template = self.workflow_repository.get(template_id)
        if template is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow not found: {template_id}"
            )
        requirement = template.requirement or str(row.get("requirement") or "").strip()
        if not requirement:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow has no requirement to run"
            )
        # The run instance carries the template's requirement AND its
        # persisted goal plan (ordered steps + per-step inputs), so
        # scheduled runs of plan-driven workflows execute sequentially and
        # result-chained exactly like manual runs. Plan-less templates
        # resolve their execution capabilities from the requirement through
        # the capability engine (identical to the manual path).
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        instance = self.workflow_repository.create(
            WorkflowCreateRequest(
                project_id=template.project_id,
                name=f"{template.name} · scheduled {stamp}",
            )
        )
        instance = self.workflow_repository.update(
            instance,
            {
                "requirement": requirement,
                "scheduled_from_id": template_id,
                "plan": template.plan,
            },
        )
        try:
            return self.runtime.run_workflow(
                instance.id,
                requirement=requirement,
                agent_factory=self.agent_factory,
                agent_name=f"scheduler:{template.name}",
            )
        except Exception as exc:
            logger.warning("scheduled run instance %s failed: %s", instance.id, exc)
            self.workflow_repository.update(
                instance,
                {
                    "status": WorkflowStatus.FAILED,
                    "completed_at": datetime.now(timezone.utc),
                    "error_message": f"{RuntimeErrorCode.WORKFLOW_INVALID}: {exc}",
                    "evaluation": {
                        "status": "Failed",
                        "passed": False,
                        "summary": str(exc),
                    },
                },
            )
            raise
