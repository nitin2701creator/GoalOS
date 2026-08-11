"""Discovery and lifecycle management for GoalOS skills."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType
from typing import Mapping, TypeAlias

from app.skills.base_skill import BaseSkill
from app.skills.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

SkillClass: TypeAlias = type[BaseSkill]


class SkillLoader:
    """Discover, instantiate, and initialize skills for one runtime instance."""

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        """Create a loader with an injected registry when desired."""

        self.registry = registry or SkillRegistry()
        self._discovered_skill_classes: dict[str, SkillClass] = {}

    def discover_skills(self, package: ModuleType | str = "app.skills") -> tuple[str, ...]:
        """Discover concrete skill classes contained by a package.

        Discovery is idempotent and does not instantiate classes; construction
        and lifecycle startup are performed by :meth:`load_skills`.
        """

        package_module = importlib.import_module(package) if isinstance(package, str) else package
        modules = [package_module]
        if hasattr(package_module, "__path__"):
            modules.extend(
                importlib.import_module(module.name)
                for module in pkgutil.walk_packages(package_module.__path__, f"{package_module.__name__}.")
                if not module.name.rsplit(".", 1)[-1].startswith("_")
            )

        for module in modules:
            for _, skill_class in inspect.getmembers(module, inspect.isclass):
                # ``inspect.isclass`` also reports PEP 585 aliases such as
                # ``SkillClass: TypeAlias = type[BaseSkill]`` (a GenericAlias
                # whose ``__module__`` is ``builtins``). Require a real class
                # defined in the walked module before subclass checks.
                if (
                    not isinstance(skill_class, type)
                    or skill_class.__module__ != module.__name__
                ):
                    continue
                if (
                    skill_class is BaseSkill
                    or not issubclass(skill_class, BaseSkill)
                    or inspect.isabstract(skill_class)
                ):
                    continue
                self._discovered_skill_classes.setdefault(skill_class.__name__, skill_class)

        discovered = tuple(sorted(self._discovered_skill_classes))
        logger.debug("Discovered GoalOS skills: %s", discovered)
        return discovered

    def load_skills(self) -> Mapping[str, BaseSkill]:
        """Instantiate and initialize all discovered and registered skills."""

        for skill_class in self._discovered_skill_classes.values():
            skill = skill_class()
            if self.registry.get_skill(skill.name) is None:
                self.registry.register(skill)

        for name, skill in self.registry.snapshot().items():
            skill.initialize()
            logger.info("Initialized GoalOS skill '%s'", name)

        return self.registry.snapshot()

    def shutdown_skills(self) -> None:
        """Shut down every registered skill in the runtime instance."""

        for name, skill in self.registry.snapshot().items():
            skill.shutdown()
            logger.info("Shut down GoalOS skill '%s'", name)
