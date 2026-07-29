"""Registry and contract for specialized executive agents."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Protocol


class ExecutiveAgent(Protocol):
    """Minimal department-facing contract coordinated by the Digital CEO."""

    name: str

    def get_status(self) -> str: ...
    def get_kpis(self) -> Mapping[str, Any]: ...
    def get_priorities(self) -> list[str] | tuple[str, ...]: ...
    def get_recommendations(self) -> list[str] | tuple[str, ...]: ...
    def execute(self, action: Any) -> Any: ...


class ExecutiveRegistry:
    """Own executive instances for a single CEO composition root."""

    def __init__(self) -> None:
        self._executives: dict[str, ExecutiveAgent] = {}

    def register(self, executive: ExecutiveAgent) -> None:
        """Register an executive instance under its stable department name."""

        name = self._name_of(executive)
        if name in self._executives:
            raise ValueError(f"Executive already registered: {name}")
        self._validate_contract(executive)
        self._executives[name] = executive

    def unregister(self, name: str) -> ExecutiveAgent | None:
        return self._executives.pop(self._normalize_name(name), None)

    def get_executive(self, name: str) -> ExecutiveAgent | None:
        return self._executives.get(self._normalize_name(name))

    def list_executives(self) -> tuple[str, ...]:
        return tuple(sorted(self._executives))

    def snapshot(self) -> Mapping[str, ExecutiveAgent]:
        return MappingProxyType(dict(self._executives))

    @staticmethod
    def _validate_contract(executive: ExecutiveAgent) -> None:
        required_methods = (
            "get_status", "get_kpis", "get_priorities", "get_recommendations", "execute",
        )
        if any(not callable(getattr(executive, method, None)) for method in required_methods):
            raise TypeError("executive must implement the executive department interface")

    @staticmethod
    def _name_of(executive: ExecutiveAgent) -> str:
        return ExecutiveRegistry._normalize_name(getattr(executive, "name", None))

    @staticmethod
    def _normalize_name(name: object) -> str:
        if not isinstance(name, str) or not (normalized := name.strip()):
            raise ValueError("executive name is required")
        return normalized.casefold()
