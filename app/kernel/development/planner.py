"""Planning boundary for the Autonomous Development System."""

from __future__ import annotations

from uuid import UUID

from app.kernel.development.models import DevelopmentTask

_PHASES: tuple[tuple[str, str], ...] = (
    (
        "Define requirements for {objective}",
        "Clarify scope, inputs, and acceptance criteria for the objective.",
    ),
    (
        "Implement {objective}",
        "Implement the agreed scope for the objective.",
    ),
    (
        "Test {objective}",
        "Add and run focused tests covering the implemented objective.",
    ),
    (
        "Document and finalize {objective}",
        "Document behavior, usage, and completion notes for the objective.",
    ),
)


class DevelopmentPlanner:
    """Translate an objective into a deterministic development plan."""

    def plan(self, objective: str) -> tuple[DevelopmentTask, ...]:
        """Decompose ``objective`` into a dependency-ordered task plan.

        The same objective always yields the same task titles, order, and
        dependency chain, so plans are reviewable before execution.

        Args:
            objective: Business or engineering objective to plan.

        Returns:
            Planned development tasks in dependency order.

        Raises:
            ValueError: If the objective is blank.
        """
        normalized_objective = objective.strip()
        if not normalized_objective:
            raise ValueError("Objective must not be empty")

        tasks: list[DevelopmentTask] = []
        previous_task_id: UUID | None = None

        for title_template, description in _PHASES:
            task = DevelopmentTask(
                title=title_template.format(objective=normalized_objective),
                description=description,
                dependencies=[previous_task_id] if previous_task_id is not None else [],
            )
            tasks.append(task)
            previous_task_id = task.id

        return tuple(tasks)
