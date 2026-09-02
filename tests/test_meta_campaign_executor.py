"""Comprehensive tests for the GoalOS Meta Campaign Executor.

Covers: intelligence layer, campaign builder, execution engine,
guardrails, approval flow, agent capability discovery, and
end-to-end orchestration path.
"""
from __future__ import annotations

import os
import secrets
from uuid import uuid4

import pytest

os.environ.setdefault("GOALOS_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))

from app.services.meta_intelligence import (
    extract_competitor_intelligence,
    generate_ad_copy,
    score_creative,
    detect_fatigue,
    audit_account,
)
from app.services.meta_campaign_builder import (
    CampaignConfig,
    AdSetConfig,
    AdConfig,
    CreativeConfig,
    build_campaign,
    blueprint_to_dry_run,
)
from app.services.meta_execution import (
    BudgetGuardrails,
    ExecutionEngine,
    ExecutionMode,
)
from app.services.meta_optimization import MetaOptimizationEngine
from app.db.models.meta_ads import ActionStatus, ActionType, ExecutionMode as ExecMode


# ---------------------------------------------------------------------------
# 1. Intelligence Layer
# ---------------------------------------------------------------------------

class TestCompetitorIntelligence:
    def test_empty_ads(self):
        result = extract_competitor_intelligence([])
        assert result["ads_analyzed"] == 0
        assert result["hooks"] == []

    def test_extract_hooks(self):
        ads = [
            {"id": "1", "body": "Did you know AI can 10x your ads?", "headline": "AI Ads", "cta": "Learn More"},
            {"id": "2", "body": "Stop wasting money on bad ads.", "headline": "Save Money", "cta": "Shop Now"},
        ]
        result = extract_competitor_intelligence(ads)
        assert result["ads_analyzed"] == 2
        assert len(result["hooks"]) == 2
        assert len(result["cta_patterns"]) == 2

    def test_extract_offers(self):
        ads = [{"id": "1", "body": "Get 50% off your first month. Free trial available."}]
        result = extract_competitor_intelligence(ads)
        assert len(result["offers"]) >= 1

    def test_hook_ranking(self):
        ads = [
            {"id": "1", "body": "Did you know?"},
            {"id": "2", "body": "Did you know?"},
            {"id": "3", "body": "Something else"},
        ]
        result = extract_competitor_intelligence(ads)
        assert len(result["hook_ranking"]) >= 1


class TestCopyGeneration:
    def test_generates_20_variations(self):
        result = generate_ad_copy(
            product="GoalOS",
            benefits=["saves time", "increases revenue"],
            audience="SaaS founders",
        )
        assert result["total_variations"] == 20
        assert len(result["variations"]) == 20

    def test_all_angles_covered(self):
        result = generate_ad_copy(product="Test", benefits=["benefit1"])
        angles = set(v["angle"] for v in result["variations"])
        assert len(angles) == 5

    def test_each_variation_has_required_fields(self):
        result = generate_ad_copy(product="Test", benefits=["benefit1"])
        for v in result["variations"]:
            assert "angle" in v
            assert "body" in v
            assert "headline" in v
            assert "cta" in v

    def test_custom_angles(self):
        result = generate_ad_copy(
            product="Test",
            benefits=["benefit1"],
            angles=["problem_agitate"],
        )
        assert result["total_variations"] == 4
        assert all(v["angle"] == "problem_agitate" for v in result["variations"])


class TestCreativeScoring:
    def test_empty_creative(self):
        score = score_creative()
        assert score.overall < 0.2
        assert len(score.feedback) > 0

    def test_strong_creative(self):
        score = score_creative(
            headline="Stop scrolling — this changes everything",
            body="Join 5000+ customers who saved 10 hours per week. Free trial, no commitment.",
            cta="Start Free Trial",
        )
        assert score.overall > 0.5
        assert score.hook_score > 0.4
        assert score.cta_score > 0.5

    def test_weak_creative_gets_feedback(self):
        score = score_creative(headline="Hi", body="Buy stuff")
        assert score.overall < 0.5
        assert len(score.feedback) >= 1

    def test_scores_are_bounded(self):
        score = score_creative(
            headline="Amazing secret — you won't believe this",
            body="Save 50% today! Free trial, guaranteed results, limited time offer!",
            cta="Shop Now",
        )
        assert 0.0 <= score.overall <= 1.0
        assert 0.0 <= score.hook_score <= 1.0


class TestFatigueDetection:
    def test_healthy_performance(self):
        data = [{"id": "1", "name": "Ad 1", "ctr": 2.5, "frequency": 1.5, "cpc": 0.50}]
        signals = detect_fatigue(data)
        assert len(signals) == 1
        assert signals[0].classification == "healthy"

    def test_critical_fatigue(self):
        data = [{"id": "1", "name": "Ad 1", "ctr": 0.3, "frequency": 6.0, "cpc": 12.0}]
        signals = detect_fatigue(data)
        assert signals[0].classification == "critical"
        assert "critically" in signals[0].reason

    def test_warning_fatigue(self):
        data = [{"id": "1", "name": "Ad 1", "ctr": 0.8, "frequency": 3.5, "cpc": 6.0}]
        signals = detect_fatigue(data)
        assert signals[0].classification == "warning"


class TestAccountAudit:
    def test_empty_account(self):
        result = audit_account({})
        assert result["total_findings"] >= 1
        assert result["critical"] >= 1

    def test_healthy_account(self):
        result = audit_account(
            account_data={"id": "123"},
            campaigns=[{"id": "c1"}, {"id": "c2"}],
            adsets=[{"id": "a1", "daily_budget": 50}],
            ads=[{"id": "ad1", "creative": {"id": "cr1"}}],
            performance=[{"id": "c1", "ctr": 2.0, "frequency": 1.5}],
        )
        assert result["critical"] == 0
        assert result["score"] > 80

    def test_too_many_campaigns(self):
        result = audit_account(
            account_data={"id": "123"},
            campaigns=[{"id": f"c{i}"} for i in range(25)],
        )
        warnings = [f for f in result["findings"] if f["severity"] == "warning"]
        assert any("Too many campaigns" in w["title"] for w in warnings)


# ---------------------------------------------------------------------------
# 2. Campaign Builder
# ---------------------------------------------------------------------------

class TestCampaignBuilder:
    def test_valid_campaign(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="Test Campaign", objective="SALES"),
            ad_sets=[AdSetConfig(name="Test AdSet", campaign_name="Test Campaign", daily_budget=50)],
            ads=[AdConfig(name="Test Ad", adset_name="Test AdSet", campaign_name="Test Campaign")],
            creatives=[CreativeConfig(name="Test Creative", body="Buy now", call_to_action_type="SHOP_NOW")],
        )
        assert blueprint.is_valid
        assert len(blueprint.validation_errors) == 0

    def test_invalid_objective(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="Test", objective="INVALID"),
        )
        assert not blueprint.is_valid
        assert any("objective" in e.lower() for e in blueprint.validation_errors)

    def test_missing_name(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="", objective="SALES"),
        )
        assert not blueprint.is_valid

    def test_dry_run_output(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="Dry Run Test", objective="SALES", daily_budget=100),
            ad_sets=[AdSetConfig(name="AdSet 1", campaign_name="Dry Run Test", daily_budget=100)],
        )
        dry_run = blueprint_to_dry_run(blueprint)
        assert dry_run["mode"] == "dry_run"
        assert dry_run["is_valid"]
        assert dry_run["estimated_daily_spend"] == 100.0
        assert len(dry_run["meta_api_actions"]) >= 1

    def test_budget_estimation(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="Budget Test", objective="SALES"),
            ad_sets=[
                AdSetConfig(name="A1", campaign_name="Budget Test", daily_budget=30),
                AdSetConfig(name="A2", campaign_name="Budget Test", daily_budget=70),
            ],
        )
        assert blueprint.estimated_daily_spend == 100.0

    def test_api_actions_sequence(self):
        blueprint = build_campaign(
            campaign=CampaignConfig(name="Seq Test", objective="SALES"),
            ad_sets=[AdSetConfig(name="A1", campaign_name="Seq Test", daily_budget=50)],
            creatives=[CreativeConfig(name="C1", body="text", call_to_action_type="LEARN_MORE")],
            ads=[AdConfig(name="Ad1", adset_name="A1", campaign_name="Seq Test")],
        )
        dry_run = blueprint_to_dry_run(blueprint)
        actions = dry_run["meta_api_actions"]
        types = [a["type"] for a in actions]
        assert "create_campaign" in types
        assert "create_adset" in types
        assert "create_creative" in types
        assert "create_ad" in types


# ---------------------------------------------------------------------------
# 3. Execution Engine
# ---------------------------------------------------------------------------

class TestExecutionEngine:
    def test_safe_mode_creates_dry_run(self):
        engine = ExecutionEngine(mode=ExecutionMode.SAFE)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        assert action.status == ActionStatus.DRY_RUN.value
        assert action.requires_approval

    def test_supervised_mode_requires_approval(self):
        engine = ExecutionEngine(mode=ExecutionMode.SUPERVISED)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        assert action.status == ActionStatus.PENDING_APPROVAL.value

    def test_approval_flow(self):
        engine = ExecutionEngine(mode=ExecutionMode.SUPERVISED)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        approved = engine.approve_action(action.id, approved_by="admin")
        assert approved.status == ActionStatus.APPROVED.value
        assert approved.approved
        assert approved.approved_by == "admin"

    def test_rejection_flow(self):
        engine = ExecutionEngine(mode=ExecutionMode.SUPERVISED)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        rejected = engine.reject_action(action.id, reason="Too expensive")
        assert rejected.status == ActionStatus.REJECTED.value
        assert "Too expensive" in rejected.error_message

    def test_budget_guardrails_reject_overspend(self):
        engine = ExecutionEngine(
            mode=ExecutionMode.SUPERVISED,
            guardrails=BudgetGuardrails(max_daily_budget=100),
        )
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES", "daily_budget": 500},
        )
        assert action.status == ActionStatus.FAILED.value
        assert "exceeds" in action.error_message

    def test_budget_increase_guardrails(self):
        engine = ExecutionEngine(
            mode=ExecutionMode.SUPERVISED,
            guardrails=BudgetGuardrails(max_budget_change=100),
        )
        action = engine.create_action(
            action_type=ActionType.INCREASE_BUDGET.value,
            parameters={"increase_amount": 200, "current_budget": 50},
        )
        assert action.status == ActionStatus.FAILED.value

    def test_cannot_execute_unapproved(self):
        engine = ExecutionEngine(mode=ExecutionMode.SUPERVISED)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        # Action is pending_approval, not approved — execute should fail
        result = engine.execute_action(action.id, meta_adapter=None)
        assert result.status == ActionStatus.FAILED.value
        assert result.error_message is not None

    def test_audit_record_created(self):
        engine = ExecutionEngine(mode=ExecutionMode.SUPERVISED)
        action = engine.create_action(
            action_type=ActionType.CREATE_CAMPAIGN.value,
            parameters={"name": "Test", "objective": "SALES"},
        )
        audit = engine.create_audit_record(action, actor="test-agent")
        assert audit.action_type == ActionType.CREATE_CAMPAIGN.value
        assert audit.actor == "test-agent"


# ---------------------------------------------------------------------------
# 4. Optimization Engine
# ---------------------------------------------------------------------------

class TestOptimizationEngine:
    def test_no_data(self):
        engine = MetaOptimizationEngine()
        recs = engine.analyze_and_recommend()
        assert recs == []

    def test_pause_underperforming_ad(self):
        engine = MetaOptimizationEngine()
        ads = [{"id": "ad1", "name": "Bad Ad", "status": "ACTIVE"}]
        performance = [{"id": "ad1", "ctr": 0.3, "spend": 50, "cpc": 5.0}]
        recs = engine.analyze_and_recommend(ads=ads, performance=performance)
        pause_recs = [r for r in recs if r.action == "pause_ad"]
        assert len(pause_recs) == 1
        assert pause_recs[0].confidence > 0.5

    def test_activate_strong_ad(self):
        engine = MetaOptimizationEngine()
        ads = [{"id": "ad2", "name": "Good Ad", "status": "PAUSED"}]
        performance = [{"id": "ad2", "ctr": 3.0}]
        recs = engine.analyze_and_recommend(ads=ads, performance=performance)
        activate_recs = [r for r in recs if r.action == "activate_ad"]
        assert len(activate_recs) == 1

    def test_fatigue_recommendation(self):
        engine = MetaOptimizationEngine()
        ads = [{"id": "ad3", "name": "Tired Ad", "status": "ACTIVE"}]
        performance = [{"id": "ad3", "frequency": 5.0, "ctr": 1.5}]
        recs = engine.analyze_and_recommend(ads=ads, performance=performance)
        fatigue_recs = [r for r in recs if r.action == "replace_creative"]
        assert len(fatigue_recs) == 1

    def test_recommendations_sorted_by_confidence(self):
        engine = MetaOptimizationEngine()
        ads = [
            {"id": "ad1", "name": "Ad 1", "status": "ACTIVE"},
            {"id": "ad2", "name": "Ad 2", "status": "PAUSED"},
        ]
        performance = [
            {"id": "ad1", "ctr": 0.2, "spend": 100},
            {"id": "ad2", "ctr": 3.5},
        ]
        recs = engine.analyze_and_recommend(ads=ads, performance=performance)
        if len(recs) > 1:
            assert recs[0].confidence >= recs[-1].confidence


# ---------------------------------------------------------------------------
# 5. Agent Capability Discovery
# ---------------------------------------------------------------------------

class TestAgentCapabilityDiscovery:
    """Prove that Meta capabilities are registered and discoverable."""

    def test_meta_capabilities_exist(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        meta_caps = [k for k in BUILTIN_CAPABILITIES if k.startswith("meta_")]
        assert len(meta_caps) >= 15

    def test_read_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for cap in ["meta_get_accounts", "meta_get_campaigns", "meta_get_adsets",
                     "meta_get_ads", "meta_get_insights"]:
            assert cap in BUILTIN_CAPABILITIES, f"{cap} not registered"

    def test_intelligence_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for cap in ["meta_audit_account", "meta_analyze_fatigue", "meta_research_competitors",
                     "meta_generate_copy", "meta_score_creative"]:
            assert cap in BUILTIN_CAPABILITIES, f"{cap} not registered"

    def test_build_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for cap in ["meta_build_campaign", "meta_validate_campaign"]:
            assert cap in BUILTIN_CAPABILITIES, f"{cap} not registered"

    def test_execution_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for cap in ["meta_dry_run", "meta_request_approval", "meta_execute_action",
                     "meta_get_action_status"]:
            assert cap in BUILTIN_CAPABILITIES, f"{cap} not registered"

    def test_audit_capabilities_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "meta_get_audit_log" in BUILTIN_CAPABILITIES

    def test_capabilities_have_schemas(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in ["meta_get_accounts", "meta_get_campaigns"]:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.input_schema is not None
            assert cap.output_schema is not None

    def test_write_capabilities_require_approval(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        for name in ["meta_build_campaign", "meta_execute_action", "meta_request_approval"]:
            cap = BUILTIN_CAPABILITIES[name]
            assert cap.requires_approval, f"{name} should require approval"


# ---------------------------------------------------------------------------
# 6. API Endpoints
# ---------------------------------------------------------------------------

class TestMetaAdsAPI:
    @pytest.fixture
    def api(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.db import session as session_module
        from app.db.base import Base
        from app.main import app

        monkeypatch.delenv("GOALOS_META_ACCESS_TOKEN", raising=False)
        engine = create_engine(
            f"sqlite:///{tmp_path / 'meta_test.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        def override_get_db():
            db = factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[session_module.get_db] = override_get_db
        try:
            with TestClient(app) as client:
                yield client
        finally:
            app.dependency_overrides.clear()
            engine.dispose()

    def test_config_endpoint(self, api):
        response = api.get("/api/v1/meta/config")
        assert response.status_code == 200
        data = response.json()
        assert "access_token_configured" in data
        assert data["api_version"] == "v21.0"

    def test_generate_copy(self, api):
        response = api.post("/api/v1/meta/intelligence/copy", json={
            "product": "GoalOS",
            "benefits": ["saves time", "increases revenue"],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total_variations"] == 20

    def test_score_creative(self, api):
        response = api.post("/api/v1/meta/intelligence/score", json={
            "headline": "Stop scrolling — this changes everything",
            "body": "Join 5000+ customers who saved 10 hours per week.",
            "cta": "Start Free Trial",
        })
        assert response.status_code == 200
        data = response.json()
        assert "overall" in data
        assert 0.0 <= data["overall"] <= 1.0

    def test_fatigue_analysis(self, api):
        response = api.post("/api/v1/meta/intelligence/fatigue", json={
            "performance_data": [
                {"id": "1", "name": "Ad 1", "ctr": 0.3, "frequency": 6.0, "cpc": 12.0},
            ],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["critical"] == 1

    def test_build_campaign(self, api):
        response = api.post("/api/v1/meta/campaign/build", json={
            "campaign": {"name": "API Test", "objective": "SALES"},
            "ad_sets": [{"name": "AdSet 1", "campaign_name": "API Test", "daily_budget": 50}],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"]
        assert "dry_run" in data

    def test_validate_campaign(self, api):
        response = api.post("/api/v1/meta/campaign/validate", json={
            "campaign": {"name": "Validate Test", "objective": "INVALID"},
        })
        assert response.status_code == 200
        data = response.json()
        assert not data["is_valid"]

    def test_dry_run(self, api):
        response = api.post("/api/v1/meta/execution/dry-run", json={
            "action_type": "create_campaign",
            "parameters": {"name": "Dry Run Test", "objective": "SALES"},
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "dry_run"

    def test_optimization_recommendations(self, api):
        response = api.post("/api/v1/meta/optimization/recommendations", json={
            "ads": [{"id": "ad1", "name": "Test", "status": "ACTIVE"}],
            "performance": [{"id": "ad1", "ctr": 0.2, "spend": 100}],
        })
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
