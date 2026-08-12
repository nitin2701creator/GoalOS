"""API schemas for the GoalOS capability engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.capability_definitions import CapabilityProviderType
from app.agents.permissions import Permission
from app.db.models.capability import CapabilityStatus


class CapabilityCreateRequest(BaseModel):
    """Request to register a capability (idempotent when already present)."""

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    category: str = "general"
    version: str = "1.0"
    required_permissions: list[Permission] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    provider_type: CapabilityProviderType
    provider: str = "native"
    implementation: str | None = None
    execution_capability: str | None = None
    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
    requires_approval: bool = False


class CapabilityResponse(BaseModel):
    """API representation of a persisted capability."""

    id: UUID
    name: str
    description: str
    category: str
    version: str
    status: CapabilityStatus
    required_permissions: list[Permission]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    provider_type: CapabilityProviderType
    provider: str
    implementation: str | None = None
    execution_capability: str | None = None
    keywords: list[str]
    enabled: bool
    requires_approval: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CapabilityResolveRequest(BaseModel):
    """Request to resolve a single capability by name."""

    name: str = Field(min_length=1)


class CapabilityResolveManyRequest(BaseModel):
    """Request to resolve several capabilities at once."""

    names: list[str] = Field(min_length=1)


class CapabilityResolveResponse(BaseModel):
    """Honest resolution outcome for one capability.

    ``available`` reflects whether the provider/implementation is
    actually configured and healthy — an unconfigured capability reports
    ``INTEGRATION_NOT_CONFIGURED`` in ``reason``, never a fabricated
    success.
    """

    name: str
    exists: bool
    enabled: bool
    available: bool
    reason: str | None = None
    required_permissions: list[Permission] = Field(default_factory=list)
    permissions_sufficient: bool | None = None
    missing_permissions: list[str] = Field(default_factory=list)
    provider_type: str | None = None
    provider: str | None = None
    implementation: str | None = None
    execution_capability: str | None = None
    description: str | None = None
    category: str | None = None
    requires_approval: bool = False


class CapabilityMatchRequest(BaseModel):
    """Request to match a goal/requirement against the capability registry."""

    requirement: str = Field(min_length=1)


class CapabilityMatchResult(BaseModel):
    """One capability matched to a requirement, and how it matched."""

    name: str
    description: str
    category: str
    source: Literal["keyword", "llm"]


class CapabilityGoalResolution(BaseModel):
    """Capabilities resolved for a goal plus the execution capability set.

    ``capabilities`` are the matched registry names; ``execution_capabilities``
    are the deduplicated catalog capabilities the agent factory uses to
    reuse/create the executing agent.
    """

    requirement: str
    capabilities: list[str] = Field(default_factory=list)
    execution_capabilities: list[str] = Field(default_factory=list)


class CapabilityExecuteRequest(BaseModel):
    """Request to execute a capability through the existing runtime.

    ``permissions`` are the explicitly granted permissions of the calling
    agent/operator — the engine never escalates permissions implicitly.
    """

    params: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)


class CapabilityExecuteResponse(BaseModel):
    """Structured execution result — never a fabricated success."""

    capability: str
    status: Literal[
        "OK",
        "INTEGRATION_NOT_CONFIGURED",
        "PERMISSION_DENIED",
        "DISABLED",
        "NOT_FOUND",
        "ERROR",
    ]
    provider: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
