"""Scheduling boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask, TaskStatus


class DevelopmentScheduler:
    """Select the next pending ADS task in the supplied order."""

    def select_next(self, tasks: tuple[DevelopmentTask, ...]) -> DevelopmentTask | None:
        """Select the first pending task, if any."""

        return next((task for task in tasks if task.status is TaskStatus.PENDING), None)
