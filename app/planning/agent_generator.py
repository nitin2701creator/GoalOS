"""Deterministic AI agent requirement planning logic."""

from __future__ import annotations


class AgentGenerator:
    """Generates agent requirements from vision and goals."""

    def generate(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        agents = []
        for index, goal in enumerate(goals, start=1):
            agents.append(
                {
                    "name": f"Agent {index}: {goal} Coordinator",
                    "role": "Planning",
                    "responsibility": f"Coordinate activities for the business goal '{goal}'.",
                }
            )
        return agents
