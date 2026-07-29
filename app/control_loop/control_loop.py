"""Autonomous execution control loop for GoalOS."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.control_loop.evaluator import DecisionType, ExecutionEvaluator
from app.services.execution_service import ExecutionService


class ControlLoopAction(str, Enum):
    """Actions the control loop can take."""

    COMPLETE = "complete"
    RETRY = "retry"
    WAIT = "wait"
    CANCELLED = "cancelled"
    INTERVENTION = "intervention"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ControlLoopDecision:
    """Structured decision returned by the GoalOS control loop."""

    execution_id: UUID
    action: ControlLoopAction
    reason: str
    retry_count: int = 0


class ControlLoop:
    """Evaluate executions and decide their next lifecycle action."""

    def __init__(
        self,
        execution_service: ExecutionService,
        evaluator: ExecutionEvaluator | None = None,
        max_retries: int = 3,
    ) -> None:
        self.execution_service = execution_service
        self.max_retries = max_retries
        self.evaluator = evaluator or ExecutionEvaluator(
            max_retries=max_retries
        )

    def process(self, execution_id: UUID) -> ControlLoopDecision:
        """Evaluate an execution and determine what GoalOS should do next."""

        execution = self.execution_service.get(execution_id)

        if execution is None:
            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.NOT_FOUND,
                reason="Execution not found.",
            )

        evaluation = self.evaluator.evaluate(execution)

        if evaluation.action is DecisionType.CONTINUE:
            self.execution_service.append_execution_log(
                execution_id,
                "\nControl loop: execution completed successfully.",
            )

            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.COMPLETE,
                reason=evaluation.reason,
                retry_count=execution.retry_count,
            )

        if evaluation.action is DecisionType.RETRY:
            updated = self.execution_service.retry_execution(execution_id)

            self.execution_service.append_execution_log(
                execution_id,
                "\nControl loop: execution scheduled for retry.",
            )

            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.RETRY,
                reason=evaluation.reason,
                retry_count=(
                    updated.retry_count
                    if updated is not None
                    else execution.retry_count + 1
                ),
            )

        if evaluation.action is DecisionType.WAIT:
            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.WAIT,
                reason=evaluation.reason,
                retry_count=execution.retry_count,
            )

        if evaluation.action is DecisionType.CANCELLED:
            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.CANCELLED,
                reason=evaluation.reason,
                retry_count=execution.retry_count,
            )

        if evaluation.action is DecisionType.HUMAN_REVIEW:
            self.execution_service.append_execution_log(
                execution_id,
                "\nControl loop: human intervention required.",
            )

            return ControlLoopDecision(
                execution_id=execution_id,
                action=ControlLoopAction.INTERVENTION,
                reason=evaluation.reason,
                retry_count=execution.retry_count,
            )

        return ControlLoopDecision(
            execution_id=execution_id,
            action=ControlLoopAction.INTERVENTION,
            reason="Control loop received an unsupported decision.",
            retry_count=execution.retry_count,
        )