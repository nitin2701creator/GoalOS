"""Execution evaluation for the GoalOS control loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.db.models.execution import Execution, ExecutionStatus


class DecisionType(str, Enum):
    """Actions the GoalOS control loop can recommend."""

    CONTINUE = "continue"
    RETRY = "retry"
    HUMAN_REVIEW = "human_review"
    WAIT = "wait"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExecutionDecision:
    """Normalized management decision produced from an execution."""

    action: DecisionType
    reason: str
    execution_id: str
    task_id: str
    agent_name: str
    retry_count: int
    result: str | None = None
    error_message: str | None = None


class ExecutionEvaluator:
    """Evaluate an execution and recommend the next GoalOS action."""

    def __init__(self, max_retries: int = 3) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")

        self.max_retries = max_retries

    def evaluate(self, execution: Execution) -> ExecutionDecision:
        """Convert execution state into a control-loop decision."""

        if execution.status is ExecutionStatus.COMPLETED:
            if execution.result and execution.result.strip():
                return self._decision(
                    execution,
                    DecisionType.CONTINUE,
                    "Execution completed successfully with a result.",
                )

            return self._decision(
                execution,
                DecisionType.HUMAN_REVIEW,
                "Execution completed but produced no result.",
            )

        if execution.status is ExecutionStatus.FAILED:
            if execution.retry_count < self.max_retries:
                return self._decision(
                    execution,
                    DecisionType.RETRY,
                    "Execution failed and remains within the retry limit.",
                )

            return self._decision(
                execution,
                DecisionType.HUMAN_REVIEW,
                "Execution failed and exhausted the retry limit.",
            )

        if execution.status is ExecutionStatus.CANCELLED:
            return self._decision(
                execution,
                DecisionType.CANCELLED,
                "Execution was cancelled.",
            )

        if execution.status in {
            ExecutionStatus.PENDING,
            ExecutionStatus.RUNNING,
            ExecutionStatus.RETRYING,
        }:
            return self._decision(
                execution,
                DecisionType.WAIT,
                f"Execution is currently {execution.status.value.lower()}.",
            )

        return self._decision(
            execution,
            DecisionType.HUMAN_REVIEW,
            "Execution is in an unsupported state.",
        )

    @staticmethod
    def _decision(
        execution: Execution,
        action: DecisionType,
        reason: str,
    ) -> ExecutionDecision:
        return ExecutionDecision(
            action=action,
            reason=reason,
            execution_id=str(execution.id),
            task_id=str(execution.task_id),
            agent_name=execution.agent_name,
            retry_count=execution.retry_count,
            result=execution.result,
            error_message=execution.error_message,
        )