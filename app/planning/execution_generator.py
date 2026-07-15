"""Deterministic execution planning logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class ExecutionGenerator:
    """Generates execution requirements for tasks."""

    def generate(self, tasks: list[dict]) -> list[dict]:
        executions = []
        now = datetime.now(timezone.utc)
        for task in tasks:
            execution_id = uuid.uuid5(uuid.NAMESPACE_URL, f"execution:{task['id']}")
            executions.append(
                {
                    "id": execution_id,
                    "task_id": task["id"],
                    "agent_name": "unassigned",
                    "status": "Pending",
                    "started_at": None,
                    "completed_at": None,
                    "execution_duration_seconds": None,
                    "retry_count": 0,
                    "result": None,
                    "error_message": None,
                    "execution_logs": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return executions
