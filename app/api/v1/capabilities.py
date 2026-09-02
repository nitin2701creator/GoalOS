"""Capability engine API endpoints.

GoalOS can list, resolve, match, and execute capabilities through the
persistent registry. Execution never fabricates: an unconfigured provider
reports INTEGRATION_NOT_CONFIGURED and insufficient permissions report
PERMISSION_DENIED.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.integrations.factory import build_default_registry
from app.llm.provider_factory import ProviderFactory
from app.repositories.capability_repository import CapabilityRepository
from app.schemas.capability import (
    CapabilityCreateRequest,
    CapabilityExecuteRequest,
    CapabilityExecuteResponse,
    CapabilityGoalResolution,
    CapabilityMatchRequest,
    CapabilityResolveManyRequest,
    CapabilityResolveRequest,
    CapabilityResolveResponse,
    CapabilityResponse,
)
from app.services.capability_service import CapabilityService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> CapabilityService:
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


@router.get("")
def list_capabilities(service: CapabilityService = Depends(_get_service)):
    """List every registered capability with its honest availability."""
    capabilities = service.list_with_status()
    return {"capabilities": capabilities, "total": len(capabilities)}


@router.get("/discovery")
def discover_capabilities(service: CapabilityService = Depends(_get_service)):
    """Capability discovery endpoint for LibreChat and external consumers.

    Returns a simplified catalog optimized for tool/function-calling
    integrations: each capability includes its name, description,
    input/output schemas, required permissions, and approval status.
    Only enabled capabilities are included.
    """
    service.ensure_seeded()
    tools: list[dict[str, Any]] = []
    for capability in service.repository.list():
        if not capability.enabled:
            continue
        tools.append({
            "name": capability.name,
            "description": capability.description,
            "category": capability.category,
            "provider": capability.provider,
            "provider_type": capability.provider_type,
            "input_schema": capability.input_schema or {},
            "output_schema": capability.output_schema or {},
            "required_permissions": capability.required_permissions,
            "requires_approval": capability.requires_approval,
            "implementation": capability.implementation,
        })
    return {
        "tools": tools,
        "total": len(tools),
        "categories": sorted({t["category"] for t in tools}),
    }


@router.post("", response_model=CapabilityResponse, status_code=status.HTTP_201_CREATED)
def register_capability(
    request: CapabilityCreateRequest,
    service: CapabilityService = Depends(_get_service),
):
    """Register a capability; duplicate registration is idempotent."""
    return service.register(request)


@router.get("/{name}", response_model=CapabilityResolveResponse)
def get_capability(name: str, service: CapabilityService = Depends(_get_service)):
    """Resolve one capability: exists, enabled, available, permissions."""
    return service.resolve(name)


@router.post("/resolve", response_model=CapabilityResolveResponse)
def resolve_capability(
    request: CapabilityResolveRequest,
    service: CapabilityService = Depends(_get_service),
):
    """Resolve one capability by name."""
    return service.resolve(request.name)


@router.post("/resolve-many", response_model=list[CapabilityResolveResponse])
def resolve_capabilities(
    request: CapabilityResolveManyRequest,
    service: CapabilityService = Depends(_get_service),
):
    """Resolve several capabilities at once."""
    return service.resolve_many(request.names)


@router.post("/match", response_model=CapabilityGoalResolution)
def match_capabilities(
    request: CapabilityMatchRequest,
    service: CapabilityService = Depends(_get_service),
):
    """Resolve the capabilities required for a goal/requirement.

    Returns the matched registry capability names plus the deduplicated
    execution capabilities used to reuse/create the executing agent.
    """
    return service.resolve_for_goal(request.requirement)


@router.post("/{name}/execute", response_model=CapabilityExecuteResponse)
def execute_capability(
    name: str,
    request: CapabilityExecuteRequest,
    service: CapabilityService = Depends(_get_service),
):
    """Execute one capability through the existing runtime.

    ``permissions`` are the explicitly granted permissions of the calling
    agent/operator; the engine never escalates permissions implicitly.
    """
    return service.execute(name, request.params, set(request.permissions))


@router.post("/{name}/enable", response_model=CapabilityResponse)
def enable_capability(name: str, service: CapabilityService = Depends(_get_service)):
    result = service.enable(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability not found"
        )
    return result


@router.post("/{name}/disable", response_model=CapabilityResponse)
def disable_capability(name: str, service: CapabilityService = Depends(_get_service)):
    result = service.disable(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability not found"
        )
    return result
