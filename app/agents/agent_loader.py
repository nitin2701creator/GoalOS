"""Automatic agent discovery and lifecycle management."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType
from typing import Mapping

from app.agents.agent_registry import AgentRegistry
from app.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AgentLoader:
    """Discover, instantiate, and initialize agents for a runtime instance."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        """Create a loader with an injected registry when desired."""

        self.registry = registry or AgentRegistry()
        self._loaded_agents: dict[str, BaseAgent] = {}

    @property
    def loaded_agents(self) -> Mapping[str, BaseAgent]:
        """Expose an immutable snapshot of initialized agent instances."""

        from types import MappingProxyType

        return MappingProxyType(dict(self._loaded_agents))

    def discover_agents(self, package: ModuleType | str = "app.agents") -> tuple[str, ...]:
        """Import agent modules and register concrete BaseAgent subclasses."""

        package_module = importlib.import_module(package) if isinstance(package, str) else package
        modules = [package_module]
        if hasattr(package_module, "__path__"):
            modules.extend(
                importlib.import_module(module.name)
                for module in pkgutil.iter_modules(package_module.__path__, f"{package_module.__name__}.")
                if not module.name.rsplit(".", 1)[-1].startswith("_")
            )

        discovered: list[str] = []
        for module in modules:
            for _, agent_class in inspect.getmembers(module, inspect.isclass):
                if agent_class is BaseAgent or not issubclass(agent_class, BaseAgent):
                    continue
                if agent_class.__module__ != module.__name__:
                    continue
                try:
                    self.registry.register(agent_class)
                    discovered.append(self._registry_name(agent_class))
                except ValueError:
                    # Discovery is safely repeatable for an already-populated registry.
                    continue
        return tuple(sorted(discovered))

    def load_agents(self) -> Mapping[str, BaseAgent]:
        """Instantiate and initialize every registered agent class."""

        for name, agent_class in self.registry.snapshot().items():
            agent = self._loaded_agents.get(name)
            if agent is None:
                agent = agent_class()
                self._loaded_agents[name] = agent
            agent.initialize()
            logger.info("Initialized GoalOS agent '%s'", name)
        return self.loaded_agents

    def get_agent(self, name: str) -> BaseAgent | None:
        """Return a loaded agent instance by runtime name."""

        return self._loaded_agents.get(name.strip())

    @staticmethod
    def _registry_name(agent_class: type[BaseAgent]) -> str:
        """Resolve the registry key without instantiating an agent."""

        return str(getattr(agent_class, "agent_name", agent_class.__name__)).strip()
