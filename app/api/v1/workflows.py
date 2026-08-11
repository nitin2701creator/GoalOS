from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.integrations.factory import build_default_registry
from app.llm.provider_factory import ProviderFactory
from app.repositories.agent_repository import AgentRepository
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.runtime_execution import (
    RuntimeWorkflowRunRequest,
    RuntimeWorkflowRunResponse,
)
from app.schemas.workflow import (
    AgentWorkflowRunRequest,
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.workflow_service import WorkflowService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> WorkflowService:
    workflow_repo = WorkflowRepository(db)
    execution_repo = ExecutionRepository(db)
    return WorkflowService(workflow_repo, execution_repo)


def _capability_service(db) -> CapabilityService:
    """Compose the capability engine per request (existing conventions)."""
    provider = None
    try:
        provider = ProviderFactory.create()
    except ValueError:
        provider = None
    return CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
        llm_provider=provider,
    )


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(service: WorkflowService = Depends(_get_service)):
    return service.list()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.get(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    request: WorkflowCreateRequest, service: WorkflowService = Depends(_get_service)
):
    return service.create(request)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    request: WorkflowUpdateRequest,
    service: WorkflowService = Depends(_get_service),
):
    result = service.update(workflow_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    ok = service.delete(workflow_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


@router.post("/{workflow_id}/start", response_model=WorkflowResponse)
def start_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.start(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/complete", response_model=WorkflowResponse)
def complete_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.complete(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/fail", response_model=WorkflowResponse)
def fail_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(_get_service),
):
    result = service.fail(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post(
    "/{workflow_id}/approve",
    response_model=WorkflowResponse,
    summary="Approve a workflow with its capability plan",
    description=(
        "Resolve the requirement into a capability plan and persist it on "
        "the workflow (requirement, resolved capabilities) without "
        "executing. The execution runtime accepts the approved workflow "
        "via POST /{workflow_id}/run-runtime."
    ),
)
def approve_workflow(
    workflow_id: UUID,
    request: AgentWorkflowRunRequest,
    service: WorkflowService = Depends(_get_service),
    db=Depends(get_db),
):
    """Approve a workflow with its resolved capability plan."""
    try:
        result = service.approve(
            workflow_id,
            request.requirement,
            capability_service=_capability_service(db),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post(
    "/{workflow_id}/run-runtime",
    response_model=RuntimeWorkflowRunResponse,
    summary="Run an approved workflow through the execution runtime",
    description=(
        "Accept an approved workflow from the workflow service, execute "
        "each capability step through the execution runtime (registry "
        "resolution, permission checks, provider dispatch), persist every "
        "step as a runtime execution, and update the workflow with the "
        "step results and evaluation. Unavailable integrations are "
        "reported honestly as INTEGRATION_NOT_CONFIGURED — never faked."
    ),
)
def run_workflow_runtime(
    workflow_id: UUID,
    request: RuntimeWorkflowRunRequest,
    service: WorkflowService = Depends(_get_service),
    db=Depends(get_db),
):
    """Run an approved workflow through the execution runtime."""
    agent_factory = AgentFactoryService(
        AgentRepository(db),
        SkillRepository(db),
    )
    capability_service = _capability_service(db)
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        capability_service,
        workflow_repository=WorkflowRepository(db),
    )
    try:
        result = runtime.run_workflow(
            workflow_id,
            requirement=request.requirement,
            capabilities=request.capabilities,
            permissions=set(request.permissions) if request.permissions is not None else None,
            agent_name=request.agent_name,
            agent_factory=agent_factory,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return result


@router.post("/{workflow_id}/run-agent", response_model=WorkflowResponse)
def run_agent_workflow(
    workflow_id: UUID,
    request: AgentWorkflowRunRequest,
    service: WorkflowService = Depends(_get_service),
    db=Depends(get_db),
):
    """Run an autonomous agent workflow against an existing workflow.

    GoalOS resolves the requirement into capabilities through the
    capability engine (persistent registry + optional LLM refinement),
    reuses or creates the agents/skills, executes them through the agent
    runtime, and persists the resolved capabilities, step results, and
    evaluation on the workflow.
    """
    agent_factory = AgentFactoryService(
        AgentRepository(db),
        SkillRepository(db),
    )
    integration_registry = build_default_registry(session=db)
    llm_provider = None
    try:
        llm_provider = ProviderFactory.create()
    except ValueError:
        llm_provider = None
    capability_service = CapabilityService(
        CapabilityRepository(db),
        integration_registry=integration_registry,
        llm_provider=llm_provider,
    )
    try:
        result = service.run_agent_workflow(
            workflow_id,
            request.requirement,
            agent_factory,
            integration_registry=integration_registry,
            capability_service=capability_service,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/pause", response_model=WorkflowResponse)
def pause_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(_get_service),
):
    """Pause a workflow and disable its schedule."""
    try:
        result = service.pause(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/resume", response_model=WorkflowResponse)
def resume_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(_get_service),
):
    """Resume a paused workflow and re-enable its schedule."""
    try:
        result = service.resume(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
def cancel_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(_get_service),
    db=Depends(get_db),
):
    """Cancel a workflow: terminal state, schedule disabled, in-flight
    capability executions cancelled (persisted as cancelled)."""
    try:
        result = service.cancel(workflow_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        _capability_service(db),
        workflow_repository=WorkflowRepository(db),
    )
    runtime.cancel_in_flight(workflow_id)
    return result


@router.post(
    "/{workflow_id}/retry",
    response_model=RuntimeWorkflowRunResponse,
    summary="Retry a failed workflow as a fresh run instance",
    description=(
        "Clone a failed workflow into a new run instance (history retained) "
        "and execute it through the execution runtime with the same "
        "requirement/capability plan and permission gates."
    ),
)
def retry_workflow(
    workflow_id: UUID,
    db=Depends(get_db),
):
    """Retry a failed workflow through the execution runtime."""
    agent_factory = AgentFactoryService(
        AgentRepository(db),
        SkillRepository(db),
    )
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        _capability_service(db),
        workflow_repository=WorkflowRepository(db),
    )
    try:
        return runtime.retry_workflow(workflow_id, agent_factory=agent_factory)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/{workflow_id}/progress", response_model=WorkflowResponse)
def progress_workflow(
    workflow_id: UUID,
    progress: int,
    service: WorkflowService = Depends(_get_service),
):
    result = service.progress(workflow_id, progress)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.get("/project/{project_id}", response_model=list[WorkflowResponse])
def list_workflows_by_project(
    project_id: UUID, service: WorkflowService = Depends(_get_service)
):
    result = service.list_by_project(project_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result
