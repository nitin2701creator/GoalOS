"""Tests for the GoalOS autonomous execution control loop."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from app.control_loop.control_loop import ControlLoop, ControlLoopAction
from app.db.models.execution import ExecutionStatus


def make_execution(
    *,
    status: ExecutionStatus,
    result: str | None = None,
    retry_count: int = 0,
    error_message: str | None = None,
):
    """Create a lightweight execution object for control-loop tests."""

    return SimpleNamespace(
        id=uuid4(),
        task_id=uuid4(),
        agent_name="test-agent",
        status=status,
        result=result,
        retry_count=retry_count,
        error_message=error_message,
    )


def test_control_loop_returns_not_found():
    service = MagicMock()
    service.get.return_value = None

    execution_id = uuid4()
    control_loop = ControlLoop(service)

    decision = control_loop.process(execution_id)

    assert decision.execution_id == execution_id
    assert decision.action is ControlLoopAction.NOT_FOUND
    assert decision.retry_count == 0

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_not_called()


def test_control_loop_completes_successful_execution():
    execution = make_execution(
        status=ExecutionStatus.COMPLETED,
        result="Task completed successfully.",
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.COMPLETE
    assert decision.retry_count == 0

    service.append_execution_log.assert_called_once()
    service.retry_execution.assert_not_called()


def test_control_loop_retries_failed_execution():
    execution = make_execution(
        status=ExecutionStatus.FAILED,
        retry_count=0,
        error_message="Temporary failure.",
    )

    updated_execution = SimpleNamespace(
        retry_count=1,
    )

    service = MagicMock()
    service.get.return_value = execution
    service.retry_execution.return_value = updated_execution

    control_loop = ControlLoop(service, max_retries=3)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.RETRY
    assert decision.retry_count == 1

    service.retry_execution.assert_called_once_with(execution.id)
    service.append_execution_log.assert_called_once()


def test_control_loop_waits_for_pending_execution():
    execution = make_execution(
        status=ExecutionStatus.PENDING,
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.WAIT

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_not_called()


def test_control_loop_waits_for_running_execution():
    execution = make_execution(
        status=ExecutionStatus.RUNNING,
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.WAIT

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_not_called()


def test_control_loop_waits_for_retrying_execution():
    execution = make_execution(
        status=ExecutionStatus.RETRYING,
        retry_count=1,
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.WAIT
    assert decision.retry_count == 1

    service.retry_execution.assert_not_called()


def test_control_loop_handles_cancelled_execution():
    execution = make_execution(
        status=ExecutionStatus.CANCELLED,
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.CANCELLED

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_not_called()


def test_control_loop_requests_intervention_after_retry_limit():
    execution = make_execution(
        status=ExecutionStatus.FAILED,
        retry_count=3,
        error_message="Persistent failure.",
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service, max_retries=3)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.INTERVENTION
    assert decision.retry_count == 3

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_called_once()


def test_control_loop_requests_intervention_when_completed_without_result():
    execution = make_execution(
        status=ExecutionStatus.COMPLETED,
        result=None,
    )

    service = MagicMock()
    service.get.return_value = execution

    control_loop = ControlLoop(service)
    decision = control_loop.process(execution.id)

    assert decision.action is ControlLoopAction.INTERVENTION

    service.retry_execution.assert_not_called()
    service.append_execution_log.assert_called_once()