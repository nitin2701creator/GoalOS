"""Sprint 1 — Capability Foundation tests.

Comprehensive tests for:
- Capability Registry (new placeholders)
- Memory Foundation (remember, recall, search, forget, context, provider)
- Resource Monitor (normalized metrics, missing psutil)
- Capacity Advisor (healthy, warning, risk, upgrade, sustained pressure)
- Action Policy (READ, LOW, MEDIUM, HIGH, CRITICAL, approval flow)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.memory import MemoryRecord, MemoryType
from app.db.session import get_db
from app.memory import ContextResult, MemoryQuery, MemoryResult
from app.repositories.memory_repository import MemoryRepository
from app.schemas.memory import (
    ContextResponse,
    MemoryForgetRequest,
    MemoryRememberRequest,
    MemoryResponse,
    MemorySearchRequest,
)
from app.services.memory_service import MemoryProvider
from app.services.resource_monitor import ResourceMonitor, ResourceHistory, SystemMetrics
from app.services.capacity_advisor import (
    CapacityAdvisor,
    HealthStatus,
    Thresholds,
    _classify,
)
from app.services.action_policy import (
    ActionDeclaration,
    ActionPolicyEngine,
    PolicyDecision,
    RiskLevel,
    SPRINT1_ACTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = Session()
    # Clean memory table between tests
    session.query(MemoryRecord).delete()
    session.commit()
    yield session
    session.close()


@pytest.fixture()
def memory_provider(db):
    return MemoryProvider(MemoryRepository(db))


# ---------------------------------------------------------------------------
# 1. CAPABILITY REGISTRY — new placeholders
# ---------------------------------------------------------------------------

class TestCapabilityRegistryEnhancements:
    """Test that new capability placeholders were added correctly."""

    def test_new_capabilities_importable(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        expected_new = [
            "phone_voice_call",
            "sms_send",
            "seo_audit",
            "seo_keyword_research",
            "viral_idea_finder",
            "resource_monitor",
        ]
        for name in expected_new:
            assert name in BUILTIN_CAPABILITIES, f"{name} not in BUILTIN_CAPABILITIES"

    def test_phone_voice_call_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["phone_voice_call"]
        assert cap.category == "communication"
        assert cap.provider == "communications"
        assert cap.implementation == "phone_voice_call"

    def test_sms_send_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["sms_send"]
        assert cap.category == "communication"
        assert cap.provider == "communications"
        assert cap.implementation == "sms_send"

    def test_seo_audit_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["seo_audit"]
        assert cap.category == "seo"
        assert cap.implementation == "website.analyze"

    def test_viral_idea_finder_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["viral_idea_finder"]
        assert cap.category == "intelligence"
        assert cap.implementation == "viral.scan"

    def test_resource_monitor_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["resource_monitor"]
        assert cap.category == "system"
        assert cap.implementation == "system.resource_monitor"

    def test_existing_capabilities_preserved(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        # Existing capabilities must still exist
        assert "web_search" in BUILTIN_CAPABILITIES
        assert "seo_audit" in BUILTIN_CAPABILITIES
        assert "memory_store" in BUILTIN_CAPABILITIES
        assert "social_meta_create_post" in BUILTIN_CAPABILITIES


# ---------------------------------------------------------------------------
# 2. MEMORY FOUNDATION
# ---------------------------------------------------------------------------

class TestMemoryModel:
    """Test the MemoryRecord database model."""

    def test_memory_types(self):
        expected = {"fact", "preference", "decision", "conversation", "task", "event", "knowledge", "outcome"}
        actual = {mt.value for mt in MemoryType}
        assert actual == expected


class TestMemoryProvider:
    """Test the memory service (remember, recall, search, forget, context)."""

    def test_remember_and_recall(self, memory_provider):
        result = memory_provider.remember(
            entity="user:123",
            content="User prefers dark mode",
            memory_type="preference",
            importance=0.8,
            confidence=0.9,
            goal="ui_customization",
            source="user_settings",
        )
        assert result.entity == "user:123"
        assert result.content == "User prefers dark mode"
        assert result.memory_type == "preference"
        assert result.importance == 0.8

        recalled = memory_provider.recall(result.id)
        assert recalled is not None
        assert recalled.content == "User prefers dark mode"

    def test_remember_default_values(self, memory_provider):
        result = memory_provider.remember(
            entity="user:1",
            content="Test fact",
            memory_type="fact",
        )
        assert result.importance == 0.5
        assert result.confidence == 1.0

    def test_search_by_entity(self, memory_provider):
        memory_provider.remember("user:99", "Fact A", "fact")
        memory_provider.remember("user:99", "Fact B", "knowledge")
        memory_provider.remember("user:100", "Other fact", "fact")

        results = memory_provider.search(MemoryQuery(entity="user:99"))
        assert len(results) == 2
        assert all(r.entity == "user:99" for r in results)

    def test_search_by_memory_type(self, memory_provider):
        memory_provider.remember("user:1", "decision 1", "decision")
        memory_provider.remember("user:1", "fact 1", "fact")
        memory_provider.remember("user:1", "decision 2", "decision")

        results = memory_provider.search(
            MemoryQuery(entity="user:1", memory_type="decision")
        )
        assert len(results) == 2

    def test_search_by_query_text(self, memory_provider):
        memory_provider.remember("user:1", "Python is great for data science", "knowledge")
        memory_provider.remember("user:1", "JavaScript for web development", "knowledge")

        results = memory_provider.search(
            MemoryQuery(entity="user:1", query="Python")
        )
        assert len(results) == 1
        assert "Python" in results[0].content

    def test_search_by_goal(self, memory_provider):
        memory_provider.remember("user:1", "Goal A insight", "knowledge", goal="project_alpha")
        memory_provider.remember("user:1", "Goal B insight", "knowledge", goal="project_beta")

        results = memory_provider.search(
            MemoryQuery(entity="user:1", goal="project_alpha")
        )
        assert len(results) == 1

    def test_search_min_importance(self, memory_provider):
        memory_provider.remember("user:1", "Low importance", "fact", importance=0.2)
        memory_provider.remember("user:1", "High importance", "fact", importance=0.9)

        results = memory_provider.search(
            MemoryQuery(entity="user:1", min_importance=0.5)
        )
        assert len(results) == 1
        assert results[0].importance == 0.9

    def test_forget(self, memory_provider):
        result = memory_provider.remember("user:1", "To be forgotten", "fact")
        assert memory_provider.forget(result.id) is True

        recalled = memory_provider.recall(result.id)
        assert recalled is None

        # Forgotten items should not appear in search
        results = memory_provider.search(MemoryQuery(entity="user:1"))
        assert len(results) == 0

    def test_forget_nonexistent(self, memory_provider):
        fake_id = uuid.uuid4()
        assert memory_provider.forget(fake_id) is False

    def test_recall_nonexistent(self, memory_provider):
        assert memory_provider.recall(uuid.uuid4()) is None

    def test_get_context(self, memory_provider):
        memory_provider.remember("user:1", "Recent fact", "fact", importance=0.9, goal="goal_a")
        memory_provider.remember("user:1", "Another fact", "fact", importance=0.3)
        memory_provider.remember("user:1", "Preference", "preference", importance=0.7)

        ctx = memory_provider.get_context("user:1", limit=10)
        assert ctx.entity == "user:1"
        assert ctx.total_count == 3
        assert len(ctx.recent_memories) == 3
        assert len(ctx.key_facts) >= 1
        assert "goal_a" in ctx.active_goals

    def test_get_context_empty(self, memory_provider):
        ctx = memory_provider.get_context("nonexistent_user")
        assert ctx.total_count == 0
        assert ctx.recent_memories == []
        assert ctx.active_goals == []


class TestMemoryRepository:
    """Test the memory repository directly."""

    def test_count_for_entity(self, db):
        repo = MemoryRepository(db)
        entity = f"count_test_{uuid.uuid4().hex[:8]}"
        assert repo.count_for_entity(entity) == 0

    def test_active_goals(self, db):
        repo = MemoryRepository(db)
        entity = f"goals_test_{uuid.uuid4().hex[:8]}"
        mem_type = MemoryType.KNOWLEDGE
        for goal in ["goal_a", "goal_b", "goal_a"]:
            repo.create({
                "entity": entity,
                "content": f"test {goal}",
                "memory_type": mem_type,
                "goal": goal,
            })
        goals = repo.active_goals_for_entity(entity)
        assert set(goals) == {"goal_a", "goal_b"}


# ---------------------------------------------------------------------------
# 3. RESOURCE MONITOR
# ---------------------------------------------------------------------------

class TestResourceMonitor:
    """Test the Resource Monitor service."""

    def test_collect_returns_metrics(self):
        monitor = ResourceMonitor()
        metrics = monitor.collect()
        assert isinstance(metrics, SystemMetrics)
        assert metrics.cpu_count >= 1
        assert 0.0 <= metrics.cpu_percent <= 100.0 or metrics.cpu_percent == 0.0

    def test_to_dict(self):
        monitor = ResourceMonitor()
        metrics = monitor.collect()
        d = monitor.to_dict(metrics)
        assert "cpu_percent" in d
        assert "ram_percent" in d
        assert "swap_percent" in d
        assert "disk_percent" in d
        assert "cpu_count" in d
        assert "timestamp" in d

    def test_sustained_averages(self):
        monitor = ResourceMonitor()
        monitor.collect()
        monitor.collect()
        avg = monitor.get_sustained_averages()
        assert "cpu_percent" in avg
        assert avg["sample_count"] >= 2

    def test_resource_history_window(self):
        h = ResourceHistory(window_seconds=2)
        m1 = SystemMetrics(
            cpu_percent=10.0, ram_percent=20.0, swap_percent=0.0,
            disk_percent=30.0, load_avg_1m=1.0, load_avg_5m=1.0,
            load_avg_15m=1.0, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=1.0, swap_total_gb=0.0, swap_used_gb=0.0,
            disk_total_gb=50.0, disk_used_gb=15.0, process_count=100,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        h.add(m1)
        assert h.average("cpu_percent") == 10.0

    def test_fallback_when_no_psutil(self):
        """When psutil is not available, metrics should still return."""
        with patch("app.services.resource_monitor.psutil", None):
            monitor = ResourceMonitor()
            metrics = monitor.collect()
            assert metrics.cpu_count >= 1  # fallback returns 1


# ---------------------------------------------------------------------------
# 4. CAPACITY ADVISOR
# ---------------------------------------------------------------------------

class TestCapacityAdvisor:
    """Test the Capacity Advisor service."""

    def test_healthy_system(self):
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=30.0, ram_percent=40.0, swap_percent=1.0,
            disk_percent=50.0, load_avg_1m=0.5, load_avg_5m=0.4,
            load_avg_15m=0.3, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=1.6, swap_total_gb=2.0, swap_used_gb=0.02,
            disk_total_gb=50.0, disk_used_gb=25.0, process_count=100,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 30.0,
            "ram_percent": 40.0,
            "swap_percent": 1.0,
            "disk_percent": 50.0,
            "load_avg_1m": 0.5,
            "load_avg_5m": 0.4,
            "load_avg_15m": 0.3,
            "sample_count": 10,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        assert assessment.status == HealthStatus.HEALTHY
        assert assessment.recommended_plan is None

    def test_warning_system(self):
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=75.0, ram_percent=75.0, swap_percent=3.0,
            disk_percent=72.0, load_avg_1m=1.5, load_avg_5m=1.4,
            load_avg_15m=1.3, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=3.0, swap_total_gb=2.0, swap_used_gb=0.06,
            disk_total_gb=50.0, disk_used_gb=36.0, process_count=150,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 75.0, "ram_percent": 75.0,
            "swap_percent": 3.0, "disk_percent": 72.0,
            "load_avg_1m": 1.5, "load_avg_5m": 1.4,
            "load_avg_15m": 1.3, "sample_count": 10,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        assert assessment.status == HealthStatus.WARNING
        assert len(assessment.reasons) > 0

    def test_capacity_risk_system(self):
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=82.0, ram_percent=82.0, swap_percent=11.0,
            disk_percent=85.0, load_avg_1m=1.8, load_avg_5m=1.7,
            load_avg_15m=1.6, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=3.3, swap_total_gb=2.0, swap_used_gb=0.22,
            disk_total_gb=50.0, disk_used_gb=42.5, process_count=200,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 82.0, "ram_percent": 82.0,
            "swap_percent": 11.0, "disk_percent": 85.0,
            "load_avg_1m": 1.8, "load_avg_5m": 1.7,
            "load_avg_15m": 1.6, "sample_count": 10,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        assert assessment.status == HealthStatus.CAPACITY_RISK

    def test_upgrade_recommended_system(self):
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=88.0, ram_percent=88.0, swap_percent=16.0,
            disk_percent=92.0, load_avg_1m=2.2, load_avg_5m=2.1,
            load_avg_15m=2.0, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=3.5, swap_total_gb=2.0, swap_used_gb=0.32,
            disk_total_gb=50.0, disk_used_gb=46.0, process_count=250,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 88.0, "ram_percent": 88.0,
            "swap_percent": 16.0, "disk_percent": 92.0,
            "load_avg_1m": 2.2, "load_avg_5m": 2.1,
            "load_avg_15m": 2.0, "sample_count": 10,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        assert assessment.status == HealthStatus.UPGRADE_RECOMMENDED
        assert assessment.recommended_plan is not None

    def test_single_spike_does_not_trigger_upgrade(self):
        """Insufficient samples should downgrade upgrade to CAPACITY_RISK."""
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=90.0, ram_percent=90.0, swap_percent=20.0,
            disk_percent=95.0, load_avg_1m=2.5, load_avg_5m=2.4,
            load_avg_15m=2.3, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=3.6, swap_total_gb=2.0, swap_used_gb=0.4,
            disk_total_gb=50.0, disk_used_gb=47.5, process_count=300,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        # Only 1 sample — less than min_samples (3)
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 90.0, "ram_percent": 90.0,
            "swap_percent": 20.0, "disk_percent": 95.0,
            "load_avg_1m": 2.5, "load_avg_5m": 2.4,
            "load_avg_15m": 2.3, "sample_count": 1,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        # Should NOT be UPGRADE_RECOMMENDED with only 1 sample
        assert assessment.status != HealthStatus.UPGRADE_RECOMMENDED
        assert assessment.status == HealthStatus.CAPACITY_RISK

    def test_sustained_pressure_over_time(self):
        """Multiple samples at high levels should trigger upgrade."""
        monitor = MagicMock()
        monitor.collect.return_value = SystemMetrics(
            cpu_percent=86.0, ram_percent=86.0, swap_percent=16.0,
            disk_percent=91.0, load_avg_1m=2.0, load_avg_5m=1.9,
            load_avg_15m=1.8, cpu_count=2, ram_total_gb=4.0,
            ram_used_gb=3.44, swap_total_gb=2.0, swap_used_gb=0.32,
            disk_total_gb=50.0, disk_used_gb=45.5, process_count=200,
            goalos_process_healthy=True, timestamp=time.time(),
        )
        # Enough samples
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 86.0, "ram_percent": 86.0,
            "swap_percent": 16.0, "disk_percent": 91.0,
            "load_avg_1m": 2.0, "load_avg_5m": 1.9,
            "load_avg_15m": 1.8, "sample_count": 5,
        }
        advisor = CapacityAdvisor(monitor)
        assessment = advisor.assess()
        assert assessment.status == HealthStatus.UPGRADE_RECOMMENDED
        assert assessment.recommended_plan is not None


class TestClassify:
    """Test the _classify helper function."""

    def test_healthy(self):
        assert _classify(50.0, 70.0, 80.0, 85.0) == HealthStatus.HEALTHY

    def test_warning(self):
        assert _classify(72.0, 70.0, 80.0, 85.0) == HealthStatus.WARNING

    def test_risk(self):
        assert _classify(82.0, 70.0, 80.0, 85.0) == HealthStatus.CAPACITY_RISK

    def test_upgrade(self):
        assert _classify(86.0, 70.0, 80.0, 85.0) == HealthStatus.UPGRADE_RECOMMENDED

    def test_exact_boundary_warning(self):
        assert _classify(70.0, 70.0, 80.0, 85.0) == HealthStatus.WARNING

    def test_exact_boundary_risk(self):
        assert _classify(80.0, 70.0, 80.0, 85.0) == HealthStatus.CAPACITY_RISK

    def test_exact_boundary_upgrade(self):
        assert _classify(85.0, 70.0, 80.0, 85.0) == HealthStatus.UPGRADE_RECOMMENDED


# ---------------------------------------------------------------------------
# 5. ACTION POLICY
# ---------------------------------------------------------------------------

class TestActionPolicy:
    """Test the Action Policy engine."""

    def test_read_action_allowed(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("inspect_analytics")
        assert result.decision == PolicyDecision.ALLOWED

    def test_low_action_allowed(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("create_draft")
        assert result.decision == PolicyDecision.ALLOWED

    def test_medium_action_requires_approval(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("send_whatsapp")
        assert result.decision == PolicyDecision.APPROVAL_REQUIRED

    def test_high_action_requires_approval(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("publish_content")
        assert result.decision == PolicyDecision.APPROVAL_REQUIRED

    def test_critical_action_denied(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("infrastructure_change")
        assert result.decision == PolicyDecision.DENIED

    def test_critical_financial_denied(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("financial_transaction")
        assert result.decision == PolicyDecision.DENIED

    def test_unknown_action_denied(self):
        engine = ActionPolicyEngine()
        result = engine.evaluate("nonexistent_action")
        assert result.decision == PolicyDecision.DENIED
        assert "not registered" in result.reason

    def test_approved_context_allows_medium(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("send_whatsapp", has_approved_context=True)
        assert result.decision == PolicyDecision.ALLOWED

    def test_critical_still_denied_with_context(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("infrastructure_change", has_approved_context=True)
        assert result.decision == PolicyDecision.DENIED

    def test_cost_triggers_approval(self):
        engine = ActionPolicyEngine(max_cost_without_approval=0.0)
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        result = engine.evaluate("make_phone_call", cost_override=0.50)
        assert result.decision == PolicyDecision.APPROVAL_REQUIRED

    def test_sprint1_actions_count(self):
        assert len(SPRINT1_ACTIONS) >= 15

    def test_get_declaration(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        decl = engine.get_declaration("publish_content")
        assert decl is not None
        assert decl.risk_level == RiskLevel.HIGH

    def test_list_actions(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        actions = engine.list_actions()
        assert len(actions) >= 15

    def test_request_approval(self):
        engine = ActionPolicyEngine()
        for decl in SPRINT1_ACTIONS:
            engine.register(decl)
        req = engine.request_approval("send_whatsapp", "agent:123", reason="test")
        assert req is not None
        assert req.action_name == "send_whatsapp"
        assert req.risk_level == RiskLevel.MEDIUM
        assert len(engine.get_pending_approvals()) == 1
