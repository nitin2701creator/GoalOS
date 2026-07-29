"""Deterministic dependency planning logic."""

from __future__ import annotations


class DependencyGenerator:
    """Generates dependencies for tasks."""

    def generate(self, tasks: list[dict]) -> list[dict]:
        dependencies = []
        for index, task in enumerate(tasks, start=1):
            if index > 1 and task["project_id"] == tasks[index - 2]["project_id"]:
                dependencies.append(
                    {
                        "task_id": task["id"],
                        "depends_on_task_id": tasks[index - 2]["id"],
                    }
                )
        return dependencies
