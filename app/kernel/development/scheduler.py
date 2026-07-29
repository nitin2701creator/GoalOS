"""Scheduling boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask


class DevelopmentScheduler:
    """Placeholder for selecting the next eligible ADS task."""

    def select_next(self, tasks: tuple[DevelopmentTask, ...]) -> DevelopmentTask | None:
        """Select a task when ordering and eligibility rules are defined."""

        # TODO: Define deterministic scheduling and dependency rules.
        raise NotImplementedError


# TODO: Add scheduling policy and queue state contracts.
