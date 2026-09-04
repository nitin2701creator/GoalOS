"""Resource Guardian — comprehensive tests.

Covers:
- Capacity state machine and transitions
- Smart decision engine (multi-signal)
- Hysteresis/recovery
- Alert deduplication
- Container awareness (mocked)
- API endpoints
- Edge cases (no swap, Docker unavailable, single spike, sustained pressure)
- Agent capability registration
- No false upgrade recommendations
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.resource_guardian import (
    CapacityAlert,
    CapacityState,
    GuardianAssessment,
    GuardianThresholds,
    ResourceGuardian,
)
from app.services.resource_monitor import ResourceMonitor, SystemMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_metrics(**overrides) -> SystemMetrics:
    """Create a SystemMetrics with sensible defaults and optional overrides."""
    defaults = dict(
        cpu_percent=30.0,
        ram_percent=40.0,
        swap_percent=1.0,
        disk_percent=50.0,
        load_avg_1m=0.5,
        load_avg_5m=0.4,
        load_avg_15m=0.3,
        cpu_count=4,
        ram_total_gb=8.0,
        ram_used_gb=3.2,
        swap_total_gb=2.0,
        swap_used_gb=0.02,
        disk_total_gb=100.0,
        disk_used_gb=50.0,
        process_count=150,
        goalos_process_healthy=True,
        timestamp=time.time(),
    )
    defaults.update(overrides)
    return SystemMetrics(**defaults)


def _make_guardian_with_mock_monitor(
    metrics: SystemMetrics,
    sustained_overrides: dict | None = None,
) -> ResourceGuardian:
    """Create a ResourceGuardian with a mocked monitor returning fixed data."""
    monitor = MagicMock(spec=ResourceMonitor)
    monitor.collect.return_value = metrics

    sustained = {
        "cpu_percent": metrics.cpu_percent,
        "ram_percent": metrics.ram_percent,
        "swap_percent": metrics.swap_percent,
        "disk_percent": metrics.disk_percent,
        "load_avg_1m": metrics.load_avg_1m,
        "load_avg_5m": metrics.load_avg_5m,
        "load_avg_15m": metrics.load_avg_15m,
        "sample_count": 10,
    }
    if sustained_overrides:
        sustained.update(sustained_overrides)
    monitor.get_sustained_averages.return_value = sustained
    monitor.to_dict.return_value = {
        "cpu_percent": metrics.cpu_percent,
        "ram_percent": metrics.ram_percent,
        "swap_percent": metrics.swap_percent,
        "disk_percent": metrics.disk_percent,
        "load_avg_1m": metrics.load_avg_1m,
        "load_avg_5m": metrics.load_avg_5m,
        "load_avg_15m": metrics.load_avg_15m,
        "cpu_count": metrics.cpu_count,
        "ram_total_gb": metrics.ram_total_gb,
        "ram_used_gb": metrics.ram_used_gb,
        "swap_total_gb": metrics.swap_total_gb,
        "swap_used_gb": metrics.swap_used_gb,
        "disk_total_gb": metrics.disk_total_gb,
        "disk_used_gb": metrics.disk_used_gb,
        "process_count": metrics.process_count,
        "goalos_process_healthy": metrics.goalos_process_healthy,
        "timestamp": metrics.timestamp,
    }

    return ResourceGuardian(monitor=monitor)


# ---------------------------------------------------------------------------
# 1. CapacityState
# ---------------------------------------------------------------------------

class TestCapacityState:
    def test_state_ordering(self):
        assert CapacityState.HEALTHY.rank < CapacityState.WARNING.rank
        assert CapacityState.WARNING.rank < CapacityState.CAPACITY_RISK.rank
        assert CapacityState.CAPACITY_RISK.rank < CapacityState.CRITICAL.rank
        assert CapacityState.CRITICAL.rank < CapacityState.UPGRADE_REQUIRED.rank

    def test_is_worse_than(self):
        assert CapacityState.WARNING.is_worse_than(CapacityState.HEALTHY)
        assert CapacityState.CRITICAL.is_worse_than(CapacityState.WARNING)
        assert not CapacityState.HEALTHY.is_worse_than(CapacityState.WARNING)

    def test_is_better_than(self):
        assert CapacityState.HEALTHY.is_better_than(CapacityState.WARNING)
        assert not CapacityState.UPGRADE_REQUIRED.is_better_than(CapacityState.CRITICAL)


# ---------------------------------------------------------------------------
# 2. Healthy system
# ---------------------------------------------------------------------------

class TestHealthySystem:
    def test_healthy_assessment(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.HEALTHY
        assert assessment.score < 0.5
        assert assessment.recommended_action is None
        assert not assessment.upgrade_required

    def test_healthy_has_no_reasons(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert len(assessment.reasons) == 0

    def test_healthy_headroom(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.headroom["ram_percent"] == 60.0
        assert assessment.headroom["cpu_percent"] == 70.0
        assert assessment.headroom["disk_percent"] == 50.0


# ---------------------------------------------------------------------------
# 3. Warning states
# ---------------------------------------------------------------------------

class TestWarningState:
    def test_ram_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=75, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.WARNING
        assert "RAM" in assessment.affected_resources

    def test_cpu_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=75, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.WARNING
        assert "CPU" in assessment.affected_resources

    def test_disk_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=75)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.WARNING
        assert "Disk" in assessment.affected_resources


# ---------------------------------------------------------------------------
# 4. Capacity risk
# ---------------------------------------------------------------------------

class TestCapacityRisk:
    def test_ram_risk(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=85, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CAPACITY_RISK

    def test_multiple_resources_at_risk(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=85, ram_percent=85, disk_percent=85)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CAPACITY_RISK
        assert len(assessment.affected_resources) >= 2


# ---------------------------------------------------------------------------
# 5. Critical state
# ---------------------------------------------------------------------------

class TestCriticalState:
    def test_ram_critical(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=92, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL

    def test_cpu_critical(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=92, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL

    def test_disk_critical_very_low_free(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(
                cpu_percent=30, ram_percent=40, disk_percent=96,
                disk_total_gb=100.0, disk_used_gb=99.5,  # 0.5 GB free
            )
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL

    def test_critical_triggers_action(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=92, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.recommended_action is not None
        assert "Immediate" in assessment.recommended_action


# ---------------------------------------------------------------------------
# 6. Single spike does NOT trigger upgrade
# ---------------------------------------------------------------------------

class TestSingleSpikeGuard:
    def test_single_critical_does_not_upgrade(self):
        """A single critical sample should stay at CRITICAL, not escalate to UPGRADE."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=96, disk_percent=50),
            sustained_overrides={"sample_count": 1},
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL
        assert not assessment.upgrade_required

    def test_single_critical_with_insufficient_samples(self):
        """Should downgrade UPGRADE to CRITICAL when samples < min_samples."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=96, ram_percent=96, disk_percent=96),
            sustained_overrides={"sample_count": 2},
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL


# ---------------------------------------------------------------------------
# 7. Sustained pressure triggers upgrade
# ---------------------------------------------------------------------------

class TestSustainedPressure:
    def test_insufficient_samples_stays_critical(self):
        """With insufficient samples, upgrade should be downgraded to CRITICAL."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=96, disk_percent=50),
            sustained_overrides={"sample_count": 1},
        )
        a1 = guardian.assess()
        # Only 1 sample, so UPGRADE_REQUIRED from classifier gets downgraded
        assert a1.state == CapacityState.CRITICAL
        assert not a1.upgrade_required

    def test_sufficient_samples_can_upgrade(self):
        """With sufficient samples and sustained critical, upgrade should trigger."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=96, disk_percent=50),
            sustained_overrides={"sample_count": 5},
        )
        a1 = guardian.assess()
        # Enough samples, thresholds exceeded → UPGRADE_REQUIRED
        assert a1.state == CapacityState.UPGRADE_REQUIRED
        assert a1.upgrade_required
        assert a1.recommended_action is not None


# ---------------------------------------------------------------------------
# 8. Hysteresis / recovery
# ---------------------------------------------------------------------------

class TestHysteresis:
    def test_recovery_is_gradual(self):
        """Recovery from UPGRADE_REQUIRED should drop one level at a time."""
        # Drive to UPGRADE_REQUIRED with sufficient samples
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=96, disk_percent=50),
            sustained_overrides={"sample_count": 5},
        )
        a1 = guardian.assess()
        assert a1.state == CapacityState.UPGRADE_REQUIRED

        # Now return to healthy metrics
        healthy = _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        monitor = MagicMock(spec=ResourceMonitor)
        monitor.collect.return_value = healthy
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 30.0, "ram_percent": 40.0, "swap_percent": 1.0,
            "disk_percent": 50.0, "load_avg_1m": 0.5, "load_avg_5m": 0.4,
            "load_avg_15m": 0.3, "sample_count": 10,
        }
        monitor.to_dict.return_value = {}
        guardian._monitor = monitor

        # First recovery: should drop one level
        a = guardian.assess()
        assert a.state.rank == CapacityState.UPGRADE_REQUIRED.rank - 1

        # Keep recovering
        for _ in range(10):
            a = guardian.assess()

        # Eventually should reach HEALTHY
        assert a.state == CapacityState.HEALTHY


# ---------------------------------------------------------------------------
# 9. Alert deduplication
# ---------------------------------------------------------------------------

class TestAlertDeduplication:
    def test_same_state_does_not_duplicate_alert(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=75, disk_percent=50)
        )
        guardian.assess()
        guardian.assess()
        # Only one transition event should generate one alert
        alerts = guardian.get_alerts()
        warning_alerts = [a for a in alerts if a["alert_type"] == "resource_capacity_warning"]
        assert len(warning_alerts) == 1

    def test_recovery_generates_alert(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=75, disk_percent=50)
        )
        guardian.assess()  # WARNING

        # Recover to healthy
        healthy = _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        monitor = MagicMock(spec=ResourceMonitor)
        monitor.collect.return_value = healthy
        monitor.get_sustained_averages.return_value = {
            "cpu_percent": 30.0, "ram_percent": 40.0, "swap_percent": 1.0,
            "disk_percent": 50.0, "load_avg_1m": 0.5, "load_avg_5m": 0.4,
            "load_avg_15m": 0.3, "sample_count": 10,
        }
        monitor.to_dict.return_value = {}
        guardian._monitor = monitor
        guardian.assess()  # recover

        alerts = guardian.get_alerts()
        recovery = [a for a in alerts if a["alert_type"] == "resource_capacity_recovered"]
        assert len(recovery) >= 1

    def test_acknowledge_alert(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=75, disk_percent=50)
        )
        guardian.assess()
        result = guardian.acknowledge_alert(0)
        assert result is True

    def test_acknowledge_invalid_index(self):
        guardian = _make_guardian_with_mock_monitor(_make_metrics())
        assert guardian.acknowledge_alert(999) is False


# ---------------------------------------------------------------------------
# 10. GoalOS process unhealthy
# ---------------------------------------------------------------------------

class TestProcessHealth:
    def test_unhealthy_process_triggers_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50,
                          goalos_process_healthy=False)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.WARNING
        assert "Service" in assessment.affected_resources

    def test_healthy_process_no_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50,
                          goalos_process_healthy=True)
        )
        assessment = guardian.assess()
        assert "Service" not in assessment.affected_resources


# ---------------------------------------------------------------------------
# 11. Container awareness (mocked)
# ---------------------------------------------------------------------------

class TestContainerAwareness:
    @patch("app.services.resource_guardian.subprocess.run")
    def test_unhealthy_container_adds_warning(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="goalos|Up 5 minutes (unhealthy)\nnginx|Up 5 minutes\n",
        )
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert "Containers" in assessment.affected_resources
        assert any("unhealthy" in r for r in assessment.reasons)

    @patch("app.services.resource_guardian.subprocess.run")
    def test_docker_not_available_non_fatal(self, mock_run):
        mock_run.side_effect = FileNotFoundError("docker not found")
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.HEALTHY
        assert "Containers" not in assessment.affected_resources

    @patch("app.services.resource_guardian.subprocess.run")
    def test_all_containers_healthy(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="goalos|Up 5 minutes (healthy)\nnginx|Up 5 minutes\n",
        )
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert "Containers" not in assessment.affected_resources


# ---------------------------------------------------------------------------
# 12. No swap configured
# ---------------------------------------------------------------------------

class TestNoSwap:
    def test_no_swap_with_low_ram_triggers_risk(self):
        """No swap + high RAM should trigger at least CAPACITY_RISK."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(
                cpu_percent=30, ram_percent=92, disk_percent=50,
                swap_total_gb=0.0, swap_used_gb=0.0,
            ),
            sustained_overrides={"swap_percent": 0.0},
        )
        assessment = guardian.assess()
        assert assessment.state.rank >= CapacityState.CRITICAL.rank


# ---------------------------------------------------------------------------
# 13. Score calculation
# ---------------------------------------------------------------------------

class TestScore:
    def test_healthy_low_score(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.score < 0.5

    def test_critical_high_score(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=92, ram_percent=92, disk_percent=92)
        )
        assessment = guardian.assess()
        assert assessment.score >= 0.7


# ---------------------------------------------------------------------------
# 14. Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        d = guardian.to_dict(assessment)
        assert "state" in d
        assert "score" in d
        assert "reasons" in d
        assert "headroom" in d
        assert "current_metrics" in d
        assert "sustained_metrics" in d
        assert "evaluation_metadata" in d
        assert "alerts" in d

    def test_to_dict_no_assessment(self):
        guardian = ResourceGuardian()
        d = guardian.to_dict()
        assert d["state"] == "UNKNOWN"

    def test_assessment_timestamp(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=30, ram_percent=40, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.timestamp > 0


# ---------------------------------------------------------------------------
# 15. API endpoint test
# ---------------------------------------------------------------------------

class TestGuardianAPI:
    def test_api_import(self):
        from app.api.v1.resource_guardian import guardian_status, guardian_alerts, guardian_health
        assert callable(guardian_status)
        assert callable(guardian_alerts)
        assert callable(guardian_health)

    def test_guardian_status_returns_dict(self):
        from app.api.v1.resource_guardian import get_guardian
        guardian = get_guardian()
        assessment = guardian.assess()
        d = guardian.to_dict(assessment)
        assert isinstance(d, dict)
        assert "state" in d

    def test_guardian_health_returns_dict(self):
        from app.api.v1.resource_guardian import get_guardian
        guardian = get_guardian()
        assessment = guardian.assess()
        result = {
            "state": assessment.state.value,
            "upgrade_required": assessment.upgrade_required,
            "score": assessment.score,
            "timestamp": assessment.timestamp,
        }
        assert "state" in result


# ---------------------------------------------------------------------------
# 16. Agent capability registration
# ---------------------------------------------------------------------------

class TestAgentCapability:
    def test_resource_guardian_registered(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "resource_guardian" in BUILTIN_CAPABILITIES

    def test_resource_guardian_definition(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["resource_guardian"]
        assert cap.category == "system"
        assert cap.provider == "native"
        assert cap.implementation == "system.resource_guardian"
        assert "infrastructure" in cap.description.lower() or "capacity" in cap.description.lower()

    def test_resource_monitor_still_exists(self):
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "resource_monitor" in BUILTIN_CAPABILITIES


# ---------------------------------------------------------------------------
# 17. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_ram_available_warning_threshold(self):
        """Low available RAM should trigger warning even if percent is not high."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(
                cpu_percent=30, ram_percent=60, disk_percent=50,
                ram_total_gb=4.0, ram_used_gb=3.3,  # 0.7 GB available (< 1.0 GB warning)
            )
        )
        assessment = guardian.assess()
        assert assessment.state.rank >= CapacityState.WARNING.rank

    def test_very_low_disk_free(self):
        """Less than 1 GB free disk should trigger CRITICAL."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(
                cpu_percent=30, ram_percent=40, disk_percent=99,
                disk_total_gb=100.0, disk_used_gb=99.5,
            )
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL

    def test_load_average_high(self):
        """High load average should affect CPU status."""
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(
                cpu_percent=70,  # Below warning threshold
                ram_percent=40, disk_percent=50,
                load_avg_1m=4.0, load_avg_5m=3.5, load_avg_15m=3.0,
                cpu_count=2,
            ),
            sustained_overrides={"load_avg_5m": 3.5},
        )
        assessment = guardian.assess()
        # High load should push to at least WARNING
        assert assessment.state.rank >= CapacityState.WARNING.rank


# ---------------------------------------------------------------------------
# 18. GuardianThresholds
# ---------------------------------------------------------------------------

class TestThresholds:
    def test_default_thresholds(self):
        t = GuardianThresholds()
        assert t.ram_warning == 70.0
        assert t.ram_risk == 80.0
        assert t.ram_critical == 90.0
        assert t.ram_upgrade == 95.0
        assert t.min_samples_for_upgrade == 3

    def test_custom_thresholds(self):
        t = GuardianThresholds(ram_warning=60.0, ram_risk=75.0)
        assert t.ram_warning == 60.0
        assert t.ram_risk == 75.0


# ---------------------------------------------------------------------------
# 19. Multiple simultaneous pressures
# ---------------------------------------------------------------------------

class TestMultiplePressures:
    def test_ram_and_cpu_both_critical(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=92, ram_percent=92, disk_percent=50)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.CRITICAL
        assert "CPU" in assessment.affected_resources
        assert "RAM" in assessment.affected_resources
        assert len(assessment.reasons) >= 2

    def test_all_resources_warning(self):
        guardian = _make_guardian_with_mock_monitor(
            _make_metrics(cpu_percent=75, ram_percent=75, disk_percent=75)
        )
        assessment = guardian.assess()
        assert assessment.state == CapacityState.WARNING
        assert len(assessment.affected_resources) >= 3
