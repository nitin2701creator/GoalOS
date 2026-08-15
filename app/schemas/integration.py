"""API schemas for the GoalOS integration execution foundation.

Integrations are the executable boundaries of the connector registry: each
one carries a name, a functional type, an enabled/disabled state, the
capabilities it exposes, and the *names* of the environment variables that
configure it (never their values). Execution results are structured and
never fabricated — an unconfigured integration reports
``INTEGRATION_NOT_CONFIGURED``, a disabled one ``DISABLED``, an unknown
one ``INTEGRATION_NOT_FOUND``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.permissions import Permission
from app.schemas.runtime_execution import RuntimeExecutionResponse


class IntegrationSummaryResponse(BaseModel):
    """Persisted registry representation of one integration."""

    id: UUID
    name: str
    integration_type: str
    description: str
    enabled: bool
    capabilities: list[str]
    #: Environment variable NAMES configuring the integration — never values.
    required_env_vars: list[str]
    #: Whether the connector is registered in the current runtime registry.
    registered: bool = True
    #: Live health snapshot (value of ConnectorHealthStatus).
    status: str | None = None
    message: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IntegrationUpdateRequest(BaseModel):
    """Enable/disable an integration (operator control)."""

    enabled: bool


class IntegrationExecuteRequest(BaseModel):
    """Execute one capability of an integration.

    ``permissions`` are the explicitly granted permissions of the calling
    agent/operator — the integration never escalates permissions
    implicitly. ``params`` are the structured capability parameters.
    """

    capability: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)


class IntegrationExecuteResponse(BaseModel):
    """Structured integration execution result — never a fabricated success.

    ``execution`` is the persisted runtime execution record (the audit
    trail entry for this integration run).
    """

    integration: str
    capability: str
    status: Literal[
        "OK",
        "INTEGRATION_NOT_CONFIGURED",
        "PERMISSION_DENIED",
        "DISABLED",
        "INTEGRATION_NOT_FOUND",
        "AUTHENTICATION_FAILED",
        "RATE_LIMITED",
        "ERROR",
    ]
    error_code: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    execution: RuntimeExecutionResponse | None = None


class IntegrationTestResponse(BaseModel):
    """Result of a health/test operation on one integration."""

    integration: str
    status: str
    message: str | None = None
    last_checked_at: datetime
