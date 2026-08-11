"""Dynamically generated runtime agents for the GoalOS agent factory.

An :class:`AgentDefinition` is pure structured data. To make it
executable through the existing agent runtime, the factory generates a
:class:`DynamicAgent` subclass whose name matches the definition and
whose skills/tools load from the definition's attachments. Execution uses
the existing :class:`BaseAgent` contract (plan/execute/report with
:class:`AgentContext`/:class:`AgentResult`) — no second execution engine.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.agents.agent_definitions import AgentDefinition
from app.agents.base_agent import AgentContext, AgentResult, BaseAgent
from app.skills.base_skill import BaseSkill


class DynamicAgent(BaseAgent):
    """Runtime agent generated from a structured :class:`AgentDefinition`.

    Instances are created by the agent factory with the definition and the
    skill implementations attached to it. Subclasses generated for each
    definition set ``agent_name`` so they register cleanly in the
    :class:`AgentRegistry`.
    """

    def __init__(
        self,
        definition: AgentDefinition,
        skill_implementations: Mapping[str, BaseSkill] | None = None,
        integrations: Any | None = None,
    ) -> None:
        """Initialize the dynamic agent.

        Args:
            definition: The structured definition driving this agent.
            skill_implementations: Available implementations keyed by skill
                name; only skills in the definition are attached.
            integrations: Optional integration registry made available to
                skills that declare required integrations.
        """
        super().__init__(name=definition.name, description=definition.purpose)
        self._definition = definition
        self._skill_implementations = dict(skill_implementations or {})
        self._integrations = integrations

    @property
    def integrations(self) -> Any | None:
        """Return the integration registry attached to this agent, if any."""
        return self._integrations

    @property
    def definition(self) -> AgentDefinition:
        """Return the structured definition driving this agent."""
        return self._definition

    def load_skills(self) -> Mapping[str, BaseSkill]:
        """Attach only the implementations named by the definition."""
        return {
            name: implementation
            for name, implementation in self._skill_implementations.items()
            if name in self._definition.skills
        }

    def load_tools(self) -> Mapping[str, Any]:
        """Dynamic agents exercise capability through their skills."""
        return {}

    async def plan(self, context: AgentContext) -> AgentResult:
        """Plan work using the attached skills and declared permissions."""
        goal = self._require_text(context.goal, "goal")
        return self._result(
            summary=f"Planned work for {self.name}: {goal}",
            actions=tuple(
                f"Execute skill: {skill_name}" for skill_name in self._definition.skills
            ),
            metadata={
                "phase": "plan",
                "skill_count": len(self._definition.skills),
                "permissions": [permission.value for permission in self._definition.permissions],
            },
        )

    async def execute(self, context: AgentContext) -> AgentResult:
        """Execute every attached skill over the context input.

        The input is read from ``context.metadata["input"]`` and must match
        the definition's ``input_schema``. Each skill's output is collected
        under its name in ``metadata["skill_results"]``.
        """
        goal = self._require_text(context.goal, "goal")
        inputs = dict(context.metadata.get("input") or {})
        if self._integrations is not None:
            inputs["__integrations__"] = self._integrations
            inputs["__permissions__"] = frozenset(self._definition.permissions)
        skill_results: dict[str, Any] = {}
        errors: list[str] = []

        for skill_name in self._definition.skills:
            skill = self.skills.get(skill_name)
            if skill is None:
                errors.append(f"skill {skill_name} has no implementation")
                skill_results[skill_name] = {"error": f"no implementation for {skill_name}"}
                continue
            try:
                skill_results[skill_name] = await skill.execute(inputs)
            except Exception as exc:  # noqa: BLE001 - a failing skill must not crash the agent
                errors.append(f"skill {skill_name} failed: {exc}")
                skill_results[skill_name] = {"error": str(exc)}

        return self._result(
            summary=(
                f"Executed {self.name}: {len(skill_results)} skill(s), "
                f"{len(errors)} error(s)."
            ),
            metadata={
                "phase": "execute",
                "goal": goal,
                "skill_results": skill_results,
                "errors": tuple(errors),
            },
        )

    async def report(self, context: AgentContext) -> AgentResult:
        """Report the agent's scope, permissions, and attached skills."""
        goal = self._require_text(context.goal, "goal")
        return self._result(
            summary=f"Prepared report for {self.name}: {goal}",
            metadata={
                "phase": "report",
                "skills": tuple(self._definition.skills),
                "permissions": [permission.value for permission in self._definition.permissions],
            },
        )


def build_dynamic_agent_class(definition: AgentDefinition) -> type[DynamicAgent]:
    """Generate a runtime agent class for ``definition``.

    The generated class sets ``agent_name`` to the definition's name so the
    existing :class:`AgentRegistry` keys it exactly like a hand-written
    agent. The class is placed in this module so automatic discovery never
    imports it into a runtime composition root.

    Returns:
        A concrete :class:`DynamicAgent` subclass.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", definition.name).strip("_") or "agent"
    class_name = "Dynamic" + "".join(part.capitalize() for part in slug.split("_"))
    namespace: dict[str, Any] = {
        "agent_name": definition.name,
        "__module__": __name__,
    }
    return type(class_name, (DynamicAgent,), namespace)
