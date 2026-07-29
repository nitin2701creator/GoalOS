"""Deterministic KPI planning logic."""

from __future__ import annotations

import uuid


class KPIGenerator:
    """Generates KPIs from goals."""

    def generate(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        kpis = []
        for index, goal in enumerate(goals, start=1):
            kpis.append(
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, f"kpi:{goal}"),
                    "name": f"KPI {index}: {goal}",
                    "description": f"Measure success for the business goal '{goal}'.",
                    "target": "TBD",
                }
            )
        return kpis
