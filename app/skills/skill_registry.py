"""Instance registry for GoalOS skills."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Mapping

from app.skills.base_skill import BaseSkill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Own skill instances for a single runtime composition root."""

    def __init__(self) -> None:
        """Create an empty registry without process-wide mutable state."""

        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a skill under its stable name.

        Raises:
            TypeError: If the supplied object is not a skill.
            ValueError: If the skill name is already registered.
        """

        if not isinstance(skill, BaseSkill):
            raise TypeError("skill must inherit BaseSkill")

        name = self._normalize_name(skill.name)
        if name in self._skills:
            raise ValueError(f"Skill already registered: {name}")
        self._skills[name] = skill
        logger.debug("Registered GoalOS skill '%s'", name)

    def unregister(self, name: str) -> BaseSkill | None:
        """Remove and return a skill, if it is registered."""

        skill = self._skills.pop(self._normalize_name(name), None)
        if skill is not None:
            logger.debug("Unregistered GoalOS skill '%s'", skill.name)
        return skill

    def list_skills(self) -> tuple[str, ...]:
        """Return registered skill names in deterministic order."""

        return tuple(sorted(self._skills))

    def get_skill(self, name: str) -> BaseSkill | None:
        """Return the skill registered under ``name``, if present."""

        return self._skills.get(self._normalize_name(name))

    def snapshot(self) -> Mapping[str, BaseSkill]:
        """Return an immutable snapshot of the registered skills."""

        return MappingProxyType(dict(self._skills))

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a skill registry key."""

        if not isinstance(name, str) or not (normalized_name := name.strip()):
            raise ValueError("skill name is required")
        return normalized_name
