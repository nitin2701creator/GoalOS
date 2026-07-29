"""Planning boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class DevelopmentPlanner:
    """Placeholder for translating ADS inputs into development tasks."""

    def plan(self, objective: str) -> tuple[DevelopmentTask, ...]:
        """Plan tasks for an objective when planning rules are defined."""

        # TODO: Define objective decomposition and approval requirements.
        raise NotImplementedError


# TODO: Introduce planning inputs, outputs, and traceability metadata.
