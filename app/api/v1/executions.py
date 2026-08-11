from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.integrations.factory import build_default_registry
from app.kernel.development.executors import create_coding_executor
from app.llm.provider_factory import ProviderFactory
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.execution import (
    ExecutionCompleteRequest,
    ExecutionCreateRequest,
    ExecutionFailRequest,
    ExecutionResponse,
    ExecutionUpdateRequest,
    TaskExecuteRequest,
)
from app.schemas.runtime_execution import (
    RuntimeExecuteRequest,
    RuntimeExecutionResponse,
)
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.execution_service import ExecutionService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ExecutionService:
    repo = ExecutionRepository(db)
    return ExecutionService(repo, TaskRepository(db))


def _get_runtime_service(db=Depends(get_db)) -> ExecutionRuntimeService:
    """Compose the execution runtime per request (existing conventions)."""
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
    return ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        capability_service,
        workflow_repository=WorkflowRepository(db),
    )


def _repository_path() -> Path:
    """Return the repository root CLI workers should run in."""
    configured = os.getenv("GOALOS_REPOSITORY")
    return Path(configured) if configured else Path.cwd()


@router.get(
    "/executions/runtime",
    response_model=list[RuntimeExecutionResponse],
    summary="List capability runtime executions",
    description=(
        "List persisted capability executions; filter by workflow with "
        "``?workflow_id=...``, by status (``?status=failed``), or by "
        "capability (``?capability=web_search``). Each record carries the "
        "capability, status (pending/running/succeeded/failed/blocked/"
        "cancelled), inputs, outputs, errors, error codes, timestamps, "
        "and execution metadata."
    ),
)
def list_runtime_executions(
    workflow_id: UUID | None = None,
    status: str | None = None,
    capability: str | None = None,
    service: ExecutionRuntimeService = Depends(_get_runtime_service),
):
    return service.list_filtered(
        workflow_id=workflow_id,
        status=status,
        capability=capability,
    )


@router.post(
    "/executions/runtime",
    response_model=RuntimeExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute one capability through the execution runtime",
    description=(
        "Resolve the capability through the registry, check the existing "
        "permission system, execute through the runtime, and persist the "
        "full lifecycle. Unavailable providers persist as failed with the "
        "honest INTEGRATION_NOT_CONFIGURED reason — never a fake success."
    ),
)
def execute_runtime_capability(
    request: RuntimeExecuteRequest,
    service: ExecutionRuntimeService = Depends(_get_runtime_service),
):
    try:
        return service.execute(
            request.capability,
            request.params,
            set(request.permissions),
            workflow_id=request.workflow_id,
            agent_name=request.agent_name,
            metadata=request.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/executions/runtime/{execution_id}", response_model=RuntimeExecutionResponse)
def get_runtime_execution(
    execution_id: UUID,
    service: ExecutionRuntimeService = Depends(_get_runtime_service),
):
    result = service.get(execution_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime execution not found"
        )
    return result


@router.post(
    "/executions/runtime/{execution_id}/retry",
    response_model=RuntimeExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Retry a failed capability execution",
    description=(
        "Re-execute a failed/blocked/cancelled capability as a fresh "
        "execution record (the original stays for history). The granted "
        "permissions are restored from the previous attempt — never "
        "escalated."
    ),
)
def retry_runtime_execution(
    execution_id: UUID,
    service: ExecutionRuntimeService = Depends(_get_runtime_service),
):
    try:
        result = service.retry(execution_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime execution not found"
        )
    return result


@router.get("/executions", response_model=list[ExecutionResponse])
def list_executions(service: ExecutionService = Depends(_get_service)):
    return service.list_executions()


@router.post("/executions", response_model=ExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_execution(
    request: ExecutionCreateRequest, service: ExecutionService = Depends(_get_service)
):
    try:
        return service.create_execution(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
def get_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.get(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.patch("/executions/{execution_id}", response_model=ExecutionResponse)
def update_execution(
    execution_id: UUID,
    request: ExecutionUpdateRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.update_execution(execution_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.delete("/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    ok = service.delete_execution(execution_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")


@router.get("/tasks/{task_id}/executions", response_model=list[ExecutionResponse])
def get_task_executions(task_id: UUID, service: ExecutionService = Depends(_get_service)):
    return service.list_task_executions(task_id)


@router.post(
    "/tasks/{task_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute a task end to end",
    description=(
        "Submit a task for execution, claim it for the named worker, run the "
        "worker, verify the result, and persist the execution outcome, "
        "verification verdict, and final task status."
    ),
)
def execute_task(
    task_id: UUID,
    request: TaskExecuteRequest,
    service: ExecutionService = Depends(_get_service),
):
    """Execute a persisted task through the full worker lifecycle."""
    try:
        return service.run_task(
            task_id,
            request.agent_name,
            worker_type=request.worker_type,
            repository=_repository_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_id}/autonomous-execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a task through the autonomous development loop",
    description=(
        "Inspect the repository, plan the change, implement it, run the test "
        "suite, repair failures within a bounded attempt limit, review, and "
        "commit only after verification passes. Every state transition and "
        "artifact (state, attempts, test results, errors, review results, "
        "result, commit hash) is persisted on the execution."
    ),
)
def execute_task_autonomously(
    task_id: UUID,
    request: TaskExecuteRequest,
    service: ExecutionService = Depends(_get_service),
):
    """Execute a persisted task through the autonomous development loop."""
    repository = _repository_path()
    executor = None
    if request.executor:
        try:
            executor = create_coding_executor(request.executor, repository=repository)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    try:
        return service.run_autonomous(
            task_id,
            request.agent_name,
            worker_type=request.worker_type,
            executor=executor,
            repository=repository,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/executions/{execution_id}/start", response_model=ExecutionResponse)
def start_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.start_execution(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/complete", response_model=ExecutionResponse)
def complete_execution(
    execution_id: UUID,
    request: ExecutionCompleteRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.complete_execution(execution_id, request.result)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/fail", response_model=ExecutionResponse)
def fail_execution(
    execution_id: UUID,
    request: ExecutionFailRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.fail_execution(execution_id, request.error_message)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/retry", response_model=ExecutionResponse)
def retry_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.retry_execution(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result
