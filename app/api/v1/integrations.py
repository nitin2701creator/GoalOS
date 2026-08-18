"""Integration registry and execution API endpoints.

Integrations are executable boundaries over the connector registry: each
one can be listed, inspected, health-tested, enabled/disabled, and
executed (one capability at a time, fully persisted as a runtime
execution record). Execution is honest — an unconfigured integration
reports ``INTEGRATION_NOT_CONFIGURED``, a disabled one ``DISABLED``, an
unknown one ``INTEGRATION_NOT_FOUND``; never a fabricated success and
never a leaked secret.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.db.session import get_db
from app.integrations.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectorError,
    RateLimitError,
)
from app.schemas.integration import (
    IntegrationExecuteRequest,
    IntegrationExecuteResponse,
    IntegrationSummaryResponse,
    IntegrationTestResponse,
    IntegrationUpdateRequest,
)
from app.services.google_oauth_service import GoogleOAuthService
from app.services.integration_service import IntegrationService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> IntegrationService:
    """Compose the integration service per request (existing conventions)."""
    return IntegrationService(db)


def _get_google_service(db=Depends(get_db)) -> GoogleOAuthService:
    """Compose the Google OAuth web-flow service per request."""
    return GoogleOAuthService(db)


# ----------------------------------------------------------------------
# Google OAuth web flow
#
# These routes implement the interactive consent flow that mints the
# refresh token powering the Gmail, Calendar, and Drive integrations.
# The redirect URI is read from GOOGLE_REDIRECT_URI (environment-driven,
# never hard-coded); it must match the callback path below exactly.
# No token is ever exposed in a response.
# ----------------------------------------------------------------------


@router.get("/google/authorize")
def google_authorize(
    scope: str | None = None,
    state: str | None = None,
    service: GoogleOAuthService = Depends(_get_google_service),
):
    """Redirect the browser to Google's consent screen.

    Requires ``GOOGLE_CLIENT_ID``, ``GOOGLE_CLIENT_SECRET`` and
    ``GOOGLE_REDIRECT_URI`` to be configured; otherwise returns 400
    listing only the missing variable names.
    """
    try:
        url = service.authorize_url(scope=scope, state=state)
    except ConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url=url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/google/callback")
def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    service: GoogleOAuthService = Depends(_get_google_service),
):
    """Receive Google's redirect, exchange the code, store the token.

    On success the refresh token is persisted and activated (available to
    Gmail, Calendar, and Drive immediately) and a simple success response
    is returned — suitable for a browser. Failures return structured
    errors without ever exposing tokens or the client secret.
    """
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google authorization failed: {error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="missing 'code' or 'state' query parameters",
        )
    try:
        result = service.handle_callback(code=code, state=state)
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except ConnectorError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google OAuth token exchange failed",
        ) from exc
    return {
        "status": "success",
        "message": "Google OAuth is configured for Gmail, Calendar, and Drive",
        **result,
    }


@router.get("")
def list_integrations(service: IntegrationService = Depends(_get_service)):
    """List every registered integration and its configuration state.

    ``sync`` first makes the persisted registry match the connector
    registry (idempotent, preserves operator-set enabled state). Only
    configuration *state* and env var *names* are exposed — never
    credentials or values.
    """
    service.sync()
    integrations = service.list()
    return {"integrations": integrations, "total": len(integrations)}


@router.get("/{name}", response_model=IntegrationSummaryResponse)
def get_integration(name: str, service: IntegrationService = Depends(_get_service)):
    """Return one integration with its live health snapshot."""
    service.sync()
    result = service.get(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result


@router.post("/{name}/test", response_model=IntegrationTestResponse)
def test_integration(name: str, service: IntegrationService = Depends(_get_service)):
    """Run the health/test operation and cache the health snapshot."""
    service.sync()
    result = service.test(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result


@router.post("/{name}/execute", response_model=IntegrationExecuteResponse)
def execute_integration(
    name: str,
    request: IntegrationExecuteRequest,
    service: IntegrationService = Depends(_get_service),
):
    """Execute one capability of an integration, fully persisted.

    The run is recorded in ``runtime_executions`` (the same audit trail
    as the execution runtime) and returned with the structured outcome.
    """
    service.sync()
    return service.execute(
        name,
        request.capability,
        request.params,
        request.permissions,
    )


@router.get("/{name}/executions")
def integration_executions(
    name: str,
    capability: str | None = None,
    service: IntegrationService = Depends(_get_service),
):
    """Return the persisted execution history for one integration."""
    service.sync()
    if service.get(name) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    executions = service.execution_history(name, capability=capability)
    return {"integration": name, "executions": executions, "total": len(executions)}


@router.patch("/{name}", response_model=IntegrationSummaryResponse)
def update_integration(
    name: str,
    request: IntegrationUpdateRequest,
    service: IntegrationService = Depends(_get_service),
):
    """Enable/disable an integration (operator control)."""
    service.sync()
    result = service.set_enabled(name, request.enabled)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result
