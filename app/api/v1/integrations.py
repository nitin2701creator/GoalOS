"""Integration discovery API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.db.session import get_db
from app.integrations.factory import build_default_registry

router = APIRouter()


@router.get("")
def list_integrations(db=Depends(get_db)):
    """List every registered integration and its configuration state.

    Only configuration *state* is exposed — never credentials. Values are
    intentionally omitted so this endpoint is safe to call from the UI.
    """
    registry = build_default_registry(session=db)
    integrations = []
    for name in registry.list_connectors():
        connector = registry.get_connector(name)
        assert connector is not None
        health = connector.health_check()
        integrations.append(
            {
                "name": name,
                "description": connector.description,
                "status": health.status.value,
                "message": health.message,
                "capabilities": list(connector.get_capabilities()),
            }
        )
    return {"integrations": integrations, "total": len(integrations)}
