"""Planning boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class DevelopmentPlanner:
    """Planning boundary for a selected development objective."""

    def plan(self, objective: str) -> tuple[DevelopmentTask, ...]:
        """Return the planned task collection for ``objective``.

        The orchestrator already has a selected task, so the default planner
        deliberately creates no additional backlog items.
        """

        return ()
