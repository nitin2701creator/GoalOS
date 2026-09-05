"""Meta Ads API endpoints for GoalOS.

Endpoints for Meta campaign management, intelligence analysis,
campaign building, execution, and audit.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any
from uuid import UUID

from app.integrations.meta_write_adapter import MetaWriteAdapter
from app.services.meta_campaign_builder import (
    CampaignConfig,
    AdSetConfig,
    AdConfig,
    CreativeConfig,
    build_campaign,
    blueprint_to_dry_run,
)
from app.services.meta_execution import BudgetGuardrails, ExecutionEngine, ExecutionMode
from app.services.meta_intelligence import (
    audit_account,
    detect_fatigue,
    extract_competitor_intelligence,
    generate_ad_copy,
    score_creative,
)
from app.services.meta_optimization import MetaOptimizationEngine

router = APIRouter()


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CopyGenerationRequest(BaseModel):
    product: str = Field(min_length=1)
    benefits: list[str] = Field(default_factory=list)
    audience: str = ""
    angles: list[str] | None = None
    variations_per_angle: int = 4


class CreativeScoreRequest(BaseModel):
    headline: str = ""
    body: str = ""
    cta: str = ""
    description: str = ""
    creative_type: str = ""


class FatigueAnalysisRequest(BaseModel):
    performance_data: list[dict[str, Any]] = Field(default_factory=list)


class AccountAuditRequest(BaseModel):
    account_data: dict[str, Any] = Field(default_factory=dict)
    campaigns: list[dict[str, Any]] | None = None
    adsets: list[dict[str, Any]] | None = None
    ads: list[dict[str, Any]] | None = None
    performance: list[dict[str, Any]] | None = None


class CampaignBuildRequest(BaseModel):
    campaign: dict[str, Any]
    ad_sets: list[dict[str, Any]] | None = None
    ads: list[dict[str, Any]] | None = None
    creatives: list[dict[str, Any]] | None = None


class ExecutionRequest(BaseModel):
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    entity_type: str | None = None
    entity_meta_id: str | None = None


class ApprovalRequest(BaseModel):
    action_id: UUID
    approved: bool
    reason: str = ""


class OptimizationRequest(BaseModel):
    campaigns: list[dict[str, Any]] | None = None
    adsets: list[dict[str, Any]] | None = None
    ads: list[dict[str, Any]] | None = None
    performance: list[dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# Intelligence endpoints
# ---------------------------------------------------------------------------

class CompetitorRequest(BaseModel):
    ads: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/intelligence/competitors")
def analyze_competitors(request: CompetitorRequest):
    """Analyze competitor ads for hooks, offers, CTAs."""
    return extract_competitor_intelligence(request.ads)


@router.post("/intelligence/copy")
def generate_copy(request: CopyGenerationRequest):
    """Generate 20 on-brand ad copy variations."""
    return generate_ad_copy(
        product=request.product,
        benefits=request.benefits,
        audience=request.audience,
        angles=request.angles,
        variations_per_angle=request.variations_per_angle,
    )


@router.post("/intelligence/score")
def score_creative_endpoint(request: CreativeScoreRequest):
    """Score a creative across six dimensions."""
    result = score_creative(
        headline=request.headline,
        body=request.body,
        cta=request.cta,
        description=request.description,
        creative_type=request.creative_type,
    )
    return {
        "hook_score": result.hook_score,
        "copy_score": result.copy_score,
        "cta_score": result.cta_score,
        "emotional_pull": result.emotional_pull,
        "offer_clarity": result.offer_clarity,
        "visual_fit": result.visual_fit,
        "overall": result.overall,
        "feedback": result.feedback,
    }


@router.post("/intelligence/fatigue")
def analyze_fatigue(request: FatigueAnalysisRequest):
    """Detect creative fatigue signals."""
    signals = detect_fatigue(request.performance_data)
    return {
        "signals": [
            {
                "entity_id": s.entity_id,
                "entity_name": s.entity_name,
                "ctr": s.ctr,
                "frequency": s.frequency,
                "cpc": s.cpc,
                "spend": s.spend,
                "classification": s.classification,
                "reason": s.reason,
            }
            for s in signals
        ],
        "total": len(signals),
        "critical": sum(1 for s in signals if s.classification == "critical"),
        "warning": sum(1 for s in signals if s.classification == "warning"),
    }


@router.post("/intelligence/audit")
def audit_account_endpoint(request: AccountAuditRequest):
    """Full account audit with ranked findings."""
    return audit_account(
        account_data=request.account_data,
        campaigns=request.campaigns,
        adsets=request.adsets,
        ads=request.ads,
        performance=request.performance,
    )


# ---------------------------------------------------------------------------
# Campaign builder endpoints
# ---------------------------------------------------------------------------

@router.post("/campaign/build")
def build_campaign_endpoint(request: CampaignBuildRequest):
    """Build and validate a campaign blueprint."""
    campaign = CampaignConfig(**request.campaign)
    ad_sets = [AdSetConfig(**a) for a in (request.ad_sets or [])]
    ads = [AdConfig(**a) for a in (request.ads or [])]
    creatives = [CreativeConfig(**c) for c in (request.creatives or [])]

    blueprint = build_campaign(campaign, ad_sets, ads, creatives)
    return {
        "is_valid": blueprint.is_valid,
        "errors": blueprint.validation_errors,
        "warnings": blueprint.validation_warnings,
        "estimated_daily_spend": blueprint.estimated_daily_spend,
        "dry_run": blueprint_to_dry_run(blueprint),
    }


@router.post("/campaign/validate")
def validate_campaign_endpoint(request: CampaignBuildRequest):
    """Validate a campaign without building the full blueprint."""
    campaign = CampaignConfig(**request.campaign)
    ad_sets = [AdSetConfig(**a) for a in (request.ad_sets or [])]
    ads = [AdConfig(**a) for a in (request.ads or [])]
    creatives = [CreativeConfig(**c) for c in (request.creatives or [])]

    blueprint = build_campaign(campaign, ad_sets, ads, creatives)
    return {
        "is_valid": blueprint.is_valid,
        "errors": blueprint.validation_errors,
        "warnings": blueprint.validation_warnings,
    }


# ---------------------------------------------------------------------------
# Execution endpoints
# ---------------------------------------------------------------------------

# Module-level execution engine (stateless per request in production)
_engine = ExecutionEngine(mode=ExecutionMode.SAFE)


@router.post("/execution/dry-run")
def dry_run_action(request: ExecutionRequest):
    """Create a dry-run action (no execution)."""
    action = _engine.create_action(
        action_type=request.action_type,
        parameters=request.parameters,
        entity_type=request.entity_type,
        entity_meta_id=request.entity_meta_id,
    )
    return {
        "action_id": str(action.id),
        "status": action.status,
        "action_type": action.action_type,
        "risk_level": action.risk_level,
        "requires_approval": action.requires_approval,
        "parameters": action.parameters,
        "error": action.error_message,
    }


@router.post("/execution/request-approval")
def request_approval(request: ApprovalRequest):
    """Approve or reject an action."""
    if request.approved:
        action = _engine.approve_action(request.action_id)
    else:
        action = _engine.reject_action(request.action_id, reason=request.reason)

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")

    return {
        "action_id": str(action.id),
        "status": action.status,
        "approved": action.approved,
    }


@router.post("/execution/execute")
def execute_action(request: ExecutionRequest):
    """Create, approve, and execute a Meta Ads action.

    Flow:
    1. Create the action (with guardrail validation)
    2. Auto-approve in SUPERVISED/AUTONOMOUS mode
    3. Execute through MetaWriteAdapter if approved
    4. Return the result

    In SAFE mode the action stays as dry_run — no Meta API call is made.
    """
    action = _engine.create_action(
        action_type=request.action_type,
        parameters=request.parameters,
        entity_type=request.entity_type,
        entity_meta_id=request.entity_meta_id,
    )

    # Auto-approve in non-SAFE modes
    if _engine.mode != ExecutionMode.SAFE:
        _engine.approve_action(action.id, approved_by="system")

    # Execute through the Meta adapter if the action is approved
    if action.status == "approved":
        adapter = MetaWriteAdapter()
        action = _engine.execute_action(action.id, meta_adapter=adapter)

    return {
        "action_id": str(action.id),
        "status": action.status,
        "action_type": action.action_type,
        "execution_result": action.execution_result,
        "error": action.error_message,
    }


@router.get("/execution/status/{action_id}")
def get_action_status(action_id: UUID):
    """Get the status of an execution action."""
    action = _engine.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return {
        "action_id": str(action.id),
        "status": action.status,
        "action_type": action.action_type,
        "risk_level": action.risk_level,
        "approved": action.approved,
        "execution_result": action.execution_result,
        "error": action.error_message,
    }


@router.get("/execution/history")
def get_execution_history(
    status: str | None = None,
    action_type: str | None = None,
):
    """Get execution action history."""
    actions = _engine.list_actions(status=status, action_type=action_type)
    return {
        "actions": [
            {
                "action_id": str(a.id),
                "action_type": a.action_type,
                "entity_type": a.entity_type,
                "status": a.status,
                "risk_level": a.risk_level,
                "requires_approval": a.requires_approval,
                "approved": a.approved,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
        "total": len(actions),
    }


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------

@router.post("/optimization/recommendations")
def get_optimization_recommendations(request: OptimizationRequest):
    """Get optimization recommendations."""
    engine = MetaOptimizationEngine()
    recs = engine.analyze_and_recommend(
        campaigns=request.campaigns,
        adsets=request.adsets,
        ads=request.ads,
        performance=request.performance,
    )
    return {
        "recommendations": [
            {
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "entity_name": r.entity_name,
                "reason": r.reason,
                "confidence": r.confidence,
                "expected_impact": r.expected_impact,
                "risk_level": r.risk_level,
                "requires_approval": r.requires_approval,
            }
            for r in recs
        ],
        "total": len(recs),
    }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@router.get("/config")
def get_config():
    """Get Meta Ads configuration (no secrets)."""
    import os
    return {
        "access_token_configured": bool(os.environ.get("GOALOS_META_ACCESS_TOKEN")),
        "ad_account_configured": bool(os.environ.get("GOALOS_META_AD_ACCOUNT_ID")),
        "api_version": "v21.0",
        "execution_mode": _engine.mode.value,
        "guardrails": {
            "max_daily_budget": _engine.guardrails.max_daily_budget,
            "max_budget_increase_pct": _engine.guardrails.max_budget_increase_pct,
            "max_budget_change": _engine.guardrails.max_budget_change,
            "approval_threshold": _engine.guardrails.approval_threshold,
        },
    }
