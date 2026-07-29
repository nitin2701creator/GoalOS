"""Orchestration boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class DevelopmentOrchestrator:
    """Placeholder coordinator for the ADS lifecycle."""

    def run(self, task: DevelopmentTask) -> None:
        """Coordinate a task when ADS workflow behavior is defined."""

        # TODO: Coordinate approval, planning, execution, verification, and review.
        raise NotImplementedError


# TODO: Add explicit orchestration state and lifecycle events.
