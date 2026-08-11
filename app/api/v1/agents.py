"""Agent factory API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.agent_repository import AgentRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import (
    AgentCreateRequest,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentResolveRequest,
    AgentResolveResponse,
    AgentResponse,
    AgentUpdateRequest,
)
from app.services.agent_factory import AgentFactoryService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> AgentFactoryService:
    agent_repo = AgentRepository(db)
    skill_repo = SkillRepository(db)
    return AgentFactoryService(agent_repo, skill_repo)


@router.post("/resolve", response_model=AgentResolveResponse)
def resolve_agent(
    request: AgentResolveRequest,
    service: AgentFactoryService = Depends(_get_service),
):
    """Resolve a capability requirement into an agent or a new specification."""
    try:
        return service.resolve(request.requirement)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[AgentResponse])
def list_agents(service: AgentFactoryService = Depends(_get_service)):
    return service.list_agents()


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    request: AgentCreateRequest,
    service: AgentFactoryService = Depends(_get_service),
):
    """Create, validate, and activate an agent from a specification."""
    try:
        return service.create_agent(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: UUID, service: AgentFactoryService = Depends(_get_service)):
    result = service.get_agent(agent_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return result


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: UUID,
    request: AgentUpdateRequest,
    service: AgentFactoryService = Depends(_get_service),
):
    try:
        return service.update_agent(agent_id, request)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc


@router.post("/{agent_id}/enable", response_model=AgentResponse)
def enable_agent(agent_id: UUID, service: AgentFactoryService = Depends(_get_service)):
    try:
        return service.enable_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc


@router.post("/{agent_id}/disable", response_model=AgentResponse)
def disable_agent(agent_id: UUID, service: AgentFactoryService = Depends(_get_service)):
    try:
        return service.disable_agent(agent_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc


@router.post("/{agent_id}/execute", response_model=AgentExecuteResponse)
def execute_agent(
    agent_id: UUID,
    request: AgentExecuteRequest,
    service: AgentFactoryService = Depends(_get_service),
):
    """Execute an ACTIVE agent through the existing agent runtime."""
    try:
        return service.execute_agent(agent_id, request.goal, request.input)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
