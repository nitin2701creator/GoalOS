"""Structured agent definitions for the GoalOS agent factory.

Agents are created from deterministic, validated definitions — never from
free-form LLM text. An :class:`AgentDefinition` is a Pydantic model that
carries the full agent contract (name, purpose, instructions,
capabilities, skills, tools, actions, schemas, permissions,
dependencies, status, version) so it can be persisted, validated, and
executed consistently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities import capability_spec, resolve_capabilities
from app.agents.permissions import Permission, actions_for_permissions
from app.compat import StrEnum


class AgentStatus(StrEnum):
    """Lifecycle states of a GoalOS agent."""

    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    FAILED = "FAILED"


class AgentDefinition(BaseModel):
    """A complete, validated specification for a GoalOS agent.

    Attributes:
        name: Unique agent name.
        purpose: Business purpose of the agent.
        system_instructions: Instructions the agent operates under.
        capabilities: Capability names the agent implements.
        skills: Reusable skill names attached to the agent.
        tools: Tool names the agent may use.
        allowed_actions: Explicit action names the agent may take.
        input_schema: Structured input contract for execution.
        output_schema: Structured output contract for results.
        permissions: Explicit permissions the agent holds.
        dependencies: Names of resources the agent depends on.
        status: Current lifecycle status.
        version: Agent definition version.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    system_instructions: str = ""
    capabilities: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    integrations: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: tuple[Permission, ...] = ()
    dependencies: tuple[str, ...] = ()
    status: AgentStatus = AgentStatus.DRAFT
    version: str = "1.0"


def default_system_instructions(name: str, purpose: str) -> str:
    """Build deterministic system instructions for a generated agent."""
    return (
        f"You are {name}. Purpose: {purpose}. "
        "Operate only through your attached skills and declared permissions. "
        "Never access credentials, environment files, or private keys."
    )


def build_agent_definition(
    requirement: str,
    capabilities: tuple[str, ...],
    *,
    name: str | None = None,
    version: str = "1.0",
) -> AgentDefinition:
    """Build a deterministic agent definition from a capability set.

    The definition is derived from the capability catalog: skills, tools,
    permissions, and execution schemas come from the resolved capability
    requirements. Dangerous permissions are included in the definition's
    ``permissions`` as *required* permissions — activating the agent still
    requires the caller to declare them explicitly.

    Args:
        requirement: The original business requirement.
        capabilities: Ordered capability names to implement.
        name: Optional explicit agent name; defaults to a deterministic
            name derived from the first capability.
        version: Agent definition version.

    Returns:
        A structured agent definition.
    """
    resolved = tuple(capabilities) or resolve_capabilities(requirement)
    if not resolved:
        raise ValueError("no capabilities could be resolved from the requirement")

    skill_names: list[str] = []
    required_permissions: set[Permission] = set()
    tools: list[str] = []
    integrations: list[str] = []
    for capability in resolved:
        spec = capability_spec(capability)
        skill_names.append(spec.skill)
        required_permissions.update(spec.permissions)
        tools.extend(spec.tools)
        integrations.extend(spec.integrations)

    primary = resolved[0]
    agent_name = name or f"{primary.replace('_', ' ').title()} Agent"
    permissions = tuple(sorted(required_permissions, key=lambda item: item.value))

    return AgentDefinition(
        name=agent_name,
        purpose=requirement,
        system_instructions=default_system_instructions(agent_name, requirement),
        capabilities=resolved,
        skills=tuple(dict.fromkeys(skill_names)),
        tools=tuple(dict.fromkeys(tools)),
        integrations=tuple(dict.fromkeys(integrations)),
        allowed_actions=actions_for_permissions(permissions),
        permissions=permissions,
        dependencies=tuple(dict.fromkeys(skill_names)),
        version=version,
    )
