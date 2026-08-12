"""GoalOS capability engine: registry, resolver, matcher, and executor.

The engine is the persistent, authoritative registry of what GoalOS can
resolve and execute:

- ``ensure_seeded``/``register``: idempotently persist the built-in
  capability catalog into the ``capabilities`` table.
- ``resolve``/``resolve_many``/``match``/``resolve_for_goal``: turn a
  capability name or a plain-language goal into structured, honest
  resolution outcomes (exists, enabled, available, permissions).
- ``check_available``/``check_permissions``/``get_provider``: availability
  and authorization checks against the existing connector registry and
  permission model.
- ``execute``: run one capability through the EXISTING runtime — the
  integration connectors for ``integration`` capabilities and the existing
  skill implementations for ``skill``/``native`` capabilities. An
  unconfigured capability returns ``INTEGRATION_NOT_CONFIGURED``; an
  unauthorized one returns ``PERMISSION_DENIED``; never a fabricated
  success.

Goal-level resolution reuses the existing deterministic keyword catalog
and may be refined by the configured LLM provider (only names already
registered are ever accepted — free-form LLM output is never trusted).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from app.agents.capabilities import CAPABILITY_CATALOG, capability_spec
from app.agents.capability_definitions import (
    BUILTIN_CAPABILITIES,
    CapabilityDefinition,
    CapabilityProviderType,
)
from app.agents.factory.skill_implementations import SKILL_IMPLEMENTATIONS
from app.agents.permissions import Permission
from app.ai.llm_gateway import LLMGateway
from app.db.models.capability import Capability, CapabilityStatus
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    CapabilityUnavailableError,
    PermissionDeniedError,
)
from app.integrations.factory import integration_for_capability
from app.llm.base_provider import BaseProvider, provider_configured
from app.repositories.capability_repository import CapabilityRepository
from app.schemas.capability import (
    CapabilityCreateRequest,
    CapabilityExecuteResponse,
    CapabilityGoalResolution,
    CapabilityMatchResult,
    CapabilityResolveResponse,
    CapabilityResponse,
)


def _parse_name_list(text: str) -> list[str]:
    """Parse a JSON array (or fenced array) of capability names.

    Defensive: tolerates code fences, prose around the array, and
    single/double quotes. Returns an empty list when nothing parses.
    """
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    match = re.search(r"\[(.*?)\]", stripped, re.DOTALL)
    if match is None:
        return []
    inner = match.group(1)
    quoted = re.findall(r"\"([^\"]+)\"|'([^']+)'", inner)
    if quoted:
        return [first or second for first, second in quoted]
    return [part.strip() for part in inner.split(",") if part.strip()]


class CapabilityService:
    """Persistent capability registry, resolver, and executor."""

    def __init__(
        self,
        repository: CapabilityRepository,
        integration_registry: ConnectorRegistry | None = None,
        llm_provider: BaseProvider | None = None,
    ) -> None:
        self.repository = repository
        self.integration_registry = integration_registry
        self.llm_provider = llm_provider

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def ensure_seeded(self) -> None:
        """Idempotently persist the built-in capability catalog."""
        for definition in BUILTIN_CAPABILITIES.values():
            if self.repository.get_by_name(definition.name) is None:
                self.repository.create(self._definition_values(definition))

    def register(self, request: CapabilityCreateRequest) -> CapabilityResponse:
        """Register a capability; duplicate registration is idempotent."""
        existing = self.repository.get_by_name(request.name)
        if existing is not None:
            return self._to_response(existing)
        capability = self.repository.create(request.model_dump(mode="json"))
        return self._to_response(capability)

    def get(self, capability_id: Any) -> CapabilityResponse | None:
        self.ensure_seeded()
        capability = self.repository.get(capability_id)
        if capability is None:
            return None
        return self._to_response(capability)

    def get_by_name(self, name: str) -> CapabilityResponse | None:
        self.ensure_seeded()
        capability = self.repository.get_by_name(name)
        if capability is None:
            return None
        return self._to_response(capability)

    def list(self) -> list[CapabilityResponse]:
        self.ensure_seeded()
        return [self._to_response(capability) for capability in self.repository.list()]

    def list_with_status(self) -> list[dict[str, Any]]:
        """List capabilities with their honest availability status."""
        self.ensure_seeded()
        results: list[dict[str, Any]] = []
        for capability in self.repository.list():
            available, reason = self.check_available(capability)
            response = self._to_response(capability).model_dump(mode="json")
            response["available"] = available
            response["availability_reason"] = reason
            results.append(response)
        return results

    def enable(self, name: str) -> CapabilityResponse | None:
        self.ensure_seeded()
        capability = self.repository.get_by_name(name)
        if capability is None:
            return None
        return self._to_response(
            self.repository.update(
                capability,
                {"enabled": True, "status": CapabilityStatus.ACTIVE},
            )
        )

    def disable(self, name: str) -> CapabilityResponse | None:
        self.ensure_seeded()
        capability = self.repository.get_by_name(name)
        if capability is None:
            return None
        return self._to_response(
            self.repository.update(
                capability,
                {"enabled": False, "status": CapabilityStatus.DISABLED},
            )
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(
        self,
        name: str,
        permissions: set[Permission] | None = None,
    ) -> CapabilityResolveResponse:
        """Resolve one capability honestly (exists/enabled/available)."""
        self.ensure_seeded()
        capability = self.repository.get_by_name(name)
        if capability is None:
            return CapabilityResolveResponse(
                name=name,
                exists=False,
                enabled=False,
                available=False,
                reason="capability is not registered",
            )
        available, reason = self.check_available(capability)
        sufficient = None
        missing: list[str] = []
        if permissions is not None:
            sufficient, missing = self.check_permissions(capability, permissions)
        return CapabilityResolveResponse(
            name=capability.name,
            exists=True,
            enabled=capability.enabled,
            available=available,
            reason=reason,
            required_permissions=[
                Permission(value) for value in capability.required_permissions
            ],
            permissions_sufficient=sufficient,
            missing_permissions=missing,
            provider_type=capability.provider_type,
            provider=capability.provider,
            implementation=capability.implementation,
            execution_capability=capability.execution_capability,
            description=capability.description,
            category=capability.category,
            requires_approval=capability.requires_approval,
        )

    def resolve_many(
        self,
        names: list[str],
        permissions: set[Permission] | None = None,
    ) -> list[CapabilityResolveResponse]:
        """Resolve several capabilities at once."""
        return [self.resolve(name, permissions=permissions) for name in names]

    def match(self, requirement: str) -> list[CapabilityMatchResult]:
        """Match a goal against the registry, deterministically + LLM-refined.

        Deterministic keyword matching runs first over every registered
        capability's keywords. When an LLM provider is configured, it may
        add capabilities — but only names already registered are accepted.
        """
        self.ensure_seeded()
        text = requirement.casefold()
        matched: list[CapabilityMatchResult] = []
        for capability in self.repository.list():
            keywords = list(capability.keywords or ())
            if keywords and any(keyword in text for keyword in keywords):
                matched.append(self._match_result(capability, "keyword"))
        return self._llm_refine(requirement, matched)

    def resolve_for_goal(self, requirement: str) -> CapabilityGoalResolution:
        """Resolve a goal into matched + execution capability sets.

        ``execution_capabilities`` are the deduplicated catalog
        capabilities (in deterministic catalog order) the agent factory
        uses to reuse or create the executing agent.
        """
        matched = self.match(requirement)
        names = [result.name for result in matched]
        return CapabilityGoalResolution(
            requirement=requirement,
            capabilities=names,
            execution_capabilities=list(self._execution_capabilities(names)),
        )

    # ------------------------------------------------------------------
    # Availability and permissions
    # ------------------------------------------------------------------
    def check_available(self, capability: Capability) -> tuple[bool, str]:
        """Return (available, reason) for a persisted capability.

        Unavailable is always honest: missing provider/implementation or
        unconfigured integration reports INTEGRATION_NOT_CONFIGURED.
        """
        if not capability.enabled or capability.status is not CapabilityStatus.ACTIVE:
            return False, "capability is disabled"
        if capability.provider_type == CapabilityProviderType.INTEGRATION.value:
            return self._integration_available(capability)
        if capability.provider_type == CapabilityProviderType.SKILL.value:
            return self._skill_available(capability)
        # native provider
        if capability.implementation is None:
            return (
                False,
                "INTEGRATION_NOT_CONFIGURED: no implementation configured for this capability",
            )
        if capability.implementation in SKILL_IMPLEMENTATIONS:
            return True, "available"
        return (
            False,
            f"INTEGRATION_NOT_CONFIGURED: implementation "
            f"'{capability.implementation}' is not available",
        )

    def _integration_available(self, capability: Capability) -> tuple[bool, str]:
        if capability.implementation is None:
            return (
                False,
                f"INTEGRATION_NOT_CONFIGURED: capability {capability.name} "
                "has no implementation configured",
            )
        registry = self.integration_registry
        if registry is None:
            return (
                False,
                "INTEGRATION_NOT_CONFIGURED: no integration registry is configured",
            )
        connector = registry.get_connector(capability.provider)
        if connector is None:
            return (
                False,
                f"INTEGRATION_NOT_CONFIGURED: provider '{capability.provider}' "
                "is not registered",
            )
        available, reason = connector.capability_available(capability.implementation)
        if not available:
            return False, f"INTEGRATION_NOT_CONFIGURED: {reason}"
        return True, "available"

    def _skill_available(self, capability: Capability) -> tuple[bool, str]:
        if capability.implementation not in SKILL_IMPLEMENTATIONS:
            return (
                False,
                f"INTEGRATION_NOT_CONFIGURED: skill implementation "
                f"'{capability.implementation}' is not available",
            )
        dependencies = self._integration_dependencies(capability)
        if not dependencies:
            return True, "available"
        registry = self.integration_registry
        if registry is None:
            return (
                False,
                "INTEGRATION_NOT_CONFIGURED: no integration registry is configured",
            )
        for capability_name in dependencies:
            connector_name = integration_for_capability(capability_name)
            connector = registry.get_connector(connector_name)
            if connector is None:
                return (
                    False,
                    f"INTEGRATION_NOT_CONFIGURED: required integration "
                    f"'{connector_name}' is not registered",
                )
            available, reason = connector.capability_available(capability_name)
            if not available:
                return False, f"INTEGRATION_NOT_CONFIGURED: {reason}"
        return True, "available"

    def _integration_dependencies(self, capability: Capability) -> tuple[str, ...]:
        """Integration capabilities the mapped catalog capability needs."""
        if not capability.execution_capability:
            return ()
        try:
            return capability_spec(capability.execution_capability).integration_capabilities
        except ValueError:
            return ()

    def check_permissions(
        self,
        capability: Capability,
        permissions: set[Permission],
    ) -> tuple[bool, list[str]]:
        """Return (sufficient, missing) for the granted permission set."""
        required = {Permission(value) for value in capability.required_permissions}
        missing = sorted(
            required - permissions,
            key=lambda permission: permission.value,
        )
        return (not missing), [permission.value for permission in missing]

    def get_provider(self, name: str) -> dict[str, Any]:
        """Return provider information for a capability, if registered."""
        capability = self.repository.get_by_name(name)
        if capability is None:
            return {
                "capability": name,
                "provider": None,
                "registered": False,
                "reason": "capability is not registered",
            }
        if capability.provider_type == CapabilityProviderType.INTEGRATION.value:
            connector = (
                self.integration_registry.get_connector(capability.provider)
                if self.integration_registry is not None
                else None
            )
            return {
                "capability": name,
                "provider": capability.provider,
                "provider_type": capability.provider_type,
                "registered": connector is not None,
                "connector": connector.name if connector is not None else None,
                "implementation": capability.implementation,
            }
        return {
            "capability": name,
            "provider": capability.provider,
            "provider_type": capability.provider_type,
            "registered": capability.implementation in SKILL_IMPLEMENTATIONS,
            "implementation": capability.implementation,
        }

    # ------------------------------------------------------------------
    # Execution (through the existing runtime)
    # ------------------------------------------------------------------
    def execute(
        self,
        name: str,
        params: dict[str, Any],
        permissions: set[Permission] | list[Permission],
    ) -> CapabilityExecuteResponse:
        """Execute one capability through the existing runtime.

        The capability is resolved, availability-checked, and
        permission-checked before dispatch. Unavailable capabilities
        return INTEGRATION_NOT_CONFIGURED; insufficient permissions
        return PERMISSION_DENIED. Integration capabilities dispatch to the
        existing connectors; skill/native capabilities run the existing
        skill implementations.
        """
        self.ensure_seeded()
        capability = self.repository.get_by_name(name)
        if capability is None:
            return CapabilityExecuteResponse(
                capability=name,
                status="NOT_FOUND",
                error="capability is not registered",
            )
        if not capability.enabled or capability.status is not CapabilityStatus.ACTIVE:
            return CapabilityExecuteResponse(
                capability=name,
                status="DISABLED",
                provider=capability.provider,
                error="capability is disabled",
            )
        available, reason = self.check_available(capability)
        if not available:
            return CapabilityExecuteResponse(
                capability=name,
                status="INTEGRATION_NOT_CONFIGURED",
                provider=capability.provider,
                error=reason,
            )
        granted = set(permissions)
        sufficient, missing = self.check_permissions(capability, granted)
        if not sufficient:
            return CapabilityExecuteResponse(
                capability=name,
                status="PERMISSION_DENIED",
                provider=capability.provider,
                error="missing required permissions: " + ", ".join(missing),
            )
        try:
            if capability.provider_type == CapabilityProviderType.INTEGRATION.value:
                result = self._run_connector(capability, params, granted)
            else:
                result = self._run_skill(capability, params, granted)
        except PermissionDeniedError as exc:
            return CapabilityExecuteResponse(
                capability=name,
                status="PERMISSION_DENIED",
                provider=capability.provider,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 - execution must return structured results
            return CapabilityExecuteResponse(
                capability=name,
                status="ERROR",
                provider=capability.provider,
                error=f"{type(exc).__name__}: {exc}",
            )
        if isinstance(result, dict) and result.get("error"):
            return CapabilityExecuteResponse(
                capability=name,
                status="ERROR",
                provider=capability.provider,
                error=str(result["error"]),
            )
        return CapabilityExecuteResponse(
            capability=name,
            status="OK",
            provider=capability.provider,
            result=result if isinstance(result, dict) else {"result": result},
        )

    def _run_connector(
        self,
        capability: Capability,
        params: dict[str, Any],
        permissions: set[Permission],
    ) -> dict[str, Any]:
        assert self.integration_registry is not None
        assert capability.implementation is not None
        connector = self.integration_registry.get_connector(capability.provider)
        if connector is None:
            raise CapabilityUnavailableError(
                f"provider '{capability.provider}' is not registered"
            )
        return connector.execute(
            capability.implementation,
            params,
            permissions=permissions,
        )

    def _run_skill(
        self,
        capability: Capability,
        params: dict[str, Any],
        permissions: set[Permission],
    ) -> dict[str, Any]:
        skill_class = SKILL_IMPLEMENTATIONS.get(capability.implementation or "")
        if skill_class is None:
            raise CapabilityUnavailableError(
                f"no skill implementation for {capability.implementation}"
            )
        context = dict(params)
        context["__integrations__"] = self.integration_registry
        context["__permissions__"] = frozenset(permissions)
        return asyncio.run(skill_class().execute(context))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _llm_refine(
        self,
        requirement: str,
        matched: list[CapabilityMatchResult],
    ) -> list[CapabilityMatchResult]:
        provider = self.llm_provider
        if not provider_configured(provider):
            return matched
        known = [capability.name for capability in self.repository.list()]
        prompt = (
            "You are the GoalOS capability resolver. Given a business goal and "
            "the available capability names, return ONLY a JSON array of the "
            "capability names required to accomplish the goal.\n"
            f"Available capabilities: {', '.join(known)}\n"
            f"Goal: {requirement}\n"
        )
        try:
            payload = provider.request(prompt)
            names = _parse_name_list(LLMGateway._response_text(payload))
        except Exception:  # noqa: BLE001 - LLM refinement must never break resolution
            return matched
        existing = {result.name for result in matched}
        for name in names:
            if name in existing:
                continue
            capability = self.repository.get_by_name(name)
            if capability is None:
                continue  # never trust unregistered names
            matched.append(self._match_result(capability, "llm"))
        return matched

    def _execution_capabilities(self, names: list[str]) -> tuple[str, ...]:
        """Dedupe matched capabilities into catalog-ordered execution set."""
        mapped = set()
        for name in names:
            capability = self.repository.get_by_name(name)
            if capability is not None and capability.execution_capability:
                mapped.add(capability.execution_capability)
        return tuple(
            catalog_name
            for catalog_name in CAPABILITY_CATALOG
            if catalog_name in mapped
        )

    @staticmethod
    def _match_result(
        capability: Capability,
        source: str,
    ) -> CapabilityMatchResult:
        return CapabilityMatchResult(
            name=capability.name,
            description=capability.description,
            category=capability.category,
            source=source,  # type: ignore[arg-type]
        )

    @staticmethod
    def _definition_values(definition: CapabilityDefinition) -> dict[str, Any]:
        return {
            "name": definition.name,
            "description": definition.description,
            "category": definition.category,
            "version": definition.version,
            "required_permissions": [
                permission.value for permission in definition.required_permissions
            ],
            "input_schema": definition.input_schema,
            "output_schema": definition.output_schema,
            "provider_type": definition.provider_type.value,
            "provider": definition.provider,
            "implementation": definition.implementation,
            "execution_capability": definition.execution_capability,
            "keywords": list(definition.keywords),
            "enabled": definition.enabled,
            "requires_approval": definition.requires_approval,
        }

    def _to_response(self, capability: Capability) -> CapabilityResponse:
        return CapabilityResponse(
            id=capability.id,
            name=capability.name,
            description=capability.description,
            category=capability.category,
            version=capability.version,
            status=capability.status,
            required_permissions=[
                Permission(value) for value in capability.required_permissions
            ],
            input_schema=capability.input_schema,
            output_schema=capability.output_schema,
            provider_type=CapabilityProviderType(capability.provider_type),
            provider=capability.provider,
            implementation=capability.implementation,
            execution_capability=capability.execution_capability,
            keywords=list(capability.keywords),
            enabled=capability.enabled,
            requires_approval=capability.requires_approval,
            created_at=capability.created_at,
            updated_at=capability.updated_at,
        )
