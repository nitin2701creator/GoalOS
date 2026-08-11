"""
Workflow business service.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.agents.capabilities import capability_spec, resolve_capabilities
from app.db.models.workflow import Workflow, WorkflowStatus
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.factory import integration_for_capability
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.agent import AgentCreateRequest, AgentResponse
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService

#: Deterministic regions recognised in workflow requirements.
_REGION_KEYWORDS = (
    "india",
    "united states",
    "usa",
    "europe",
    "uk",
    "canada",
    "germany",
    "france",
    "australia",
    "japan",
)

#: Common acronyms excluded from subject extraction so proper nouns win.
_ACRONYMS = frozenset({"SEO", "KPI", "AI", "API", "ROI", "CRM", "ERP", "MRR"})

_URL_PATTERN = re.compile(r"(https?://[^\s'\"<>]+|www\.[^\s'\"<>]+)")


def _extract_subject(requirement: str) -> str:
    """Derive a deterministic subject from a workflow requirement.

    The last capitalized proper noun (excluding common acronyms) wins;
    otherwise the whole requirement is used.
    """
    candidates = []
    for token in requirement.split():
        if not (token[0].isupper() and len(token) > 1 and token not in _ACRONYMS):
            continue
        candidates.append(re.sub(r"^['\".,!?;:]+|['\".,!?;:]+$", "", token))
    if candidates:
        return candidates[-1].casefold()
    return requirement.strip().casefold()


def _extract_url(requirement: str) -> str:
    """Return the first URL mentioned in the requirement, if any."""
    match = _URL_PATTERN.search(requirement)
    if match is None:
        return ""
    return match.group(1).rstrip(".,;!?")


def _extract_region(requirement: str) -> str:
    """Return the first known region mentioned, else an empty string."""
    text = requirement.casefold()
    for region in _REGION_KEYWORDS:
        if region in text:
            return region
    return ""


def derive_workflow_input(requirement: str) -> dict[str, Any]:
    """Build the deterministic execution input for a workflow requirement.

    Every catalog skill reads only the keys it needs, so one shared input
    mapping serves any capability set without special-casing.
    """
    subject = _extract_subject(requirement)
    return {
        "requirement": requirement,
        "topic": subject,
        "query": requirement,
        "content": requirement,
        "url": _extract_url(requirement) or "",
        "industry": subject,
        "region": _extract_region(requirement) or "global",
        "text": requirement,
        "lead": requirement,
        "criteria": ["qualified", "reachable", "responsive"],
        "subject": subject,
        "outline": requirement,
        "recipient": "",
    }


class WorkflowService:
    """Business operations for workflow orchestration."""

    def __init__(self, repository: WorkflowRepository, execution_repository: ExecutionRepository):
        self.repository = repository
        self.execution_repository = execution_repository

    def _to_response(self, workflow: Workflow) -> WorkflowResponse:
        return WorkflowResponse.model_validate(workflow)

    def create(self, request: WorkflowCreateRequest) -> WorkflowResponse:
        data = request.model_dump(exclude_unset=True)
        if data.get("status") is None:
            data["status"] = WorkflowStatus.PENDING
        if data.get("progress_percentage") is None:
            data["progress_percentage"] = 0
        workflow = self.repository.create(WorkflowCreateRequest.model_validate(data))
        return self._to_response(workflow)

    def get(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get_with_tasks(workflow_id)
        if workflow is None:
            return None
        return self._to_response(workflow)

    def list(self) -> list[WorkflowResponse]:
        return [self._to_response(workflow) for workflow in self.repository.list()]

    def list_by_project(self, project_id: UUID) -> list[WorkflowResponse] | None:
        if not self.repository.project_exists(project_id):
            return None
        return [self._to_response(workflow) for workflow in self.repository.list_by_project(project_id)]

    def update(self, workflow_id: UUID, request: WorkflowUpdateRequest) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(workflow)
        return self._to_response(self.repository.update(workflow, updates))

    def delete(self, workflow_id: UUID) -> bool:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return False
        self.repository.delete(workflow)
        return True

    def start(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now(timezone.utc)
        if workflow.progress_percentage is None:
            workflow.progress_percentage = 0

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "started_at": workflow.started_at,
            "progress_percentage": workflow.progress_percentage,
        }))

    def complete(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = datetime.now(timezone.utc)
        workflow.progress_percentage = 100

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "completed_at": workflow.completed_at,
            "progress_percentage": workflow.progress_percentage,
        }))

    def fail(self, workflow_id: UUID, error_message: str | None = None) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = datetime.now(timezone.utc)

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "completed_at": workflow.completed_at,
        }))

    def progress(self, workflow_id: UUID, progress_percentage: int) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.progress_percentage = max(0, min(progress_percentage, 100))
        return self._to_response(self.repository.update(workflow, {"progress_percentage": workflow.progress_percentage}))

    def pause(self, workflow_id: UUID) -> WorkflowResponse | None:
        """Pause a workflow (only Pending/Running) and disable its schedule.

        A scheduled workflow that is paused is removed from the due set
        (``schedule_enabled=False``) but keeps its schedule definition so
        :meth:`resume` can restore the same cadence.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        if workflow.status not in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING):
            raise ValueError(
                "WORKFLOW_INVALID: only pending or running workflows can be paused "
                f"(current status: {workflow.status.value})"
            )
        return self._to_response(
            self.repository.update(
                workflow,
                {
                    "status": WorkflowStatus.PAUSED,
                    "schedule_enabled": False,
                },
            )
        )

    def resume(self, workflow_id: UUID) -> WorkflowResponse | None:
        """Resume a paused workflow and its schedule.

        A workflow that had begun running resumes as ``Running`` (its
        persisted steps remain); a never-run workflow resumes as
        ``Pending``. A paused schedule is re-enabled with a future next
        run.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        if workflow.status is not WorkflowStatus.PAUSED:
            raise ValueError(
                "WORKFLOW_INVALID: only paused workflows can be resumed "
                f"(current status: {workflow.status.value})"
            )
        updates: dict[str, Any] = {
            "status": WorkflowStatus.RUNNING if workflow.steps else WorkflowStatus.PENDING,
        }
        if workflow.schedule:
            from app.integrations.scheduler import _coerce_utc, next_run_at

            now = datetime.now(timezone.utc)
            updates["schedule_enabled"] = True
            next_run = _coerce_utc(workflow.next_run_at)
            if next_run is None or next_run <= now:
                updates["next_run_at"] = next_run_at(workflow.schedule, now)
        return self._to_response(self.repository.update(workflow, updates))

    def cancel(self, workflow_id: UUID) -> WorkflowResponse | None:
        """Cancel a workflow: terminal state, schedule disabled, runs stopped.

        In-flight capability executions of the workflow are cancelled by
        the caller via the execution runtime (``cancel_in_flight``) so no
        orphaned execution can later claim success.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        if workflow.status is WorkflowStatus.CANCELLED:
            return self._to_response(workflow)
        if workflow.status is WorkflowStatus.COMPLETED:
            raise ValueError(
                "WORKFLOW_INVALID: completed workflows cannot be cancelled "
                f"(current status: {workflow.status.value})"
            )
        return self._to_response(
            self.repository.update(
                workflow,
                {
                    "status": WorkflowStatus.CANCELLED,
                    "completed_at": datetime.now(timezone.utc),
                    "schedule_enabled": False,
                    "next_run_at": None,
                },
            )
        )

    def run_agent_workflow(
        self,
        workflow_id: UUID,
        requirement: str,
        agent_factory: AgentFactoryService,
        integration_registry: ConnectorRegistry | None = None,
        capabilities: tuple[str, ...] | None = None,
        capability_service: CapabilityService | None = None,
        resolved_capabilities: list[str] | None = None,
    ) -> WorkflowResponse | None:
        """Run an autonomous agent workflow against an existing workflow.

        The run composes the existing GoalOS pieces: capability analysis
        (the capability engine or ``resolve_capabilities``), the agent
        factory (reuse or create the agents and skills), the integration
        registry (availability and permission checks per capability), and
        the existing ``BaseAgent`` runtime for execution. Every step
        result, the aggregate results, and the evaluation are persisted on
        the workflow record.

        Args:
            workflow_id: The workflow to execute against.
            requirement: The business requirement to resolve into
                capabilities.
            agent_factory: The agent factory used to resolve/create agents.
            integration_registry: Integration connectors; when provided,
                required integrations are enforced per step and missing
                ones are persisted as blocked reasons (never faked).
            capabilities: Optional explicit execution capability set. When
                omitted it is derived from ``requirement`` (via
                ``capability_service`` when provided, else the keyword
                catalog).
            capability_service: The capability engine; when provided (and
                ``capabilities`` is omitted) the goal is resolved through
                the persistent capability registry.
            resolved_capabilities: Registry capability names matched to
                the goal, persisted on the workflow for auditability.

        Returns:
            The updated workflow, or ``None`` if it does not exist.

        Raises:
            ValueError: If the workflow has already been run.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        if workflow.steps:
            raise ValueError("workflow has already been run")

        if capability_service is not None and capabilities is None:
            resolution = capability_service.resolve_for_goal(requirement)
            capabilities = tuple(resolution.execution_capabilities)
            resolved_capabilities = list(resolution.capabilities)
        if capabilities is None:
            capabilities = resolve_capabilities(requirement)
        if resolved_capabilities is None:
            resolved_capabilities = list(capabilities)

        started_at = datetime.now(timezone.utc)
        workflow = self.repository.update(
            workflow,
            {
                "status": WorkflowStatus.RUNNING,
                "started_at": started_at,
                "requirement": requirement,
                "resolved_capabilities": resolved_capabilities,
                "steps": [],
                "results": {},
                "evaluation": None,
                "error_message": None,
                "progress_percentage": 5,
            },
        )

        if not capabilities:
            return self._fail_run(
                workflow,
                "no capabilities could be resolved from the requirement",
            )

        # Resolve an existing ACTIVE agent or create the missing one. The
        # factory enforces explicit authorization for dangerous permissions,
        # so an unprivileged run can never self-authorize code execution.
        try:
            resolved = agent_factory.resolve_for_capabilities(
                requirement, capabilities
            )
            if resolved.agent is not None:
                agent = resolved.agent
            else:
                spec = resolved.specification
                assert spec is not None
                agent = agent_factory.create_agent(
                    AgentCreateRequest(
                        name=spec.name,
                        purpose=spec.purpose,
                        required_capabilities=list(spec.capabilities),
                    )
                )
        except ValueError as exc:
            return self._fail_run(workflow, str(exc))

        steps: list[dict[str, Any]] = [
            {
                "capability": capability,
                "agent_name": agent.name,
                "status": "Pending",
                "result": None,
                "error": None,
            }
            for capability in capabilities
        ]
        step_count = len(steps)
        blocked_reasons: list[str] = []
        if integration_registry is not None:
            for step in steps:
                blockers = self._step_integration_blockers(
                    step["capability"], agent, integration_registry
                )
                if blockers:
                    step["status"] = "Blocked"
                    step["error"] = "; ".join(blockers)
                    blocked_reasons.extend(blockers)
        workflow = self.repository.update(
            workflow, {"steps": steps, "progress_percentage": 10}
        )

        if any(step["status"] == "Blocked" for step in steps):
            return self._fail_run(
                workflow,
                "required integrations are not available: "
                + "; ".join(dict.fromkeys(blocked_reasons)),
            )

        try:
            execution = agent_factory.execute_agent(
                agent.id,
                goal=requirement,
                inputs=derive_workflow_input(requirement),
                integrations=integration_registry,
            )
        except (KeyError, ValueError) as exc:
            return self._fail_run(workflow, str(exc))

        results = execution.results
        execution_errors = list(execution.errors)
        for step in steps:
            capability = step["capability"]
            if capability in results:
                step["status"] = "Completed"
                step["result"] = results[capability]
            else:
                step["status"] = "Failed"
                step["error"] = (
                    next(
                        (
                            error
                            for error in execution_errors
                            if capability in error
                        ),
                        f"agent reported no result for capability {capability}",
                    )
                )

        completed_steps = sum(1 for step in steps if step["status"] == "Completed")
        failed_steps = step_count - completed_steps
        passed = failed_steps == 0
        evaluation = {
            "status": "Passed" if passed else "Failed",
            "passed": passed,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "total_steps": step_count,
            "summary": (
                f"Executed {step_count} capability step(s) via agent "
                f"'{agent.name}': {completed_steps} completed, {failed_steps} failed."
            ),
        }

        completed_at = datetime.now(timezone.utc)
        updates: dict[str, Any] = {
            "steps": steps,
            "results": results,
            "evaluation": evaluation,
            "progress_percentage": 100 if passed else 40,
            "completed_at": completed_at,
        }
        if passed:
            updates["status"] = WorkflowStatus.COMPLETED
        else:
            updates["status"] = WorkflowStatus.FAILED
            updates["error_message"] = (
                f"{failed_steps} of {step_count} capability step(s) failed"
            )
        workflow = self.repository.update(workflow, updates)
        return self._to_response(workflow)

    @staticmethod
    def _step_integration_blockers(
        capability: str,
        agent: AgentResponse,
        registry: ConnectorRegistry,
    ) -> list[str]:
        """Return why one capability cannot run against the registry."""
        try:
            spec = capability_spec(capability)
        except ValueError:
            return []
        blockers: list[str] = []
        for capability_name in spec.integration_capabilities:
            integration = integration_for_capability(capability_name)
            connector = registry.get_connector(integration)
            if connector is None:
                blockers.append(
                    f"required integration '{integration}' is not registered"
                )
                continue
            available, reason = connector.capability_available(capability_name)
            if not available:
                blockers.append(
                    f"required capability '{capability_name}' is unavailable: {reason}"
                )
            required = getattr(connector, "CAPABILITY_PERMISSIONS", {}).get(
                capability_name
            )
            if required is not None and required not in agent.permissions:
                blockers.append(
                    f"capability '{capability_name}' requires permission "
                    f"'{required.value}', which the agent does not hold"
                )
        return blockers

    def _fail_run(self, workflow: Workflow, message: str) -> WorkflowResponse:
        """Persist a failed agent workflow run with its error reason."""
        workflow = self.repository.update(
            workflow,
            {
                "status": WorkflowStatus.FAILED,
                "completed_at": datetime.now(timezone.utc),
                "error_message": message,
                "evaluation": {
                    "status": "Failed",
                    "passed": False,
                    "summary": message,
                },
            },
        )
        return self._to_response(workflow)

    def approve(
        self,
        workflow_id: UUID,
        requirement: str,
        capabilities: tuple[str, ...] | list[str] | None = None,
        resolved_capabilities: list[str] | None = None,
        capability_service: CapabilityService | None = None,
    ) -> WorkflowResponse:
        """Approve a workflow with its capability plan, without executing.

        The approval is the hand-off from planning to execution: the
        requirement and the resolved capability set are persisted on the
        workflow so the execution runtime can pick it up later. The
        workflow keeps its ``Pending`` status — execution is a separate,
        explicit step (``ExecutionRuntimeService.run_workflow``).

        Args:
            workflow_id: The workflow to approve.
            requirement: The business requirement driving the plan.
            capabilities: Optional explicit execution capability set. When
                omitted it is resolved through ``capability_service`` when
                provided, else the deterministic keyword catalog.
            resolved_capabilities: Registry capability names matched to
                the goal, persisted for auditability.
            capability_service: The capability engine used to resolve the
                plan when ``capabilities`` is omitted.

        Returns:
            The approved workflow.

        Raises:
            ValueError: If the workflow does not exist or was already run.
        """
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            raise ValueError(f"workflow not found: {workflow_id}")
        if workflow.steps:
            raise ValueError(f"workflow has already been run: {workflow_id}")

        if capabilities is None:
            if capability_service is not None:
                resolution = capability_service.resolve_for_goal(requirement)
                capabilities = tuple(resolution.execution_capabilities)
                if resolved_capabilities is None:
                    resolved_capabilities = list(resolution.capabilities)
            else:
                capabilities = resolve_capabilities(requirement)
        if resolved_capabilities is None:
            resolved_capabilities = list(capabilities)

        workflow = self.repository.update(
            workflow,
            {
                "requirement": requirement,
                "resolved_capabilities": resolved_capabilities,
                "steps": [],
                "results": {},
                "evaluation": None,
                "error_message": None,
                "progress_percentage": 5,
            },
        )
        return self._to_response(workflow)

    def update_status_from_tasks(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get_with_tasks(workflow_id)
        if workflow is None:
            return None

        tasks = workflow.tasks
        if not tasks:
            workflow.status = WorkflowStatus.PENDING
            workflow.progress_percentage = 0
        else:
            completed_tasks = [task for task in tasks if task.status.lower() == "completed"]
            workflow.progress_percentage = int((len(completed_tasks) / len(tasks)) * 100)
            if all(task.status.lower() == "completed" for task in tasks):
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.now(timezone.utc)
            elif any(task.status.lower() == "failed" for task in tasks):
                workflow.status = WorkflowStatus.FAILED
            elif any(task.status.lower() == "running" for task in tasks):
                workflow.status = WorkflowStatus.RUNNING
            else:
                workflow.status = WorkflowStatus.PENDING

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "progress_percentage": workflow.progress_percentage,
            "completed_at": workflow.completed_at,
        }))
