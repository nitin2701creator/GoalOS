"""Resource Guardian — monitoring loop and API integration tests.

Covers:
- Monitor start/stop lifecycle
- Configurable interval
- Tick execution
- Status reporting
- Singleton behavior
- API endpoint responses
- Environment variable configuration
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

from app.control_loop.resource_guardian_monitor import (
    ResourceGuardianMonitor,
    get_resource_guardian_monitor,
    start_resource_guardian_monitor,
    stop_resource_guardian_monitor,
)
from app.services.resource_guardian import (
    CapacityState,
    ResourceGuardian,
    GuardianThresholds,
)
from app.services.resource_monitor import ResourceMonitor, SystemMetrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_healthy_guardian() -> ResourceGuardian:
    """Create a ResourceGuardian with mocked healthy metrics."""
    monitor = MagicMock(spec=ResourceMonitor)
    monitor.collect.return_value = SystemMetrics(
        cpu_percent=30.0, ram_percent=40.0, swap_percent=1.0,
        disk_percent=50.0, load_avg_1m=0.5, load_avg_5m=0.4,
        load_avg_15m=0.3, cpu_count=4, ram_total_gb=8.0, ram_used_gb=3.2,
        swap_total_gb=2.0, swap_used_gb=0.02, disk_total_gb=100.0,
        disk_used_gb=50.0, process_count=150, goalos_process_healthy=True,
        timestamp=time.time(),
    )
    monitor.get_sustained_averages.return_value = {
        "cpu_percent": 30.0, "ram_percent": 40.0, "swap_percent": 1.0,
        "disk_percent": 50.0, "load_avg_1m": 0.5, "load_avg_5m": 0.4,
        "load_avg_15m": 0.3, "sample_count": 5,
    }
    monitor.to_dict.return_value = {
        "cpu_percent": 30.0, "ram_percent": 40.0, "swap_percent": 1.0,
        "disk_percent": 50.0, "load_avg_1m": 0.5, "load_avg_5m": 0.4,
        "load_avg_15m": 0.3, "cpu_count": 4, "ram_total_gb": 8.0,
        "ram_used_gb": 3.2, "swap_total_gb": 2.0, "swap_used_gb": 0.02,
        "disk_total_gb": 100.0, "disk_used_gb": 50.0, "process_count": 150,
        "goalos_process_healthy": True, "timestamp": time.time(),
    }
    return ResourceGuardian(monitor=monitor)


# ---------------------------------------------------------------------------
# 1. Monitor lifecycle
# ---------------------------------------------------------------------------

class TestMonitorLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=999
        )
        assert not monitor.is_running
        assert monitor.start() is True
        assert monitor.is_running
        # Second start is idempotent
        assert monitor.start() is False
        # Stop
        await monitor.stop()
        assert not monitor.is_running

    def test_disabled_monitor(self, monkeypatch):
        monkeypatch.setenv("GOALOS_RESOURCE_GUARDIAN_ENABLED", "0")
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=1
        )
        assert monitor.start() is False
        assert not monitor.is_running


# ---------------------------------------------------------------------------
# 2. Tick execution
# ---------------------------------------------------------------------------

class TestMonitorTick:
    @pytest.mark.asyncio
    async def test_tick_increments_count(self):
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=999
        )
        await monitor.tick()
        assert monitor.eval_count == 1
        assert monitor.last_evaluated_at is not None
        assert monitor.last_assessment is not None

    @pytest.mark.asyncio
    async def test_tick_records_assessment(self):
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=999
        )
        await monitor.tick()
        a = monitor.last_assessment
        assert a is not None
        assert "state" in a
        assert "score" in a
        assert "headroom" in a

    @pytest.mark.asyncio
    async def test_tick_handles_exception(self):
        guardian = MagicMock(spec=ResourceGuardian)
        guardian.assess.side_effect = RuntimeError("boom")
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=999
        )
        # Should not raise
        await monitor.tick()
        assert monitor.eval_count == 0  # failed tick doesn't count


# ---------------------------------------------------------------------------
# 3. Status reporting
# ---------------------------------------------------------------------------

class TestMonitorStatus:
    @pytest.mark.asyncio
    async def test_get_status(self):
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(
            guardian=guardian, interval_seconds=120
        )
        await monitor.tick()
        status = monitor.get_status()
        assert status["interval_seconds"] == 120
        assert status["eval_count"] == 1
        assert status["last_evaluated_at"] is not None
        assert status["current_state"] in {"HEALTHY", "WARNING", "CAPACITY_RISK", "CRITICAL", "UPGRADE_REQUIRED", "UNKNOWN"}


# ---------------------------------------------------------------------------
# 4. Singleton
# ---------------------------------------------------------------------------

class TestMonitorSingleton:
    def test_get_returns_same_instance(self):
        # Reset global
        import app.control_loop.resource_guardian_monitor as mod
        mod._monitor_instance = None
        m1 = get_resource_guardian_monitor()
        m2 = get_resource_guardian_monitor()
        assert m1 is m2
        mod._monitor_instance = None  # cleanup


# ---------------------------------------------------------------------------
# 5. Configuration
# ---------------------------------------------------------------------------

class TestMonitorConfiguration:
    def test_default_interval(self):
        monitor = ResourceGuardianMonitor()
        assert monitor.interval == 300.0  # 5 minutes default

    def test_custom_interval(self):
        monitor = ResourceGuardianMonitor(interval_seconds=60)
        assert monitor.interval == 60.0

    def test_interval_from_env(self, monkeypatch):
        monkeypatch.setenv("GOALOS_RESOURCE_GUARDIAN_INTERVAL", "120")
        monitor = ResourceGuardianMonitor()
        assert monitor.interval == 120.0

    def test_invalid_env_interval(self, monkeypatch):
        monkeypatch.setenv("GOALOS_RESOURCE_GUARDIAN_INTERVAL", "invalid")
        monitor = ResourceGuardianMonitor()
        assert monitor.interval == 300.0  # falls back to default

    def test_guardian_property(self):
        guardian = _make_healthy_guardian()
        monitor = ResourceGuardianMonitor(guardian=guardian)
        assert monitor.guardian is guardian


# ---------------------------------------------------------------------------
# 6. API integration tests
# ---------------------------------------------------------------------------

class TestGuardianAPIIntegration:
    """Test the Resource Guardian API endpoints via the system router."""

    def test_guardian_endpoint_returns_dict(self):
        """The /api/v1/system/guardian endpoint returns a valid response."""
        from app.api.v1.system import guardian_status
        result = guardian_status()
        assert isinstance(result, dict)
        assert "state" in result
        assert "score" in result

    def test_guardian_alerts_endpoint(self):
        """The /api/v1/system/guardian/alerts endpoint returns a valid response."""
        from app.api.v1.system import guardian_alerts
        result = guardian_alerts()
        assert isinstance(result, dict)
        assert "alerts" in result
        assert "current_state" in result

    def test_guardian_health_endpoint(self):
        """The /api/v1/system/guardian/health endpoint returns a valid response."""
        from app.api.v1.system import guardian_health
        result = guardian_health()
        assert isinstance(result, dict)
        assert "state" in result
        assert "upgrade_required" in result
        assert "score" in result

    def test_guardian_uses_shared_monitor(self):
        """Guardian and system API share the same ResourceMonitor instance."""
        from app.api.v1.system import _monitor, _guardian
        assert _guardian.monitor is _monitor
