"""Agent factory service for GoalOS.

The factory turns a business requirement into a validated, persisted,
executable agent:

1. Resolve the requirement into capabilities (deterministic keyword
   matching over the capability catalog).
2. Build a structured :class:`AgentDefinition` (never free-form LLM text).
3. Reuse existing skills or create missing ones from the builtin catalog.
4. Enforce explicit permissions — dangerous permissions must be declared
   by the caller before the agent may become ACTIVE.
5. Persist the agent through its lifecycle (DRAFT → VALIDATING → ACTIVE /
   FAILED, DISABLED) and register its runtime class in the existing
   :class:`AgentRegistry` so the orchestrator can discover it.

Execution reuses the existing :class:`BaseAgent` contract (plan/execute/
report with :class:`AgentContext`/:class:`AgentResult`) — no second
execution engine.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.agents.agent_definitions import (
    AgentDefinition,
    AgentStatus,
    build_agent_definition,
)
from app.agents.agent_registry import AgentRegistry
from app.agents.capabilities import capability_spec, resolve_capabilities
from app.agents.factory.dynamic_agent import DynamicAgent, build_dynamic_agent_class
from app.agents.factory.skill_implementations import SKILL_IMPLEMENTATIONS
from app.agents.permissions import DANGEROUS_PERMISSIONS, Permission
from app.db.models.agent import Agent
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.factory import integration_for_capability
from app.repositories.agent_repository import AgentRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import (
    AgentCreateRequest,
    AgentExecuteResponse,
    AgentResolveResponse,
    AgentResponse,
    AgentSpecificationResponse,
    AgentUpdateRequest,
)
from app.skills.definitions import BUILTIN_SKILLS
from app.skills.skill_registry import SkillRegistry


class AgentFactoryService:
    """Create, validate, register, and execute dynamically built agents.

    Args:
        agent_repository: Persistence for agent definitions.
        skill_repository: Persistence for reusable skill definitions.
        agent_registry: Runtime class registry the factory registers into;
            the orchestrator discovers dynamically created agents here.
        skill_registry: Runtime skill instance registry.
    """

    def __init__(
        self,
        agent_repository: AgentRepository,
        skill_repository: SkillRepository,
        agent_registry: AgentRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        integration_registry: ConnectorRegistry | None = None,
    ) -> None:
        self.agent_repository = agent_repository
        self.skill_repository = skill_repository
        self.agent_registry = agent_registry or AgentRegistry()
        self.skill_registry = skill_registry or SkillRegistry()
        self.integration_registry = integration_registry
        self._instances: dict[str, DynamicAgent] = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def create_agent(self, request: AgentCreateRequest) -> AgentResponse:
        """Create, validate, and activate an agent from a specification.

        Raises:
            ValueError: If the required permissions are not declared, a
                skill cannot be resolved, or the agent name is taken.
        """
        definition = self._definition_for_request(request)

        # Dangerous permissions are never granted implicitly. Every
        # dangerous permission a capability requires must be declared by
        # the caller; non-dangerous required permissions are granted.
        declared = set(request.permissions or ())
        required = set(definition.permissions)
        missing_dangerous = sorted(
            (required & DANGEROUS_PERMISSIONS) - declared,
            key=lambda permission: permission.value,
        )
        if missing_dangerous:
            names = ", ".join(permission.value for permission in missing_dangerous)
            raise ValueError(
                f"dangerous permissions require explicit authorization: {names}"
            )

        allowed = tuple(sorted(required | declared, key=lambda p: p.value))
        definition = definition.model_copy(update={"permissions": allowed})

        self._ensure_skills(definition.skills)

        agent = self.agent_repository.create(
            {
                "name": definition.name,
                "purpose": definition.purpose,
                "system_instructions": definition.system_instructions,
                "capabilities": list(definition.capabilities),
                "skills": list(definition.skills),
                "tools": list(definition.tools),
                "integrations": list(definition.integrations),
                "allowed_actions": list(definition.allowed_actions),
                "input_schema": definition.input_schema,
                "output_schema": definition.output_schema,
                "permissions": [permission.value for permission in definition.permissions],
                "dependencies": list(definition.dependencies),
                "status": AgentStatus.DRAFT,
                "status_reason": None,
                "version": definition.version,
            }
        )

        self.validate_agent(agent.id)
        return self.get_agent(agent.id) or self._to_response(agent)

    def _definition_for_request(self, request: AgentCreateRequest) -> AgentDefinition:
        """Derive the structured definition from a create request."""
        requirement = f"{request.name}. {request.purpose}"
        capabilities = tuple(request.required_capabilities) or resolve_capabilities(
            requirement
        )
        if not capabilities:
            raise ValueError(
                "no capabilities could be resolved from name/purpose; "
                "supply required_capabilities explicitly"
            )

        definition = build_agent_definition(
            request.purpose,
            capabilities,
            name=request.name,
        )
        if request.system_instructions:
            definition = definition.model_copy(
                update={"system_instructions": request.system_instructions}
            )
        if request.allowed_actions:
            definition = definition.model_copy(
                update={"allowed_actions": tuple(request.allowed_actions)}
            )
        if request.dependencies:
            definition = definition.model_copy(
                update={"dependencies": tuple(request.dependencies)}
            )

        # Execution schemas come from the attached skills so the agent's
        # contract is deterministic and non-empty.
        input_schema: dict[str, Any] = {}
        output_schema: dict[str, Any] = {}
        for skill_name in definition.skills:
            skill_definition = BUILTIN_SKILLS.get(skill_name)
            if skill_definition is not None:
                input_schema[skill_name] = skill_definition.input_schema
                output_schema[skill_name] = skill_definition.output_schema
        return definition.model_copy(
            update={"input_schema": input_schema, "output_schema": output_schema}
        )

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------
    def _ensure_skills(self, skill_names: tuple[str, ...]) -> None:
        """Reuse existing skills and create missing ones from the catalog.

        Raises:
            ValueError: If a needed skill has no definition or implementation.
        """
        for name in skill_names:
            existing = self.skill_repository.get_by_name(name)
            if existing is None:
                self._create_skill(name)
            elif not existing.enabled:
                raise ValueError(f"skill {name} is disabled")
            self._ensure_runtime_skill(name)

    def _create_skill(self, name: str) -> None:
        """Persist a skill definition from the builtin catalog."""
        definition = BUILTIN_SKILLS.get(name)
        if definition is None:
            raise ValueError(f"no skill definition available for {name}")
        self.skill_repository.create(
            {
                "name": definition.name,
                "description": definition.description,
                "instructions": definition.instructions,
                "required_tools": list(definition.required_tools),
                "required_integrations": list(definition.required_integrations),
                "input_schema": definition.input_schema,
                "output_schema": definition.output_schema,
                "permissions": [permission.value for permission in definition.permissions],
                "version": definition.version,
                "enabled": definition.enabled,
            }
        )

    def _ensure_runtime_skill(self, name: str) -> None:
        """Register the skill implementation instance once."""
        implementation_class = SKILL_IMPLEMENTATIONS.get(name)
        if implementation_class is None:
            raise ValueError(f"no skill implementation available for {name}")
        if self.skill_registry.get_skill(name) is None:
            self.skill_registry.register(implementation_class())

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_agent(self, agent_id: uuid.UUID) -> AgentResponse:
        """Validate an agent; ACTIVE only on success, otherwise FAILED.

        Raises:
            KeyError: If the agent does not exist.
        """
        agent = self._get_or_raise(agent_id)
        self.agent_repository.update(
            agent, {"status": AgentStatus.VALIDATING, "status_reason": None}
        )
        errors = self._validate_definition(agent)
        if errors:
            agent = self.agent_repository.get(agent_id)
            assert agent is not None
            self.agent_repository.update(
                agent,
                {
                    "status": AgentStatus.FAILED,
                    "status_reason": "; ".join(errors),
                },
            )
        else:
            agent = self.agent_repository.get(agent_id)
            assert agent is not None
            self.agent_repository.update(
                agent, {"status": AgentStatus.ACTIVE, "status_reason": None}
            )
            self._register_runtime(agent)
        return self.get_agent(agent_id) or self._to_response(agent)

    def _validate_definition(self, agent: Agent) -> list[str]:
        """Return the deterministic validation errors for an agent."""
        definition = self._definition_from_agent(agent)
        errors: list[str] = []

        if not definition.capabilities:
            errors.append("agent declares no capabilities")
        for capability in definition.capabilities:
            try:
                capability_spec(capability)
            except ValueError as exc:
                errors.append(str(exc))

        for skill_name in definition.skills:
            persisted = self.skill_repository.get_by_name(skill_name)
            if persisted is None:
                errors.append(f"skill {skill_name} is not registered")
            elif not persisted.enabled:
                errors.append(f"skill {skill_name} is disabled")
            if SKILL_IMPLEMENTATIONS.get(skill_name) is None:
                errors.append(f"skill {skill_name} has no runtime implementation")

        required_permissions: set[Permission] = set()
        for capability in definition.capabilities:
            try:
                required_permissions.update(capability_spec(capability).permissions)
            except ValueError:
                continue
        missing = sorted(
            required_permissions - set(definition.permissions),
            key=lambda permission: permission.value,
        )
        if missing:
            errors.append(
                "missing required permissions: "
                + ", ".join(permission.value for permission in missing)
            )

        if not definition.input_schema:
            errors.append("input schema is empty")
        if not definition.output_schema:
            errors.append("output schema is empty")
        return errors

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register_agent(self, agent_id: uuid.UUID) -> AgentResponse:
        """Register the agent's runtime class in the agent registry."""
        agent = self._get_or_raise(agent_id)
        self._register_runtime(agent)
        return self._to_response(agent)

    def _register_runtime(
        self,
        agent: Agent,
        integrations: ConnectorRegistry | None = None,
    ) -> None:
        """Register the dynamic agent class and prepare its instance.

        Runtime skill implementations are ensured here so a fresh
        composition root (or a restart) self-heals from the persisted
        definitions.
        """
        definition = self._definition_from_agent(agent)
        for skill_name in definition.skills:
            try:
                self._ensure_runtime_skill(skill_name)
            except ValueError:
                continue
        agent_class = build_dynamic_agent_class(definition)
        if self.agent_registry.get_agent(definition.name) is None:
            self.agent_registry.register(agent_class)
        skills = {
            name: implementation
            for name, implementation in self.skill_registry.snapshot().items()
            if name in definition.skills
        }
        instance = agent_class(
            definition,
            skill_implementations=skills,
            integrations=integrations if integrations is not None else self.integration_registry,
        )
        self._instances[definition.name] = instance

    def get_runtime_agent(self, name: str) -> DynamicAgent | None:
        """Return the registered runtime instance, if any."""
        return self._instances.get(name)

    # ------------------------------------------------------------------
    # Updates and lifecycle
    # ------------------------------------------------------------------
    def update_agent(self, agent_id: uuid.UUID, request: AgentUpdateRequest) -> AgentResponse:
        """Update an agent and re-validate it.

        Raises:
            KeyError: If the agent does not exist.
        """
        agent = self._get_or_raise(agent_id)
        was_disabled = agent.status is AgentStatus.DISABLED
        updates = request.model_dump(exclude_unset=True)
        if updates:
            self.agent_repository.update(agent, updates)
        self.validate_agent(agent_id)
        refreshed = self.agent_repository.get(agent_id)
        assert refreshed is not None
        if was_disabled and refreshed.status is AgentStatus.ACTIVE:
            refreshed = self.agent_repository.get(agent_id)
            assert refreshed is not None
            self.agent_repository.update(
                refreshed,
                {
                    "status": AgentStatus.DISABLED,
                    "status_reason": "disabled by operator",
                },
            )
        return self.get_agent(agent_id) or self._to_response(refreshed)

    def enable_agent(self, agent_id: uuid.UUID) -> AgentResponse:
        """Re-validate a DISABLED agent before activating it.

        Raises:
            KeyError: If the agent does not exist.
        """
        self.validate_agent(agent_id)
        refreshed = self.agent_repository.get(agent_id)
        assert refreshed is not None
        if refreshed.status == AgentStatus.FAILED:
            return self._to_response(refreshed)
        if refreshed.status is not AgentStatus.ACTIVE:
            refreshed = self.agent_repository.get(agent_id)
            assert refreshed is not None
            self.agent_repository.update(
                refreshed, {"status": AgentStatus.ACTIVE, "status_reason": None}
            )
            self._register_runtime(refreshed)
        return self.get_agent(agent_id) or self._to_response(refreshed)

    def disable_agent(self, agent_id: uuid.UUID) -> AgentResponse:
        """Disable an agent; it can no longer be executed."""
        agent = self._get_or_raise(agent_id)
        self.agent_repository.update(
            agent, {"status": AgentStatus.DISABLED, "status_reason": "disabled by operator"}
        )
        return self.get_agent(agent_id) or self._to_response(agent)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_agent(self, agent_id: uuid.UUID) -> AgentResponse | None:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            return None
        return self._to_response(agent)

    def get_agent_by_name(self, name: str) -> AgentResponse | None:
        agent = self.agent_repository.get_by_name(name)
        if agent is None:
            return None
        return self._to_response(agent)

    def list_agents(self) -> list[AgentResponse]:
        return [self._to_response(agent) for agent in self.agent_repository.list()]

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(self, requirement: str) -> AgentResolveResponse:
        """Resolve a requirement into an agent or a generated specification.

        An existing ACTIVE agent whose capabilities cover the requirement is
        returned; otherwise a deterministic specification is generated for
        explicit confirmation.

        Raises:
            ValueError: If no capabilities can be resolved from the
                requirement.
        """
        return self.resolve_for_capabilities(requirement, resolve_capabilities(requirement))

    def resolve_for_capabilities(
        self,
        requirement: str,
        capabilities: tuple[str, ...] | list[str],
    ) -> AgentResolveResponse:
        """Resolve an explicit capability set into an agent or a specification.

        ``resolve`` derives capabilities from the requirement text; this
        variant accepts a caller-supplied capability set (e.g. from a
        chat intent) so agent resolution cannot drift from the capabilities
        the orchestrator will execute.

        Raises:
            ValueError: If ``capabilities`` is empty.
        """
        resolved = tuple(capabilities)
        if not resolved:
            raise ValueError("no capabilities could be resolved from the requirement")

        for agent in self.agent_repository.list():
            if agent.status is not AgentStatus.ACTIVE:
                continue
            if set(resolved).issubset(set(agent.capabilities)):
                return AgentResolveResponse(agent=self._to_response(agent))
        return AgentResolveResponse(
            agent=None,
            specification=self._spec_for(requirement, resolved),
        )

    def _spec_for(
        self, requirement: str, capabilities: tuple[str, ...]
    ) -> AgentSpecificationResponse:
        """Build the deterministic specification for a capability set."""
        definition = build_agent_definition(requirement, capabilities)
        input_schema: dict[str, Any] = {}
        output_schema: dict[str, Any] = {}
        for skill_name in definition.skills:
            skill_definition = BUILTIN_SKILLS.get(skill_name)
            if skill_definition is not None:
                input_schema[skill_name] = skill_definition.input_schema
                output_schema[skill_name] = skill_definition.output_schema
        definition = definition.model_copy(
            update={"input_schema": input_schema, "output_schema": output_schema}
        )
        return self._to_specification(definition)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_agent(
        self,
        agent_id: uuid.UUID,
        goal: str,
        inputs: dict[str, Any],
        integrations: ConnectorRegistry | None = None,
    ) -> AgentExecuteResponse:
        """Execute an ACTIVE agent through the existing BaseAgent contract.

        Args:
            integrations: Optional integration registry; when provided,
                required integrations are enforced before execution and
                skills may call real connectors.

        Raises:
            KeyError: If the agent does not exist.
            ValueError: If the agent is not ACTIVE, required integrations
                are unavailable, or it has no runtime instance.
        """
        agent = self._get_or_raise(agent_id)
        if agent.status is not AgentStatus.ACTIVE:
            raise ValueError(f"agent {agent.name} is not ACTIVE")
        registry = integrations if integrations is not None else self.integration_registry
        if registry is not None:
            blockers = self.integration_blockers(agent, registry)
            if blockers:
                raise ValueError(
                    f"agent {agent.name} cannot execute: " + "; ".join(blockers)
                )
        # Self-heal: rebuild the runtime instance from the persisted
        # definition so execution survives a restart or a fresh
        # composition root.
        self._register_runtime(agent, integrations=registry)
        instance = self._instances.get(agent.name)
        if instance is None:
            raise ValueError(
                f"agent {agent.name} has no runtime instance; register it first"
            )
        if not instance.is_initialized:
            instance.initialize()

        from app.agents.base_agent import AgentContext

        context = AgentContext(goal=goal, metadata={"input": inputs})
        result = asyncio.run(instance.execute(context))
        skill_results = dict(result.metadata.get("skill_results") or {})
        errors = list(result.metadata.get("errors") or [])
        return AgentExecuteResponse(
            agent_name=result.agent_name,
            summary=result.summary,
            results=skill_results,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Integration enforcement
    # ------------------------------------------------------------------
    def integration_blockers(
        self,
        agent: Agent,
        registry: ConnectorRegistry,
    ) -> list[str]:
        """Return why ``agent`` cannot execute against ``registry``, if any.

        Checks every capability's required integration capabilities:
        registered, configured/available, and covered by the agent's
        declared permissions. Missing integration means a blocked agent —
        never a fabricated result.
        """
        definition = self._definition_from_agent(agent)
        blockers: list[str] = []
        for capability in definition.capabilities:
            try:
                spec = capability_spec(capability)
            except ValueError:
                continue
            for capability_name in spec.integration_capabilities:
                integration = integration_for_capability(capability_name)
                connector = registry.get_connector(integration)
                if connector is None:
                    blockers.append(
                        f"required integration '{integration}' is not registered"
                    )
                    continue
                available, reason = connector.capability_available(capability_name)
                if not available:
                    blockers.append(
                        f"required capability '{capability_name}' is unavailable: {reason}"
                    )
                required = getattr(connector, "CAPABILITY_PERMISSIONS", {}).get(
                    capability_name
                )
                if required is not None and required not in definition.permissions:
                    blockers.append(
                        f"capability '{capability_name}' requires permission "
                        f"'{required.value}', which the agent does not hold"
                    )
        return blockers

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_or_raise(self, agent_id: uuid.UUID) -> Agent:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise KeyError(f"agent not found: {agent_id}")
        return agent

    def _to_response(self, agent: Agent) -> AgentResponse:
        return AgentResponse(
            id=agent.id,
            name=agent.name,
            purpose=agent.purpose,
            system_instructions=agent.system_instructions,
            capabilities=list(agent.capabilities),
            skills=list(agent.skills),
            tools=list(agent.tools),
            integrations=list(agent.integrations or ()),
            allowed_actions=list(agent.allowed_actions),
            input_schema=agent.input_schema,
            output_schema=agent.output_schema,
            permissions=[Permission(value) for value in agent.permissions],
            dependencies=list(agent.dependencies),
            status=agent.status,
            status_reason=agent.status_reason,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def _to_specification(self, definition: AgentDefinition) -> AgentSpecificationResponse:
        return AgentSpecificationResponse(
            name=definition.name,
            purpose=definition.purpose,
            system_instructions=definition.system_instructions,
            capabilities=list(definition.capabilities),
            skills=list(definition.skills),
            tools=list(definition.tools),
            allowed_actions=list(definition.allowed_actions),
            input_schema=definition.input_schema,
            output_schema=definition.output_schema,
            permissions=list(definition.permissions),
            dependencies=list(definition.dependencies),
            version=definition.version,
        )

    def _definition_from_agent(self, agent: Agent) -> AgentDefinition:
        return AgentDefinition(
            name=agent.name,
            purpose=agent.purpose,
            system_instructions=agent.system_instructions,
            capabilities=tuple(agent.capabilities),
            skills=tuple(agent.skills),
            tools=tuple(agent.tools),
            integrations=tuple(agent.integrations or ()),
            allowed_actions=tuple(agent.allowed_actions),
            input_schema=agent.input_schema,
            output_schema=agent.output_schema,
            permissions=tuple(Permission(value) for value in agent.permissions),
            dependencies=tuple(agent.dependencies),
            status=agent.status,
            version=agent.version,
        )
