"""GoalOS Action Policy Foundation — risk-based approval engine.

Every capability action declares its risk level, whether approval is
required, and whether it has external side effects. The policy engine
returns ALLOWED, APPROVAL_REQUIRED, or DENIED without performing the
action itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """Risk classification for capability actions."""

    READ = "READ"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyDecision(str, Enum):
    """Policy engine decision."""

    ALLOWED = "ALLOWED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class ActionDeclaration:
    """A declared action and its risk profile."""

    action_name: str
    risk_level: RiskLevel
    approval_required: bool
    reversible: bool
    has_external_side_effect: bool
    estimated_cost: float  # 0.0 = free
    required_capability: str | None = None
    description: str = ""


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """The result of evaluating an action against the policy."""

    action_name: str
    decision: PolicyDecision
    risk_level: RiskLevel
    reason: str
    approval_required: bool
    reversible: bool
    has_external_side_effect: bool
    estimated_cost: float


@dataclass(slots=True)
class ApprovalRequest:
    """A pending approval request for a high-risk action."""

    action_name: str
    risk_level: RiskLevel
    requested_by: str
    reason: str
    estimated_cost: float


# ---------------------------------------------------------------------------
# Default policy configuration
# ---------------------------------------------------------------------------

def _default_risk_overrides() -> dict[RiskLevel, bool]:
    """Default: which risk levels always require approval."""
    return {
        RiskLevel.READ: False,
        RiskLevel.LOW: False,
        RiskLevel.MEDIUM: True,
        RiskLevel.HIGH: True,
        RiskLevel.CRITICAL: True,
    }


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class ActionPolicyEngine:
    """Risk-based policy engine for capability actions.

    Evaluates whether an action is allowed, needs approval, or is denied.
    """

    def __init__(
        self,
        risk_overrides: dict[RiskLevel, bool] | None = None,
        max_cost_without_approval: float = 0.0,
    ) -> None:
        self._declarations: dict[str, ActionDeclaration] = {}
        self._risk_overrides = risk_overrides or _default_risk_overrides()
        self._max_cost_without_approval = max_cost_without_approval
        self._pending_approvals: list[ApprovalRequest] = []

    def register(self, declaration: ActionDeclaration) -> None:
        """Register an action declaration."""
        self._declarations[declaration.action_name] = declaration

    def register_many(self, declarations: list[ActionDeclaration]) -> None:
        for d in declarations:
            self.register(d)

    def evaluate(
        self,
        action_name: str,
        *,
        has_approved_context: bool = False,
        cost_override: float | None = None,
    ) -> PolicyEvaluation:
        """Evaluate whether an action is allowed."""
        decl = self._declarations.get(action_name)
        if decl is None:
            return PolicyEvaluation(
                action_name=action_name,
                decision=PolicyDecision.DENIED,
                risk_level=RiskLevel.CRITICAL,
                reason=f"Action '{action_name}' is not registered",
                approval_required=False,
                reversible=False,
                has_external_side_effect=False,
                estimated_cost=0.0,
            )

        # CRITICAL actions are always denied without explicit override
        if decl.risk_level == RiskLevel.CRITICAL:
            return PolicyEvaluation(
                action_name=action_name,
                decision=PolicyDecision.DENIED,
                risk_level=decl.risk_level,
                reason="CRITICAL actions are denied by default",
                approval_required=decl.approval_required,
                reversible=decl.reversible,
                has_external_side_effect=decl.has_external_side_effect,
                estimated_cost=decl.estimated_cost,
            )

        # Check if approval is required by risk level or explicit declaration
        needs_approval = (
            decl.approval_required
            or self._risk_overrides.get(decl.risk_level, False)
        )

        # Cost check
        cost = cost_override if cost_override is not None else decl.estimated_cost
        if cost > self._max_cost_without_approval and cost > 0:
            needs_approval = True

        if needs_approval and not has_approved_context:
            return PolicyEvaluation(
                action_name=action_name,
                decision=PolicyDecision.APPROVAL_REQUIRED,
                risk_level=decl.risk_level,
                reason=(
                    f"Action requires approval "
                    f"(risk: {decl.risk_level.value}, "
                    f"cost: ${cost:.2f})"
                ),
                approval_required=True,
                reversible=decl.reversible,
                has_external_side_effect=decl.has_external_side_effect,
                estimated_cost=cost,
            )

        return PolicyEvaluation(
            action_name=action_name,
            decision=PolicyDecision.ALLOWED,
            risk_level=decl.risk_level,
            reason="Action is allowed",
            approval_required=False,
            reversible=decl.reversible,
            has_external_side_effect=decl.has_external_side_effect,
            estimated_cost=cost,
        )

    def request_approval(
        self,
        action_name: str,
        requested_by: str,
        reason: str = "",
    ) -> ApprovalRequest | None:
        """Create an approval request for a pending action."""
        decl = self._declarations.get(action_name)
        if decl is None:
            return None
        req = ApprovalRequest(
            action_name=action_name,
            risk_level=decl.risk_level,
            requested_by=requested_by,
            reason=reason,
            estimated_cost=decl.estimated_cost,
        )
        self._pending_approvals.append(req)
        return req

    def get_pending_approvals(self) -> list[ApprovalRequest]:
        return list(self._pending_approvals)

    def get_declaration(self, action_name: str) -> ActionDeclaration | None:
        return self._declarations.get(action_name)

    def list_actions(self) -> list[ActionDeclaration]:
        return list(self._declarations.values())


# ---------------------------------------------------------------------------
# Pre-defined action declarations for GoalOS Sprint 1
# ---------------------------------------------------------------------------

SPRINT1_ACTIONS: list[ActionDeclaration] = [
    # READ actions
    ActionDeclaration(
        action_name="inspect_analytics",
        risk_level=RiskLevel.READ,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Read analytics data from connected platforms",
    ),
    ActionDeclaration(
        action_name="search_web",
        risk_level=RiskLevel.READ,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Search the web for information",
    ),
    ActionDeclaration(
        action_name="inspect_memory",
        risk_level=RiskLevel.READ,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Recall or search stored memories",
    ),
    ActionDeclaration(
        action_name="read_social",
        risk_level=RiskLevel.READ,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Read social media post/account data",
    ),
    ActionDeclaration(
        action_name="system_status",
        risk_level=RiskLevel.READ,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Check system resource status",
    ),
    # LOW actions
    ActionDeclaration(
        action_name="create_draft",
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Create a draft content item",
    ),
    ActionDeclaration(
        action_name="create_recommendation",
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Generate an actionable recommendation",
    ),
    ActionDeclaration(
        action_name="store_memory",
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        description="Store a memory record",
    ),
    # MEDIUM actions
    ActionDeclaration(
        action_name="send_whatsapp",
        risk_level=RiskLevel.MEDIUM,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        required_capability="whatsapp_send_message",
        description="Send a WhatsApp message to a contact",
    ),
    ActionDeclaration(
        action_name="make_phone_call",
        risk_level=RiskLevel.MEDIUM,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.10,
        description="Initiate an AI phone call",
    ),
    ActionDeclaration(
        action_name="send_email",
        risk_level=RiskLevel.MEDIUM,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        required_capability="gmail_send",
        description="Send an email",
    ),
    # HIGH actions
    ActionDeclaration(
        action_name="publish_content",
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        required_capability="social_publish",
        description="Publish content to social media platforms",
    ),
    ActionDeclaration(
        action_name="bulk_messaging",
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        description="Send bulk messages to multiple recipients",
    ),
    ActionDeclaration(
        action_name="video_generation",
        risk_level=RiskLevel.HIGH,
        approval_required=True,
        reversible=True,
        has_external_side_effect=True,
        estimated_cost=1.00,
        description="Generate video content (API costs may apply)",
    ),
    # CRITICAL actions
    ActionDeclaration(
        action_name="infrastructure_change",
        risk_level=RiskLevel.CRITICAL,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        description="Modify production infrastructure",
    ),
    ActionDeclaration(
        action_name="destructive_data_operation",
        risk_level=RiskLevel.CRITICAL,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        description="Destructive data operations (delete, truncate)",
    ),
    ActionDeclaration(
        action_name="financial_transaction",
        risk_level=RiskLevel.CRITICAL,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        description="Financial transactions or payments",
    ),
]
