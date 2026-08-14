"""LLM-driven goal planner for GoalOS.

The planner turns a plain-language business goal into an ordered,
validated capability plan. It asks the configured LLM provider to
decompose the goal into minimal steps, then enforces GoalOS's hard
guarantees locally:

- only REGISTERED capabilities are ever accepted (free-form LLM output is
  never trusted);
- every capability is normalized to its catalog execution capability so
  steps map 1:1 onto the workflow steps the execution runtime persists;
- explicit user restrictions ("use ONLY X", "do not use Y") are applied
  as the final filter — a prohibited capability is never planned, never
  executed, and never persisted, even when the LLM suggests it;
- an unparseable or empty LLM plan yields ``None`` so the caller falls
  back to the deterministic resolver (existing behavior preserved).

The planner is generic: it is driven by the registered capability
catalog, not hard-coded to any one capability, integration, or company.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.ai.llm_gateway import LLMGateway
from app.ai.planner_prompts import build_plan_prompt
from app.llm.base_provider import BaseProvider
from app.schemas.plan import GoalPlan, PlanStep
from app.services.capability_service import CapabilityService

logger = logging.getLogger(__name__)


def parse_plan_text(text: str) -> list[dict[str, Any]] | None:
    """Parse an LLM plan response into a list of raw step dicts.

    Defensive: tolerates code fences, prose around the JSON, a bare
    ``{"steps": [...]}`` object, or a bare array. Returns ``None`` when
    nothing parseable is present.
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        steps = parsed.get("steps")
        if isinstance(steps, list):
            return [item for item in steps if isinstance(item, dict)]
    return None


class GoalPlanner:
    """Decompose a goal into an ordered, validated capability plan.

    Args:
        capability_service: The persistent capability engine used to list
            registered capabilities, resolve suggested names, and apply
            explicit restrictions.
        llm_provider: The configured GoalOS LLM provider; planning only
            runs when a provider with real credentials is supplied.
    """

    def __init__(
        self,
        capability_service: CapabilityService,
        llm_provider: BaseProvider | None = None,
    ) -> None:
        self.capability_service = capability_service
        self.llm_provider = llm_provider

    def plan(self, requirement: str) -> GoalPlan | None:
        """Return a validated, restriction-filtered plan, or ``None``.

        ``None`` means the LLM produced no usable plan (unparseable,
        invalid, empty, or entirely prohibited) — the caller should fall
        back to the deterministic resolver.
        """
        capabilities = [
            (capability.name, capability.description)
            for capability in self.capability_service.list()
        ]
        restrictions = self.capability_service.restrictions_for(requirement)
        prompt = build_plan_prompt(requirement, capabilities, restrictions)
        try:
            payload = self.llm_provider.request(prompt)
            text = LLMGateway._response_text(payload)
        except Exception as exc:  # noqa: BLE001 - a failing provider must never break planning
            logger.warning("goal planning LLM call failed; falling back: %s", exc)
            return None

        raw_steps = parse_plan_text(text)
        if raw_steps is None:
            logger.info("goal planning returned unparseable output; falling back")
            return None

        steps: list[PlanStep] = []
        seen: set[str] = set()
        for item in raw_steps:
            capability = str(item.get("capability", "")).strip()
            if not capability:
                continue
            capability = self._normalize(capability)
            if capability is None or capability in seen:
                continue
            seen.add(capability)
            steps.append(
                PlanStep(
                    capability=capability,
                    goal=str(item.get("goal") or "").strip(),
                    inputs=dict(item.get("inputs") or {}),
                )
            )
        if not steps:
            logger.info("goal planning returned no usable capability steps; falling back")
            return None

        # Hard restriction filter: a prohibited capability is never
        # planned, even when the LLM suggested it.
        steps = self.capability_service.restrict_plan(steps, requirement)
        if not steps:
            logger.info("goal planning steps all prohibited by restrictions; falling back")
            return None
        return GoalPlan(requirement=requirement, steps=steps, source="llm")

    def _normalize(self, name: str) -> str | None:
        """Map a suggested name to its catalog execution capability.

        Returns ``None`` for unregistered names (never trusted).
        """
        capability = self.capability_service.get_by_name(name)
        if capability is None:
            logger.info("goal planner ignored unregistered capability '%s'", name)
            return None
        return capability.execution_capability or capability.name
