"""Agent class registry for the GoalOS runtime."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, TypeAlias

from app.agents.base_agent import BaseAgent

AgentClass: TypeAlias = type[BaseAgent]


class AgentRegistry:
    """Own the available agent classes for one runtime composition root."""

    def __init__(self) -> None:
        """Create an empty, non-global registry."""

        self._agents: dict[str, AgentClass] = {}

    def register(self, agent_class: AgentClass) -> None:
        """Register an agent class under its stable runtime name.

        Raises:
            TypeError: If ``agent_class`` is not a BaseAgent subclass.
            ValueError: If its name is missing or already registered.
        """

        if not isinstance(agent_class, type) or not issubclass(agent_class, BaseAgent):
            raise TypeError("agent_class must inherit BaseAgent")

        name = self._agent_name(agent_class)
        if name in self._agents:
            raise ValueError(f"Agent already registered: {name}")
        self._agents[name] = agent_class

    def unregister(self, name: str) -> AgentClass | None:
        """Remove and return an agent class, if registered."""

        return self._agents.pop(self._normalize_name(name), None)

    def list_agents(self) -> tuple[str, ...]:
        """Return registered agent names in deterministic order."""

        return tuple(sorted(self._agents))

    def get_agent(self, name: str) -> AgentClass | None:
        """Return the agent class registered under ``name``."""

        return self._agents.get(self._normalize_name(name))

    def snapshot(self) -> Mapping[str, AgentClass]:
        """Return an immutable view of registered agent classes."""

        return MappingProxyType(dict(self._agents))

    @staticmethod
    def _agent_name(agent_class: AgentClass) -> str:
        """Read and validate a class-level runtime name."""

        name = getattr(agent_class, "agent_name", agent_class.__name__)
        return AgentRegistry._normalize_name(name)

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a registry key."""

        if not isinstance(name, str) or not (normalized_name := name.strip()):
            raise ValueError("agent name is required")
        return normalized_name
