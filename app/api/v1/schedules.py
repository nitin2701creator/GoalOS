"""GoalOS persisted scheduler API.

Schedules are persisted on existing workflows and survive restart. Due
runs execute through the SAME execution runtime as manual runs; this API
only manages the schedule and triggers runs — it never bypasses
permissions (``scheduler.create`` requires ``SCHEDULE_WORKFLOWS`` and
every run goes through the runtime's permission gates).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.integrations.factory import build_default_registry
from app.integrations.scheduler import SchedulerConnector
from app.llm.provider_factory import ProviderFactory
from app.repositories.agent_repository import AgentRepository
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.runtime_execution import RuntimeWorkflowRunResponse
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleResponse,
    SchedulerTickResponse,
)
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.scheduler_service import SchedulerService

router = APIRouter()


def _scheduler_service(db) -> SchedulerService:
    """Compose the scheduler service per request (existing conventions)."""
    provider = None
    try:
        provider = ProviderFactory.create()
    except ValueError:
        provider = None
    capability_service = CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
        llm_provider=provider,
    )
    workflow_repository = WorkflowRepository(db)
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        capability_service,
        workflow_repository=workflow_repository,
    )
    agent_factory = AgentFactoryService(AgentRepository(db), SkillRepository(db))
    return SchedulerService(
        SchedulerConnector(db=db),
        workflow_repository,
        runtime,
        agent_factory,
    )


def _service(db=Depends(get_db)) -> SchedulerService:
    return _scheduler_service(db)


@router.get("", response_model=list[ScheduleResponse])
def list_schedules(service: SchedulerService = Depends(_service)):
    """List every persisted schedule with its run-history summary."""
    return service.list_schedules()


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a schedule",
    description=(
        "Schedule an existing workflow. Requires the explicit "
        "SCHEDULE_WORKFLOWS permission in ``permissions`` — never "
        "granted implicitly."
    ),
)
def create_schedule(
    request: ScheduleCreateRequest,
    service: SchedulerService = Depends(_service),
):
    try:
        result = service.create_schedule(
            request.workflow_id,
            request.schedule,
            requirement=request.requirement,
            permissions=set(request.permissions),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post(
    "/run-due",
    response_model=SchedulerTickResponse,
    summary="Execute every due scheduled workflow now",
    description=(
        "Run one scheduler poll immediately: each due workflow is claimed "
        "atomically and executed through the execution runtime as a fresh "
        "run instance. Duplicate loops cannot double-execute a run."
    ),
)
def run_due(service: SchedulerService = Depends(_service)):
    return service.run_due()


@router.post(
    "/{workflow_id}/run-now",
    response_model=RuntimeWorkflowRunResponse,
    summary="Manually trigger one scheduled workflow now",
)
def run_now(
    workflow_id: UUID,
    service: SchedulerService = Depends(_service),
):
    try:
        return service.run_now(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/{workflow_id}/disable", response_model=ScheduleResponse)
def disable_schedule(
    workflow_id: UUID,
    service: SchedulerService = Depends(_service),
):
    """Pause a schedule (definition kept; resume via /enable)."""
    try:
        return service.disable_schedule(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/{workflow_id}/enable", response_model=ScheduleResponse)
def enable_schedule(
    workflow_id: UUID,
    service: SchedulerService = Depends(_service),
):
    """Resume a paused schedule."""
    try:
        return service.enable_schedule(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete(
    "/{workflow_id}",
    response_model=ScheduleResponse,
    summary="Cancel a schedule",
)
def cancel_schedule(
    workflow_id: UUID,
    service: SchedulerService = Depends(_service),
):
    """Hard-cancel a schedule (the workflow itself is kept)."""
    try:
        return service.cancel_schedule(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
