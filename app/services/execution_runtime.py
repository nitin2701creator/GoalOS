"""GoalOS execution runtime.

The runtime is the persisted execution layer on top of the existing
capability engine. It accepts an approved workflow/action from the
existing :class:`WorkflowService`, resolves the requested capability
through the capability registry, checks the existing permission system,
resolves the provider/connector, executes the capability through a clean
:class:`CapabilityExecutor` interface, and captures the full canonical
lifecycle — ``pending`` → ``running`` → ``succeeded`` | ``failed`` |
``blocked`` | ``cancelled`` — with inputs, outputs, errors, stable error
codes, timestamps, and execution metadata in the ``runtime_executions``
table.

Honesty contract:

- An unavailable provider persists as ``failed`` with the existing
  ``INTEGRATION_NOT_CONFIGURED`` reason (``error_code``
  ``INTEGRATION_NOT_CONFIGURED``) — never a fabricated success.
- Insufficient permissions persist as ``failed`` with
  ``PERMISSION_DENIED``.
- Publishing/external-write capabilities executed outside an approved
  workflow persist as ``blocked`` with ``APPROVAL_REQUIRED`` — they never
  run silently.
- Unknown capabilities persist as ``failed`` with ``CAPABILITY_NOT_FOUND``.
- Invalid workflows are refused with ``WORKFLOW_INVALID``.
- A crashing executor persists ``EXECUTION_FAILED``.
- Workflow steps that are pre-flighted and refused before dispatch
  persist as ``blocked`` executions carrying the precise reason.
- In-flight executions of a cancelled workflow persist as ``cancelled``.

The runtime reuses the existing capability registry, permission model,
connector registry, agent factory, and workflow persistence — no
parallel architecture.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from app.agents.capabilities import capability_spec
from app.agents.permissions import Permission
from app.db.models.runtime_execution import RuntimeExecution, RuntimeExecutionStatus
from app.db.models.workflow import WorkflowStatus
from app.integrations.factory import integration_for_capability
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.agent import AgentCreateRequest
from app.schemas.capability import CapabilityExecuteResponse
from app.schemas.runtime_execution import (
    RuntimeExecutionResponse,
    RuntimeWorkflowRunResponse,
)
from app.schemas.workflow import WorkflowCreateRequest, WorkflowResponse
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService
from app.services.workflow_service import derive_workflow_input

logger = logging.getLogger(__name__)


class RuntimeErrorCode:
    """Stable machine-readable execution failure codes.

    These are persisted on ``runtime_executions.error_code`` and are the
    canonical contract for failure handling (requirement: provider
    unavailable → ``INTEGRATION_NOT_CONFIGURED``, permission denied →
    ``PERMISSION_DENIED``, invalid capability → ``CAPABILITY_NOT_FOUND``,
    invalid workflow → ``WORKFLOW_INVALID``, runtime exception →
    ``EXECUTION_FAILED``).
    """

    INTEGRATION_NOT_CONFIGURED = "INTEGRATION_NOT_CONFIGURED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
    WORKFLOW_INVALID = "WORKFLOW_INVALID"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DISABLED = "DISABLED"
    CANCELLED = "CANCELLED"


#: Executor response status → stable error code.
_EXECUTOR_STATUS_CODES: dict[str, str] = {
    "INTEGRATION_NOT_CONFIGURED": RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED,
    "PERMISSION_DENIED": RuntimeErrorCode.PERMISSION_DENIED,
    "NOT_FOUND": RuntimeErrorCode.CAPABILITY_NOT_FOUND,
    "DISABLED": RuntimeErrorCode.DISABLED,
    "ERROR": RuntimeErrorCode.EXECUTION_FAILED,
}


class CapabilityExecutor(Protocol):
    """Clean executor interface for one capability invocation.

    Implementations resolve, authorize, and run a capability and return a
    structured result — never a fabricated success. The default
    implementation delegates to the existing :class:`CapabilityService`.
    """

    def execute(
        self,
        capability: str,
        params: dict[str, Any],
        permissions: set[Permission],
    ) -> CapabilityExecuteResponse:
        """Execute one capability over structured parameters."""
        ...


class CapabilityServiceExecutor:
    """Default executor delegating to the existing capability engine.

    ``CapabilityService.execute`` already enforces availability
    (``INTEGRATION_NOT_CONFIGURED``) and permissions
    (``PERMISSION_DENIED``) before dispatch, and routes through the
    existing integration connectors and skill implementations.
    """

    def __init__(self, capability_service: CapabilityService) -> None:
        self.capability_service = capability_service

    def execute(
        self,
        capability: str,
        params: dict[str, Any],
        permissions: set[Permission],
    ) -> CapabilityExecuteResponse:
        return self.capability_service.execute(capability, params, permissions)


class ExecutionRuntimeService:
    """Persisted execution runtime for GoalOS capabilities and workflows.

    Responsibilities:

    - ``execute``: run ONE capability through the executor with the full
      persisted lifecycle and honest failure states.
    - ``run_workflow``: accept an approved workflow from the existing
      ``WorkflowService``, execute each capability step through the
      runtime, and persist the step results and evaluation back on the
      workflow (identical shape to the agent workflow path).
    - ``retry`` / ``retry_workflow``: safely retry a failed capability
      execution or a failed workflow by creating a fresh execution/run
      instance (history is retained).
    - ``cancel_in_flight``: mark in-flight executions of a cancelled
      workflow as cancelled.
    - ``list``/``get``/``list_by_workflow``/``list_filtered``/``stats``:
      query persisted executions.

    Duplicate execution is prevented: a workflow with persisted steps
    cannot be run again, an in-flight execution for a workflow blocks a
    second submission for the same workflow, and retries always create a
    new execution record.
    """

    def __init__(
        self,
        repository: RuntimeExecutionRepository,
        capability_service: CapabilityService,
        workflow_repository: WorkflowRepository | None = None,
        executor: CapabilityExecutor | None = None,
    ) -> None:
        self.repository = repository
        self.capability_service = capability_service
        self.workflow_repository = workflow_repository
        self.executor = executor or CapabilityServiceExecutor(capability_service)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list(self) -> list[RuntimeExecutionResponse]:
        return [self._to_response(execution) for execution in self.repository.list()]

    def get(self, execution_id: UUID) -> RuntimeExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None
        return self._to_response(execution)

    def list_by_workflow(self, workflow_id: UUID) -> list[RuntimeExecutionResponse]:
        return [
            self._to_response(execution)
            for execution in self.repository.list_by_workflow(workflow_id)
        ]

    def list_filtered(
        self,
        workflow_id: UUID | None = None,
        status: str | None = None,
        capability: str | None = None,
    ) -> list[RuntimeExecutionResponse]:
        """List executions with optional workflow/status/capability filters."""
        executions = (
            self.list_by_workflow(workflow_id)
            if workflow_id is not None
            else self.list()
        )
        if status is not None:
            executions = [
                execution for execution in executions if execution.status.value == status
            ]
        if capability is not None:
            executions = [
                execution
                for execution in executions
                if execution.capability == capability
            ]
        return executions

    def stats(self) -> dict[str, Any]:
        """Aggregate execution counts by status and error code (for health)."""
        executions = self.repository.list()
        by_status: dict[str, int] = {}
        by_code: dict[str, int] = {}
        for execution in executions:
            by_status[execution.status.value] = by_status.get(execution.status.value, 0) + 1
            if execution.error_code:
                by_code[execution.error_code] = by_code.get(execution.error_code, 0) + 1
        return {
            "total": len(executions),
            "by_status": by_status,
            "by_error_code": by_code,
        }

    # ------------------------------------------------------------------
    # Single capability execution
    # ------------------------------------------------------------------
    def execute(
        self,
        capability: str,
        params: dict[str, Any],
        permissions: set[Permission] | list[Permission] | None = None,
        *,
        workflow_id: UUID | None = None,
        agent_name: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_error: str | None = None,
        expected_code: str | None = None,
    ) -> RuntimeExecutionResponse:
        """Execute one capability through the runtime, fully persisted.

        Flow: resolve through the capability registry → check the existing
        permission system → transition ``pending`` → ``running`` →
        ``succeeded``/``failed``/``blocked`` → persist output/error/error
        code/timestamps. An unavailable provider or missing permission is
        persisted as ``failed`` with the honest reason and code — never
        fabricated.

        ``expected_error``/``expected_code`` are internal overrides used by
        the workflow pre-flight: when a step was already determined to be
        blocked, the precise blocker reason and code are persisted as a
        ``blocked`` execution instead of re-deriving a generic one.

        Raises:
            ValueError: If ``workflow_id`` is provided and the workflow
                already has an in-flight execution (duplicate prevention).
        """
        granted = set(permissions or ())
        if workflow_id is not None:
            active = self.repository.active_for_workflow(workflow_id)
            if active is not None:
                raise ValueError(
                    f"workflow {workflow_id} already has an active runtime execution "
                    f"({active.capability}); refusing duplicate submission"
                )

        resolution = self.capability_service.resolve(capability, granted)
        if expected_error is not None:
            execution = self.repository.create(
                {
                    "workflow_id": workflow_id,
                    "capability": capability,
                    "status": RuntimeExecutionStatus.PENDING,
                    "input": dict(params or {}),
                    "provider": resolution.provider,
                    "permissions_required": [
                        permission.value for permission in resolution.required_permissions
                    ],
                    "agent_name": agent_name,
                    "execution_metadata": {
                        **(metadata or {}),
                        "granted_permissions": sorted(
                            permission.value for permission in granted
                        ),
                        "resolution": {
                            "exists": resolution.exists,
                            "enabled": resolution.enabled,
                            "available": False,
                            "reason": expected_error,
                            "blocked": True,
                        },
                    },
                }
            )
            return self._finish(
                execution,
                None,
                expected_error,
                code=expected_code or RuntimeErrorCode.EXECUTION_FAILED,
                status=RuntimeExecutionStatus.BLOCKED,
            )

        execution = self.repository.create(
            {
                "workflow_id": workflow_id,
                "capability": capability,
                "status": RuntimeExecutionStatus.PENDING,
                "input": dict(params or {}),
                "provider": resolution.provider,
                "permissions_required": [
                    permission.value for permission in resolution.required_permissions
                ],
                "agent_name": agent_name,
                "execution_metadata": {
                    **(metadata or {}),
                    "granted_permissions": sorted(
                        permission.value for permission in granted
                    ),
                    "resolution": {
                        "exists": resolution.exists,
                        "enabled": resolution.enabled,
                        "available": resolution.available,
                        "reason": resolution.reason,
                        "permissions_sufficient": resolution.permissions_sufficient,
                        "missing_permissions": list(resolution.missing_permissions),
                        "provider": resolution.provider,
                        "execution_capability": resolution.execution_capability,
                    },
                },
            }
        )

        # Honest gates BEFORE dispatch: never execute an unregistered,
        # unauthorized, or unconfigured capability.
        if not resolution.exists:
            return self._finish(
                execution,
                None,
                "capability is not registered",
                code=RuntimeErrorCode.CAPABILITY_NOT_FOUND,
            )
        if resolution.permissions_sufficient is False:
            return self._finish(
                execution,
                None,
                "missing required permissions: " + ", ".join(resolution.missing_permissions),
                code=RuntimeErrorCode.PERMISSION_DENIED,
            )
        if not resolution.available:
            return self._finish(
                execution,
                None,
                resolution.reason or "INTEGRATION_NOT_CONFIGURED",
                code=RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED,
            )
        if resolution.requires_approval and not self._approved_context(workflow_id):
            return self._finish(
                execution,
                None,
                (
                    f"APPROVAL_REQUIRED: capability '{capability}' changes external "
                    "state and must be executed through an approved workflow"
                ),
                code=RuntimeErrorCode.APPROVAL_REQUIRED,
                status=RuntimeExecutionStatus.BLOCKED,
            )

        execution = self.repository.update(
            execution,
            {"status": RuntimeExecutionStatus.RUNNING, "started_at": datetime.now(timezone.utc)},
        )
        try:
            response = self.executor.execute(capability, dict(params or {}), granted)
        except Exception as exc:  # noqa: BLE001 - a crashing executor must persist a failure
            logger.warning("runtime execution of '%s' crashed: %s", capability, exc)
            return self._finish(
                execution,
                None,
                f"{type(exc).__name__}: {exc}",
                code=RuntimeErrorCode.EXECUTION_FAILED,
            )

        if response.status == "OK":
            return self._finish(execution, response.result or {"result": None})
        return self._finish(
            execution,
            {"status": response.status, "result": response.result},
            response.error or response.status,
            code=_EXECUTOR_STATUS_CODES.get(
                response.status, RuntimeErrorCode.EXECUTION_FAILED
            ),
        )

    def retry(self, execution_id: UUID) -> RuntimeExecutionResponse | None:
        """Retry a failed, blocked, or cancelled capability execution.

        A fresh execution record is created with the same capability,
        parameters, and granted permissions (the granted set is restored
        from the previous attempt's persisted metadata — never escalated).
        Returns ``None`` when the execution does not exist; raises when it
        is not retryable.
        """
        previous = self.repository.get(execution_id)
        if previous is None:
            return None
        if previous.status not in (
            RuntimeExecutionStatus.FAILED,
            RuntimeExecutionStatus.BLOCKED,
            RuntimeExecutionStatus.CANCELLED,
        ):
            raise ValueError(
                f"EXECUTION_FAILED: only failed, blocked, or cancelled executions "
                f"can be retried (current status: {previous.status.value})"
            )
        granted = {
            Permission(value)
            for value in (previous.execution_metadata or {}).get(
                "granted_permissions", []
            )
        }
        return self.execute(
            previous.capability,
            dict(previous.input or {}),
            granted,
            workflow_id=previous.workflow_id,
            agent_name=previous.agent_name,
            metadata={
                **(previous.execution_metadata or {}),
                "retried_from": str(previous.id),
            },
        )

    def cancel_in_flight(self, workflow_id: UUID) -> list[RuntimeExecutionResponse]:
        """Cancel every in-flight execution of a workflow (audit persists)."""
        return [
            self._to_response(execution)
            for execution in self.repository.cancel_in_flight(workflow_id)
        ]

    # ------------------------------------------------------------------
    # Approved workflow execution
    # ------------------------------------------------------------------
    def run_workflow(
        self,
        workflow_id: UUID,
        requirement: str | None = None,
        capabilities: tuple[str, ...] | list[str] | None = None,
        permissions: set[Permission] | list[Permission] | None = None,
        agent_name: str | None = None,
        agent_factory: AgentFactoryService | None = None,
    ) -> RuntimeWorkflowRunResponse:
        """Run an approved workflow through the execution runtime.

        The workflow must exist and must not have been run before (its
        steps must be empty — duplicate prevention). The requirement
        defaults to the approved workflow's persisted requirement. When
        permissions are omitted, the agent factory reuses/creates the
        agent for the capability set and its declared permissions are
        granted (never implicit escalation).

        Every capability step executes through :meth:`execute`, so each
        step has a persisted runtime execution record. Unavailable
        capabilities are pre-flighted and persisted as ``blocked`` steps
        and executions with the honest reason and error code — the
        workflow never claims a fabricated success.

        Returns:
            The updated workflow plus the per-step runtime executions.

        Raises:
            ValueError: If the workflow does not exist, was already run,
                is not approved, or no permissions/agent can be resolved.
        """
        if self.workflow_repository is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow repository is required "
                "to run a workflow"
            )
        workflow = self.workflow_repository.get(workflow_id)
        if workflow is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow not found: {workflow_id}"
            )
        if workflow.steps:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow has already been run: "
                f"{workflow_id}"
            )

        requirement = requirement or workflow.requirement
        if not requirement:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow {workflow_id} is not "
                "approved: no requirement is set"
            )

        if capabilities is None:
            resolution = self.capability_service.resolve_for_goal(requirement)
            capabilities = tuple(resolution.execution_capabilities)
            resolved_capabilities = list(resolution.capabilities)
        else:
            resolved_capabilities = list(workflow.resolved_capabilities or capabilities)

        if not capabilities:
            return self._fail_run(
                workflow,
                "no capabilities could be resolved from the requirement",
                executions=[],
            )

        # Permissions: explicit grant wins; otherwise resolve/reuse the
        # agent through the existing factory and use its declared
        # permissions (the factory enforces dangerous-permission
        # authorization, so an unprivileged run can never self-escalate).
        if permissions is None:
            if agent_factory is None:
                raise ValueError(
                    f"{RuntimeErrorCode.WORKFLOW_INVALID}: permissions are required "
                    "when no agent factory is provided"
                )
            permissions, agent_name = self._resolve_agent(
                agent_factory, requirement, tuple(capabilities)
            )
        granted = set(permissions)

        workflow = self.workflow_repository.update(
            workflow,
            {
                "status": WorkflowStatus.RUNNING,
                "started_at": datetime.now(timezone.utc),
                "requirement": requirement,
                "resolved_capabilities": resolved_capabilities,
                "steps": [],
                "results": {},
                "evaluation": None,
                "error_message": None,
                "progress_percentage": 5,
            },
        )

        steps: list[dict[str, Any]] = [
            {
                "capability": capability,
                "agent_name": agent_name,
                "status": "Pending",
                "result": None,
                "error": None,
            }
            for capability in capabilities
        ]
        workflow = self.workflow_repository.update(workflow, {"steps": steps})

        # Pre-flight: refuse to run when any required capability is
        # unregistered, unconfigured, or unauthorized — never fake it.
        blockers: list[tuple[str, str, str]] = []
        for step in steps:
            resolution = self.capability_service.resolve(
                step["capability"], granted
            )
            if not resolution.exists:
                blockers.append(
                    (
                        step["capability"],
                        "capability is not registered",
                        RuntimeErrorCode.CAPABILITY_NOT_FOUND,
                    )
                )
                continue
            if resolution.permissions_sufficient is False:
                blockers.append(
                    (
                        step["capability"],
                        "missing required permissions: "
                        + ", ".join(resolution.missing_permissions),
                        RuntimeErrorCode.PERMISSION_DENIED,
                    )
                )
                continue
            if not resolution.available:
                integration_blockers = self._integration_blockers(
                    step["capability"], granted
                )
                if integration_blockers:
                    blockers.extend(integration_blockers)
                else:
                    blockers.append(
                        (
                            step["capability"],
                            "required capability is unavailable: "
                            + (resolution.reason or ""),
                            RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED,
                        )
                    )
        if blockers:
            blocked_capabilities = {capability for capability, _, _ in blockers}
            for step in steps:
                if step["capability"] in blocked_capabilities:
                    step["status"] = "Blocked"
                    step["error"] = next(
                        reason
                        for capability, reason, _ in blockers
                        if capability == step["capability"]
                    )
            workflow = self.workflow_repository.update(workflow, {"steps": steps})
            # Persist one honest BLOCKED runtime execution per blocked
            # capability with the precise blocker reason and code (no
            # dispatch, no fabricated success).
            blocked_reasons: dict[str, list[str]] = {}
            blocked_codes: dict[str, str] = {}
            for capability, reason, code in blockers:
                blocked_reasons.setdefault(capability, []).append(reason)
                blocked_codes.setdefault(capability, code)
            executions = [
                self.execute(
                    capability,
                    derive_workflow_input(requirement),
                    granted,
                    workflow_id=workflow_id,
                    agent_name=agent_name,
                    expected_error="; ".join(blocked_reasons[capability]),
                    expected_code=blocked_codes[capability],
                )
                for capability in blocked_reasons
            ]
            message = "required capabilities are not available: " + "; ".join(
                dict.fromkeys(
                    f"capability '{capability}' {reason}"
                    for capability, reason, _ in blockers
                )
            )
            return self._fail_run(workflow, message, executions=executions)

        executions: list[RuntimeExecutionResponse] = []
        for step in steps:
            execution = self.execute(
                step["capability"],
                derive_workflow_input(requirement),
                granted,
                workflow_id=workflow_id,
                agent_name=agent_name,
            )
            executions.append(execution)
            step["status"] = (
                "Completed" if execution.status is RuntimeExecutionStatus.SUCCEEDED else "Failed"
            )
            step["result"] = execution.output
            step["error"] = execution.error

        results: dict[str, Any] = {}
        for step in steps:
            if step["result"] is not None:
                results[step["capability"]] = step["result"]

        completed_steps = sum(1 for step in steps if step["status"] == "Completed")
        failed_steps = len(steps) - completed_steps
        passed = failed_steps == 0
        evaluation = {
            "status": "Passed" if passed else "Failed",
            "passed": passed,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "total_steps": len(steps),
            "summary": (
                f"Executed {len(steps)} capability step(s) through the execution "
                f"runtime: {completed_steps} completed, {failed_steps} failed."
            ),
        }

        updates: dict[str, Any] = {
            "steps": steps,
            "results": results,
            "evaluation": evaluation,
            "progress_percentage": 100 if passed else 40,
            "completed_at": datetime.now(timezone.utc),
        }
        if passed:
            updates["status"] = WorkflowStatus.COMPLETED
        else:
            updates["status"] = WorkflowStatus.FAILED
            updates["error_message"] = f"{failed_steps} of {len(steps)} capability step(s) failed"
        workflow = self.workflow_repository.update(workflow, updates)
        return RuntimeWorkflowRunResponse(
            workflow=WorkflowResponse.model_validate(workflow),
            executions=executions,
        )

    def retry_workflow(
        self,
        workflow_id: UUID,
        permissions: set[Permission] | list[Permission] | None = None,
        agent_name: str | None = None,
        agent_factory: AgentFactoryService | None = None,
    ) -> RuntimeWorkflowRunResponse:
        """Retry a failed workflow by cloning it into a fresh run instance.

        The failed workflow is kept intact (history retained); a new run
        instance is created from its requirement/capability plan and
        executed through the same runtime path. ``agent_factory`` is
        required when ``permissions`` are omitted (same contract as
        :meth:`run_workflow`).
        """
        if self.workflow_repository is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow repository is required "
                "to retry a workflow"
            )
        workflow = self.workflow_repository.get(workflow_id)
        if workflow is None:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow not found: {workflow_id}"
            )
        if workflow.status is not WorkflowStatus.FAILED:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: only failed workflows can be "
                f"retried (current status: {workflow.status.value})"
            )
        requirement = workflow.requirement
        if not requirement:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: workflow has no requirement "
                "to retry"
            )
        instance = self.workflow_repository.create(
            WorkflowCreateRequest(
                project_id=workflow.project_id,
                name=f"{workflow.name} · retry",
            )
        )
        instance = self.workflow_repository.update(
            instance,
            {
                "requirement": requirement,
                "scheduled_from_id": workflow.id,
            },
        )
        # The fresh instance re-resolves its execution capabilities from the
        # requirement (identical to the manual path) — never the original's
        # full matched registry list.
        return self.run_workflow(
            instance.id,
            requirement=requirement,
            permissions=permissions,
            agent_name=agent_name,
            agent_factory=agent_factory,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _integration_blockers(
        self,
        capability: str,
        granted: set[Permission],
    ) -> list[tuple[str, str, str]]:
        """Return why a capability cannot run against the integration registry.

        Mirrors ``WorkflowService._step_integration_blockers`` so the
        persisted reason names the exact unavailable integration capability
        (e.g. ``web.search``) — honest, never fabricated.
        """
        try:
            spec = capability_spec(capability)
        except ValueError:
            return []
        registry = self.capability_service.integration_registry
        if registry is None:
            return []
        blockers: list[tuple[str, str, str]] = []
        for capability_name in spec.integration_capabilities:
            integration = integration_for_capability(capability_name)
            connector = registry.get_connector(integration)
            if connector is None:
                blockers.append(
                    (
                        capability,
                        f"required integration '{integration}' is not registered",
                        RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED,
                    )
                )
                continue
            available, reason = connector.capability_available(capability_name)
            if not available:
                blockers.append(
                    (
                        capability,
                        f"required capability '{capability_name}' is unavailable: {reason}",
                        RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED,
                    )
                )
            required = getattr(connector, "CAPABILITY_PERMISSIONS", {}).get(
                capability_name
            )
            if required is not None and required not in granted:
                blockers.append(
                    (
                        capability,
                        (
                            f"capability '{capability_name}' requires permission "
                            f"'{required.value}', which was not granted"
                        ),
                        RuntimeErrorCode.PERMISSION_DENIED,
                    )
                )
        return blockers

    def _resolve_agent(
        self,
        agent_factory: AgentFactoryService,
        requirement: str,
        capabilities: tuple[str, ...],
    ) -> tuple[set[Permission], str]:
        """Reuse/create the agent for the capability set; return its permissions."""
        try:
            resolved = agent_factory.resolve_for_capabilities(requirement, capabilities)
            if resolved.agent is not None:
                return set(resolved.agent.permissions), resolved.agent.name
            spec = resolved.specification
            assert spec is not None
            agent = agent_factory.create_agent(
                AgentCreateRequest(
                    name=spec.name,
                    purpose=spec.purpose,
                    required_capabilities=list(spec.capabilities),
                )
            )
            return set(agent.permissions), agent.name
        except ValueError as exc:
            raise ValueError(
                f"{RuntimeErrorCode.WORKFLOW_INVALID}: could not resolve an executing "
                f"agent: {exc}"
            ) from exc

    def _finish(
        self,
        execution: RuntimeExecution,
        output: dict[str, Any] | None,
        error: str | None = None,
        code: str | None = None,
        status: RuntimeExecutionStatus | None = None,
    ) -> RuntimeExecutionResponse:
        """Persist the final execution state (succeeded/failed/blocked)."""
        if error:
            final_status = status or RuntimeExecutionStatus.FAILED
            updates: dict[str, Any] = {
                "status": final_status,
                "error": error,
                "error_code": code or self._derive_code(error),
                "completed_at": datetime.now(timezone.utc),
            }
            if output is not None:
                updates["output"] = output
        else:
            updates = {
                "status": RuntimeExecutionStatus.SUCCEEDED,
                "output": output,
                "error_code": None,
                "completed_at": datetime.now(timezone.utc),
            }
        execution = self.repository.update(execution, updates)
        logger.info(
            "runtime execution of '%s' -> %s%s",
            execution.capability,
            execution.status.value,
            f" ({execution.error_code}: {execution.error})" if execution.error else "",
        )
        return self._to_response(execution)

    def _approved_context(self, workflow_id: UUID | None) -> bool:
        """Return whether execution runs inside an approved workflow context.

        Publishing/external-write capabilities are gated on approval: they
        may only execute under a workflow whose requirement has been
        approved (the same marker :meth:`run_workflow` requires). When the
        approval cannot be verified the gate fails closed.
        """
        if workflow_id is None:
            return False
        if self.workflow_repository is None:
            return False
        workflow = self.workflow_repository.get(workflow_id)
        if workflow is None:
            return False
        return bool(workflow.requirement)

    @staticmethod
    def _derive_code(error: str) -> str:
        """Derive a stable error code from a human-readable error."""
        if "APPROVAL_REQUIRED" in error:
            return RuntimeErrorCode.APPROVAL_REQUIRED
        if "INTEGRATION_NOT_CONFIGURED" in error:
            return RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED
        if "missing required permissions" in error or "requires permission" in error:
            return RuntimeErrorCode.PERMISSION_DENIED
        if "not registered" in error:
            return RuntimeErrorCode.CAPABILITY_NOT_FOUND
        return RuntimeErrorCode.EXECUTION_FAILED

    def _fail_run(
        self,
        workflow: Any,
        message: str,
        executions: Sequence[RuntimeExecutionResponse],
    ) -> RuntimeWorkflowRunResponse:
        """Persist a failed workflow runtime run with its honest reason."""
        workflow = self.workflow_repository.update(
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
        return RuntimeWorkflowRunResponse(
            workflow=WorkflowResponse.model_validate(workflow),
            executions=list(executions),
        )

    @staticmethod
    def _to_response(execution: RuntimeExecution) -> RuntimeExecutionResponse:
        return RuntimeExecutionResponse.model_validate(execution)
