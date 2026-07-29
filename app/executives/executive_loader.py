"""Dynamic discovery and lifecycle management for GoalOS executives."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from types import MappingProxyType, ModuleType
from typing import Mapping

from app.executives.base_executive import BaseExecutive
from app.executives.executive_registry import ExecutiveRegistry


class ExecutiveLoader:
    """Discover, register, and initialize executives for one runtime instance."""

    def __init__(self, registry: ExecutiveRegistry | None = None) -> None:
        """Create a loader with an injected registry when desired."""

        self.registry = registry or ExecutiveRegistry()
        self._loaded_executives: dict[str, BaseExecutive] = {}

    @property
    def loaded_executives(self) -> Mapping[str, BaseExecutive]:
        """Expose an immutable snapshot of initialized executives."""

        return MappingProxyType(dict(self._loaded_executives))

    def discover(self, package: ModuleType | str = "app.executives") -> tuple[str, ...]:
        """Import a package tree and register its concrete executive subclasses."""

        package_module = (
            importlib.import_module(package) if isinstance(package, str) else package
        )
        modules = [package_module]
        if hasattr(package_module, "__path__"):
            modules.extend(
                importlib.import_module(module.name)
                for module in pkgutil.walk_packages(
                    package_module.__path__, f"{package_module.__name__}."
                )
                if not module.name.rsplit(".", 1)[-1].startswith("_")
            )

        discovered: list[str] = []
        for module in modules:
            for _, executive_class in inspect.getmembers(module, inspect.isclass):
                if (
                    executive_class is BaseExecutive
                    or not issubclass(executive_class, BaseExecutive)
                    or inspect.isabstract(executive_class)
                    or executive_class.__module__ != module.__name__
                ):
                    continue
                executive = executive_class()
                if self.registry.exists(executive.name):
                    continue
                self.registry.register(executive)
                discovered.append(executive.name)
        return tuple(sorted(discovered, key=str.casefold))

    def load_executive(self, name: str) -> BaseExecutive:
        """Initialize and return one registered executive.

        Raises:
            LookupError: If no executive is registered under ``name``.
        """

        executive = self.registry.get(name)
        if executive is None:
            raise LookupError(f"Executive is not registered: {name}")
        executive.initialize()
        self._loaded_executives[self._normalize_name(executive.name)] = executive
        return executive

    def load_all(self) -> Mapping[str, BaseExecutive]:
        """Initialize and return every registered executive."""

        for name in self.registry.list():
            self.load_executive(name)
        return self.loaded_executives

    def reload(
        self, name: str | None = None
    ) -> BaseExecutive | Mapping[str, BaseExecutive]:
        """Restart one executive, or all registered executives when ``name`` is omitted."""

        if name is not None:
            executive = self.registry.get(name)
            if executive is None:
                raise LookupError(f"Executive is not registered: {name}")
            executive.shutdown()
            self._loaded_executives.pop(self._normalize_name(executive.name), None)
            return self.load_executive(executive.name)

        for executive in tuple(self._loaded_executives.values()):
            executive.shutdown()
        self._loaded_executives.clear()
        return self.load_all()

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a loaded-executive key using registry semantics."""

        return name.strip().casefold()
