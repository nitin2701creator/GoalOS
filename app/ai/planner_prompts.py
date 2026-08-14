"""Prompt templates for the GoalOS goal planner.

The planner asks the configured LLM provider to decompose a plain-language
goal into an ordered, minimal plan of capability steps. The prompt is
built from the registered capability catalog (never free-form), includes
any explicit user restrictions, and demands a strict JSON response the
planner validates before anything is executed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.agents.capability_restrictions import CapabilityRestrictions


def build_plan_prompt(
    requirement: str,
    capabilities: Iterable[tuple[str, str]],
    restrictions: CapabilityRestrictions | None = None,
) -> str:
    """Build the goal-planning prompt for the LLM provider.

    Args:
        requirement: The user's goal text.
        capabilities: ``(name, description)`` pairs of the registered,
            executable capabilities the plan may use.
        restrictions: Explicit user restrictions to honour (whitelist /
            blacklist), when present.

    Returns:
        The full planning prompt.
    """
    lines = [
        "You are the GoalOS goal planning engine. Decompose the user's goal "
        "into an ordered, minimal plan of capability steps.",
        "",
        "Rules:",
        "- Return ONLY a JSON object with no extra text:",
        '  {"steps": [{"capability": "...", "goal": "...", "inputs": {...}}]}',
        "- Every step must use exactly one capability from the available list.",
        "- Order steps so a later step can use the output of an earlier step "
        "when one depends on the other.",
        "- Never invent capabilities. Never include a capability the goal "
        "does not genuinely require.",
        "- Keep the plan as small as possible; an empty plan is better than "
        "an unnecessary step.",
        "",
        "Available capabilities:",
    ]
    lines.extend(f"- {name}: {description}" for name, description in capabilities)
    lines.append("")
    if restrictions is not None and restrictions.active:
        lines.extend(
            [
                "The user explicitly restricted the capabilities.",
                restrictions.describe(),
                "Return ONLY capability steps that respect these restrictions; "
                "never suggest a prohibited capability.",
                "",
            ]
        )
    lines.append(f"Goal: {requirement}")
    lines.append("")
    lines.append("Return ONLY the JSON object.")
    return "\n".join(lines)


def build_plan_debug_context(plan: dict[str, Any] | None) -> str:
    """Return a compact summary of a plan dict for logging (no secrets)."""
    if not plan:
        return "no plan"
    steps = plan.get("steps") or []
    return ", ".join(
        str(step.get("capability", "?")) if isinstance(step, dict) else str(step)
        for step in steps
    )
