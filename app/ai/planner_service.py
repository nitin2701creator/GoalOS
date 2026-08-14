"""Goal planning service for GoalOS.

The service turns a plain-language goal into an ordered :class:`GoalPlan`
using the existing capability engine and (when configured) the existing
LLM provider:

- with a configured LLM provider, the goal is decomposed into an ordered
  plan of capability steps (:class:`GoalPlanner`), validated against the
  registry and filtered by explicit user restrictions;
- without a provider (or when the LLM plan is unusable), the plan falls
  back to the deterministic capability resolver — the exact same
  capability set and order the workflow path uses today, so unrestricted
  and no-LLM behavior is preserved.

The produced plan is what the execution runtime accepts for sequential,
result-chained execution; nothing here bypasses the existing capability,
permission, or execution architecture.
"""

from __future__ import annotations

import logging
from typing import Any

from app.ai.planner import GoalPlanner
from app.llm.base_provider import BaseProvider, provider_configured
from app.schemas.plan import GoalPlan, PlanStep
from app.services.capability_service import CapabilityService

logger = logging.getLogger(__name__)


class PlannerService:
    """Orchestrate goal planning with LLM-first and deterministic fallback.

    Args:
        capability_service: The persistent capability engine used for
            catalog listing, restriction parsing, and deterministic
            resolution.
        llm_provider: The configured GoalOS LLM provider (optional).
        planner: Optional planner override for tests.
    """

    def __init__(
        self,
        capability_service: CapabilityService,
        llm_provider: BaseProvider | None = None,
        planner: GoalPlanner | None = None,
    ) -> None:
        self.capability_service = capability_service
        self.llm_provider = llm_provider
        self.planner = planner or GoalPlanner(capability_service, llm_provider)

    def plan_for_goal(self, requirement: str) -> GoalPlan:
        """Return an ordered capability plan for ``requirement``.

        The LLM plan is used only when a configured provider produces a
        valid, restriction-compliant plan; otherwise the deterministic
        fallback is returned (identical to the pre-planner workflow
        resolution).
        """
        if provider_configured(self.llm_provider):
            try:
                plan = self.planner.plan(requirement)
            except Exception:  # planning must never break the request path
                logger.exception("goal planning failed; using deterministic plan")
                plan = None
            if plan is not None and plan.steps:
                return plan
        return self._deterministic_plan(requirement)

    def _deterministic_plan(self, requirement: str) -> GoalPlan:
        """Build the deterministic fallback plan from the capability engine.

        The steps are exactly the current ``execution_capabilities`` in
        catalog order (already restriction-filtered by ``match``), one
        step per capability, so behavior matches the existing workflow
        path.
        """
        resolution = self.capability_service.resolve_for_goal(requirement)
        steps = [
            PlanStep(capability=capability, goal=requirement)
            for capability in resolution.execution_capabilities
        ]
        return GoalPlan(requirement=requirement, steps=steps, source="deterministic")

    # ------------------------------------------------------------------
    # Convenience used by the API layer
    # ------------------------------------------------------------------
    @staticmethod
    def plan_to_dict(plan: GoalPlan) -> list[dict[str, Any]]:
        """Serialize a plan to the persisted JSON form (list of steps)."""
        return [step.model_dump(mode="json") for step in plan.steps]
