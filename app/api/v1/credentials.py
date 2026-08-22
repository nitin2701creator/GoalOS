"""Credentials management API endpoints.

Provides encrypted storage, retrieval, and testing of integration
credentials. Secrets are never returned in plaintext. The dashboard
uses these endpoints to configure integrations.
"""

from __future__ import annotations

import logging
import secrets as _secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.services.credential_service import (
    INTEGRATION_FIELDS,
    CredentialService,
    _display_name,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Simple CSRF token store (in-memory, single-process)
# ---------------------------------------------------------------------------
_csrf_tokens: set[str] = set()


def _create_csrf() -> str:
    token = _secrets.token_urlsafe(32)
    _csrf_tokens.add(token)
    # Evict old tokens to bound memory
    if len(_csrf_tokens) > 500:
        to_remove = list(_csrf_tokens)[:250]
        for t in to_remove:
            _csrf_tokens.discard(t)
    return token


def _validate_csrf(token: str | None) -> bool:
    if not token:
        return False
    if token in _csrf_tokens:
        _csrf_tokens.discard(token)
        return True
    return False


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SaveCredentialsRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    csrf_token: str = Field(min_length=1)


class SaveCredentialsResponse(BaseModel):
    integration: str
    fields: list[dict]
    message: str


class TestConnectionResponse(BaseModel):
    integration: str
    status: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/csrf")
def get_csrf_token():
    """Get a fresh CSRF token for state-changing requests."""
    return {"csrf_token": _create_csrf()}


@router.get("")
def list_credentials(service: CredentialService = Depends(get_db)):
    """List all integrations that support credential configuration."""
    svc = CredentialService(service)
    integrations = svc.list_integrations_with_status()
    # Merge with full integration registry for health status
    from app.services.integration_service import IntegrationService

    reg_svc = IntegrationService(service)
    reg_svc.sync()
    registry = {i["name"]: i for i in reg_svc.list()}
    for item in integrations:
        reg = registry.get(item["name"])
        if reg:
            item["status"] = reg.get("status", "Not Configured")
            item["message"] = reg.get("message", "")
            item["enabled"] = reg.get("enabled", True)
            item["capabilities"] = reg.get("capabilities", [])
        else:
            item["status"] = "Not Registered"
            item["message"] = "Not registered in GoalOS connector registry"
            item["enabled"] = False
            item["capabilities"] = []
    return {"integrations": integrations}


@router.get("/{integration}")
def get_credentials(
    integration: str,
    service: CredentialService = Depends(get_db),
):
    """Get field definitions and masked values for one integration."""
    if integration not in INTEGRATION_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration}")
    svc = CredentialService(service)
    fields = svc.get_masked(integration)
    return {
        "integration": integration,
        "display_name": _display_name(integration),
        "fields": fields,
    }


@router.post("/{integration}")
def save_credentials(
    integration: str,
    request: SaveCredentialsRequest,
    service: CredentialService = Depends(get_db),
):
    """Save encrypted credentials for one integration."""
    if integration not in INTEGRATION_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration}")
    if not _validate_csrf(request.csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or expired CSRF token")
    svc = CredentialService(service)
    fields = svc.save(integration, request.values)
    return SaveCredentialsResponse(
        integration=integration,
        fields=fields,
        message=f"Credentials saved for {_display_name(integration)}",
    )


@router.post("/{integration}/test")
def test_credentials(
    integration: str,
    request: SaveCredentialsRequest | None = None,
    service: CredentialService = Depends(get_db),
):
    """Test the connection for one integration."""
    if integration not in INTEGRATION_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration}")
    if request and not _validate_csrf(request.csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or expired CSRF token")

    # Use the existing integration test endpoint
    from app.services.integration_service import IntegrationService

    reg_svc = IntegrationService(service)
    reg_svc.sync()
    result = reg_svc.test(integration)
    if result is None:
        return TestConnectionResponse(
            integration=integration,
            status="NOT_FOUND",
            message=f"Integration '{integration}' is not registered",
        )
    return TestConnectionResponse(
        integration=integration,
        status=result.status,
        message=result.message or "No message",
    )


@router.delete("/{integration}")
def delete_credentials(
    integration: str,
    service: CredentialService = Depends(get_db),
):
    """Delete all stored credentials for one integration."""
    if integration not in INTEGRATION_FIELDS:
        raise HTTPException(status_code=404, detail=f"Unknown integration: {integration}")
    svc = CredentialService(service)
    svc.delete(integration)
    return {"integration": integration, "message": f"Credentials deleted for {_display_name(integration)}"}
