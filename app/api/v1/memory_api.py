"""Memory Manager API endpoints.

POST /api/v1/memory/remember — store a memory.
POST /api/v1/memory/search — search/recall memories.
GET  /api/v1/memory/context/{entity} — get aggregated context.
POST /api/v1/memory/forget — soft-delete a memory.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.memory import MemoryQuery
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import (
    ContextResponse,
    MemoryForgetRequest,
    MemoryRememberRequest,
    MemoryResponse,
    MemorySearchRequest,
)
from app.services.memory_service import MemoryProvider

router = APIRouter()


def _get_provider(db=Depends(get_db)) -> MemoryProvider:
    return MemoryProvider(MemoryRepository(db))


@router.post("/remember", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def remember(
    request: MemoryRememberRequest,
    provider: MemoryProvider = Depends(_get_provider),
):
    """Store a new memory record."""
    result = provider.remember(
        entity=request.entity,
        content=request.content,
        memory_type=request.memory_type,
        importance=request.importance,
        confidence=request.confidence,
        goal=request.goal,
        project=request.project,
        conversation=request.conversation,
        source=request.source,
        metadata=request.metadata,
    )
    return result


@router.post("/search", response_model=list[MemoryResponse])
def search_memories(
    request: MemorySearchRequest,
    provider: MemoryProvider = Depends(_get_provider),
):
    """Search/recall memories matching the query."""
    query = MemoryQuery(
        entity=request.entity,
        query=request.query,
        goal=request.goal,
        project=request.project,
        conversation=request.conversation,
        memory_type=request.memory_type,
        min_importance=request.min_importance,
        min_confidence=request.min_confidence,
        limit=request.limit,
        offset=request.offset,
    )
    return provider.search(query)


@router.get("/context/{entity}", response_model=ContextResponse)
def get_context(
    entity: str,
    limit: int = 20,
    provider: MemoryProvider = Depends(_get_provider),
):
    """Get aggregated context for an entity."""
    return provider.get_context(entity, limit=limit)


@router.post("/forget")
def forget_memory(
    request: MemoryForgetRequest,
    provider: MemoryProvider = Depends(_get_provider),
):
    """Soft-delete a memory record."""
    deleted = provider.forget(request.memory_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Memory not found",
        )
    return {"status": "deleted", "memory_id": str(request.memory_id)}
