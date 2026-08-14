"""Schemas for GoalOS goal plans.

A :class:`GoalPlan` is the ordered, capability-based plan the goal planner
produces from a plain-language goal. Each :class:`PlanStep` names one
capability (a registered registry/catalog capability), a focused
sub-goal, and optional explicit inputs. The plan drives sequential,
result-chained execution through the existing execution runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    """One ordered capability step in a goal plan.

    Attributes:
        capability: Registered capability name to execute. Capabilities
            are normalized to their catalog execution capability (e.g.
            ``web_search`` → ``web_research``) so steps map 1:1 onto the
            workflow steps the runtime persists.
        goal: Focused sub-goal for this step (context for the executor).
        inputs: Explicit input overrides for this step; merged over the
            shared requirement input and the accumulated outputs of prior
            steps.
    """

    capability: str = Field(min_length=1)
    goal: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)


class GoalPlan(BaseModel):
    """The ordered capability plan for one goal.

    Attributes:
        requirement: The original user goal the plan was built from.
        steps: Ordered capability steps (empty when nothing was resolved).
        source: How the plan was produced — ``llm`` (goal planner) or
            ``deterministic`` (keyword catalog fallback with no LLM).
    """

    requirement: str
    steps: list[PlanStep] = Field(default_factory=list)
    source: Literal["llm", "deterministic"] = "deterministic"

    @property
    def capabilities(self) -> list[str]:
        """The ordered capability names of the plan steps."""
        return [step.capability for step in self.steps]
