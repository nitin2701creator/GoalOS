"""API schemas for the GoalOS agent factory."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.agent_definitions import AgentStatus
from app.agents.permissions import Permission


class AgentCreateRequest(BaseModel):
    """Request to create an agent from a structured specification.

    Attributes:
        name: Unique agent name.
        purpose: Business purpose of the agent.
        system_instructions: Optional system instructions override.
        required_capabilities: Capabilities the agent must implement; when
            omitted they are resolved from ``name`` and ``purpose``.
        permissions: Explicit permissions the creator authorizes. Dangerous
            permissions required by the capabilities must appear here.
        allowed_actions: Optional explicit action allow-list.
        dependencies: Optional resource dependencies.
    """

    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1)
    system_instructions: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    permissions: list[Permission] | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class AgentUpdateRequest(BaseModel):
    """Optional fields an ACTIVE or DRAFT agent may update."""

    purpose: str | None = None
    system_instructions: str | None = None
    allowed_actions: list[str] | None = None
    dependencies: list[str] | None = None
    version: str | None = None


class AgentResponse(BaseModel):
    """API representation of a persisted agent definition."""

    id: UUID
    name: str
    purpose: str
    system_instructions: str
    capabilities: list[str]
    skills: list[str]
    tools: list[str]
    integrations: list[str] = Field(default_factory=list)
    allowed_actions: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[Permission]
    dependencies: list[str]
    status: AgentStatus
    status_reason: str | None = None
    version: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentResolveRequest(BaseModel):
    """Request to resolve a capability requirement into an agent."""

    requirement: str = Field(min_length=1)


class AgentSpecificationResponse(BaseModel):
    """A newly generated (not yet persisted) agent specification."""

    name: str
    purpose: str
    system_instructions: str
    capabilities: list[str]
    skills: list[str]
    tools: list[str]
    integrations: list[str] = Field(default_factory=list)
    allowed_actions: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    permissions: list[Permission]
    dependencies: list[str]
    version: str


class AgentResolveResponse(BaseModel):
    """Outcome of resolving a capability requirement.

    Either an existing ACTIVE agent covers the requirement, or a newly
    generated specification is returned for explicit confirmation.
    """

    agent: AgentResponse | None = None
    specification: AgentSpecificationResponse | None = None


class AgentExecuteRequest(BaseModel):
    """Request to execute an ACTIVE agent through the existing runtime."""

    goal: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


class AgentExecuteResponse(BaseModel):
    """Result of executing a dynamically created agent."""

    agent_name: str
    summary: str
    results: dict[str, Any]
    errors: list[str] = Field(default_factory=list)
