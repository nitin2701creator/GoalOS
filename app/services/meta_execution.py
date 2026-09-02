"""Meta Ads execution engine for GoalOS.

Controls all write operations to the Meta Marketing API.
Three execution modes: SAFE, SUPERVISED, AUTONOMOUS.

Every write action must be a typed, validated GoalOS action.
No arbitrary Meta API execution is permitted.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.db.models.meta_ads import (
    ActionStatus,
    ActionType,
    ExecutionMode,
    MetaAuditLog,
    MetaExecutionAction,
    RiskLevel,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget guardrails
# ---------------------------------------------------------------------------

@dataclass
class BudgetGuardrails:
    """Configurable limits for Meta Ads spend."""
    max_daily_budget: float = 1000.0
    max_budget_increase_pct: float = 50.0
    max_budget_change: float = 500.0
    approval_threshold: float = 100.0
    max_campaigns: int = 50
    max_ad_sets: int = 200
    max_ads: int = 500


# Risk levels for each action type
_ACTION_RISK: dict[str, str] = {
    ActionType.CREATE_CAMPAIGN.value: RiskLevel.MEDIUM.value,
    ActionType.CREATE_ADSET.value: RiskLevel.MEDIUM.value,
    ActionType.CREATE_AD.value: RiskLevel.MEDIUM.value,
    ActionType.CREATE_CREATIVE.value: RiskLevel.LOW.value,
    ActionType.UPDATE_CAMPAIGN.value: RiskLevel.LOW.value,
    ActionType.UPDATE_ADSET.value: RiskLevel.LOW.value,
    ActionType.UPDATE_AD.value: RiskLevel.LOW.value,
    ActionType.ACTIVATE.value: RiskLevel.MEDIUM.value,
    ActionType.PAUSE.value: RiskLevel.LOW.value,
    ActionType.INCREASE_BUDGET.value: RiskLevel.HIGH.value,
    ActionType.DECREASE_BUDGET.value: RiskLevel.LOW.value,
    ActionType.DUPLICATE.value: RiskLevel.LOW.value,
}

# Actions that always require approval regardless of mode
_ALWAYS_APPROVAL = frozenset({
    ActionType.INCREASE_BUDGET.value,
    ActionType.CREATE_CAMPAIGN.value,
    ActionType.CREATE_ADSET.value,
    ActionType.CREATE_AD.value,
})


class ExecutionEngine:
    """Controls Meta Ads execution with approval, guardrails, and audit."""

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.SAFE,
        guardrails: BudgetGuardrails | None = None,
    ) -> None:
        self.mode = mode
        self.guardrails = guardrails or BudgetGuardrails()
        self._actions: dict[str, MetaExecutionAction] = {}

    def create_action(
        self,
        action_type: str,
        parameters: dict[str, Any],
        *,
        entity_type: str | None = None,
        entity_meta_id: str | None = None,
        actor: str | None = None,
    ) -> MetaExecutionAction:
        """Create a new execution action (always starts as dry_run or pending_approval)."""
        risk = _ACTION_RISK.get(action_type, RiskLevel.MEDIUM.value)
        requires_approval = (
            action_type in _ALWAYS_APPROVAL
            or risk in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value)
            or self.mode == ExecutionMode.SAFE
        )

        action = MetaExecutionAction(
            id=uuid4(),
            action_type=action_type,
            entity_type=entity_type,
            entity_meta_id=entity_meta_id,
            parameters=parameters,
            status=ActionStatus.DRY_RUN.value if self.mode == ExecutionMode.SAFE else ActionStatus.PENDING_APPROVAL.value,
            execution_mode=self.mode.value,
            risk_level=risk,
            requires_approval=requires_approval,
            approved=False,
        )

        # Validate budget guardrails
        guardrail_errors = self._check_guardrails(action_type, parameters)
        if guardrail_errors:
            action.error_message = "; ".join(guardrail_errors)
            action.status = ActionStatus.FAILED.value

        self._actions[str(action.id)] = action
        return action

    def approve_action(
        self,
        action_id: UUID,
        approved_by: str = "system",
    ) -> MetaExecutionAction | None:
        """Approve a pending action."""
        action = self._actions.get(str(action_id))
        if action is None:
            return None
        if action.status != ActionStatus.PENDING_APPROVAL.value:
            return action
        if not action.requires_approval:
            # Auto-approve non-approval-required actions
            action.approved = True
            action.approved_by = approved_by
            action.approved_at = datetime.now(timezone.utc)
            action.status = ActionStatus.APPROVED.value
        else:
            action.approved = True
            action.approved_by = approved_by
            action.approved_at = datetime.now(timezone.utc)
            action.status = ActionStatus.APPROVED.value
        return action

    def reject_action(
        self,
        action_id: UUID,
        reason: str = "Rejected by operator",
    ) -> MetaExecutionAction | None:
        """Reject a pending action."""
        action = self._actions.get(str(action_id))
        if action is None:
            return None
        action.status = ActionStatus.REJECTED.value
        action.error_message = reason
        return action

    def execute_action(
        self,
        action_id: UUID,
        meta_adapter: Any = None,
    ) -> MetaExecutionAction | None:
        """Execute an approved action through the Meta adapter.

        This is the ONLY path to Meta API writes.
        """
        action = self._actions.get(str(action_id))
        if action is None:
            return None

        if action.status != ActionStatus.APPROVED.value:
            action.status = ActionStatus.FAILED.value
            action.error_message = f"Cannot execute: status is '{action.status}'"
            return action

        if action.requires_approval and not action.approved:
            action.error_message = "Cannot execute: approval required but not granted"
            return action

        # Mark as executing
        action.status = ActionStatus.EXECUTING.value

        # Execute through the Meta adapter
        try:
            if meta_adapter is None:
                action.status = ActionStatus.FAILED.value
                action.error_message = "No Meta adapter configured"
                return action

            result = self._dispatch_to_meta(action, meta_adapter)
            action.execution_result = result
            action.status = ActionStatus.COMPLETED.value
            action.executed_at = datetime.now(timezone.utc)

        except Exception as exc:
            logger.exception("Meta execution failed for action %s", action_id)
            action.status = ActionStatus.FAILED.value
            action.error_message = str(exc)

        return action

    def get_action(self, action_id: UUID) -> MetaExecutionAction | None:
        return self._actions.get(str(action_id))

    def list_actions(
        self,
        status: str | None = None,
        action_type: str | None = None,
    ) -> list[MetaExecutionAction]:
        actions = list(self._actions.values())
        if status:
            actions = [a for a in actions if a.status == status]
        if action_type:
            actions = [a for a in actions if a.action_type == action_type]
        return sorted(actions, key=lambda a: a.created_at or datetime.min.replace(tzinfo=timezone.utc))

    def create_audit_record(
        self,
        action: MetaExecutionAction,
        *,
        actor: str | None = None,
        meta_response: dict[str, Any] | None = None,
    ) -> MetaAuditLog:
        """Create an immutable audit log entry."""
        return MetaAuditLog(
            id=uuid4(),
            action_id=action.id,
            action_type=action.action_type,
            entity_type=action.entity_type,
            entity_meta_id=action.entity_meta_id,
            status=action.status,
            actor=actor,
            details=action.parameters,
            meta_response=meta_response or action.execution_result,
            error=action.error_message,
        )

    # -- Internal --

    def _check_guardrails(self, action_type: str, params: dict[str, Any]) -> list[str]:
        """Check budget and count guardrails."""
        errors = []

        if action_type == ActionType.CREATE_CAMPAIGN.value:
            budget = params.get("daily_budget") or params.get("lifetime_budget")
            if budget and budget > self.guardrails.max_daily_budget:
                errors.append(
                    f"Budget ${budget:.2f} exceeds max daily budget ${self.guardrails.max_daily_budget:.2f}"
                )

        if action_type == ActionType.INCREASE_BUDGET.value:
            increase = params.get("increase_amount", 0)
            current = params.get("current_budget", 0)
            if increase > self.guardrails.max_budget_change:
                errors.append(
                    f"Budget increase ${increase:.2f} exceeds max change ${self.guardrails.max_budget_change:.2f}"
                )
            if current > 0 and (increase / current * 100) > self.guardrails.max_budget_increase_pct:
                errors.append(
                    f"Budget increase {increase/current*100:.1f}% exceeds max {self.guardrails.max_budget_increase_pct:.0f}%"
                )

        return errors

    def _dispatch_to_meta(self, action: MetaExecutionAction, adapter: Any) -> dict[str, Any]:
        """Dispatch a validated action to the Meta adapter."""
        params = action.parameters

        if action.action_type == ActionType.CREATE_CAMPAIGN.value:
            return adapter.create_campaign(params)
        elif action.action_type == ActionType.CREATE_ADSET.value:
            return adapter.create_adset(params)
        elif action.action_type == ActionType.CREATE_AD.value:
            return adapter.create_ad(params)
        elif action.action_type == ActionType.CREATE_CREATIVE.value:
            return adapter.create_creative(params)
        elif action.action_type == ActionType.UPDATE_CAMPAIGN.value:
            return adapter.update_campaign(action.entity_meta_id, params)
        elif action.action_type == ActionType.UPDATE_ADSET.value:
            return adapter.update_adset(action.entity_meta_id, params)
        elif action.action_type == ActionType.UPDATE_AD.value:
            return adapter.update_ad(action.entity_meta_id, params)
        elif action.action_type == ActionType.ACTIVATE.value:
            return adapter.update_status(action.entity_meta_id, "ACTIVE")
        elif action.action_type == ActionType.PAUSE.value:
            return adapter.update_status(action.entity_meta_id, "PAUSED")
        elif action.action_type == ActionType.INCREASE_BUDGET.value:
            return adapter.update_budget(action.entity_meta_id, params.get("new_budget", 0))
        elif action.action_type == ActionType.DECREASE_BUDGET.value:
            return adapter.update_budget(action.entity_meta_id, params.get("new_budget", 0))
        elif action.action_type == ActionType.DUPLICATE.value:
            return adapter.duplicate_entity(action.entity_meta_id, params)
        else:
            raise ValueError(f"Unknown action type: {action.action_type}")
