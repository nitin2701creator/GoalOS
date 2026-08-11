"""Scheduling boundary for the Autonomous Development System."""

from __future__ import annotations

from app.kernel.development.models import DevelopmentTask, TaskStatus


class DevelopmentScheduler:
    """Select the next eligible ADS task using deterministic rules."""

    def select_next(self, tasks: tuple[DevelopmentTask, ...]) -> DevelopmentTask | None:
        """Return the first pending task whose dependencies are completed.

        Eligibility rules:

        - the task must currently be ``PENDING``;
        - every declared dependency must refer to a known task that is
          ``COMPLETED``; and
        - selection is stable in input order, so repeated calls over the
          same state return the same task.

        Args:
            tasks: Tasks to consider for scheduling.

        Returns:
            The next eligible task, or ``None`` when nothing can run.
        """
        completed_ids = {task.id for task in tasks if task.status is TaskStatus.COMPLETED}

        for task in tasks:
            if task.status is not TaskStatus.PENDING:
                continue
            if any(dependency not in completed_ids for dependency in task.dependencies):
                continue
            return task

        return None
