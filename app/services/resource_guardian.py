"""GoalOS Resource Guardian — production-quality capacity monitoring.

Extends the existing ResourceMonitor and CapacityAdvisor with:
- Typed capacity state machine (HEALTHY → WARNING → CAPACITY_RISK → CRITICAL → UPGRADE_REQUIRED)
- Multi-signal smart decision engine
- Hysteresis/recovery thresholds to prevent state flapping
- Container/Docker awareness (optional, non-fatal)
- Service health checking
- Alert deduplication and state transitions
- Structured upgrade recommendations

Resource Guardian is advisory only. It never modifies infrastructure.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.services.resource_monitor import ResourceMonitor, SystemMetrics

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Capacity states
# ---------------------------------------------------------------------------

class CapacityState(str, Enum):
    """Typed capacity states with ordering semantics."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CAPACITY_RISK = "CAPACITY_RISK"
    CRITICAL = "CRITICAL"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"

    @property
    def rank(self) -> int:
        return {
            CapacityState.HEALTHY: 0,
            CapacityState.WARNING: 1,
            CapacityState.CAPACITY_RISK: 2,
            CapacityState.CRITICAL: 3,
            CapacityState.UPGRADE_REQUIRED: 4,
        }[self]

    def is_worse_than(self, other: CapacityState) -> bool:
        return self.rank > other.rank

    def is_better_than(self, other: CapacityState) -> bool:
        return self.rank < other.rank


# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GuardianThresholds:
    """All configurable thresholds for the Resource Guardian."""

    # Warning thresholds
    ram_warning: float = 70.0
    cpu_warning: float = 70.0
    disk_warning: float = 70.0
    swap_warning: float = 5.0

    # Capacity risk thresholds
    ram_risk: float = 80.0
    cpu_risk: float = 80.0
    disk_risk: float = 80.0
    swap_risk: float = 10.0

    # Critical thresholds
    ram_critical: float = 90.0
    cpu_critical: float = 90.0
    disk_critical: float = 95.0
    swap_critical: float = 25.0

    # Upgrade required thresholds
    ram_upgrade: float = 95.0
    cpu_upgrade: float = 95.0
    disk_upgrade: float = 98.0
    swap_upgrade: float = 50.0

    # Load average multipliers (relative to CPU count)
    load_warning_multiplier: float = 0.7
    load_risk_multiplier: float = 0.85
    load_critical_multiplier: float = 1.0
    load_upgrade_multiplier: float = 1.2

    # Minimum samples before UPGRADE_REQUIRED (prevents single-spike upgrades)
    min_samples_for_upgrade: int = 3

    # Hysteresis: recovery thresholds (drop below these to recover)
    recovery_drop_percent: float = 5.0

    # Evaluation window for sustained observations
    evaluation_window_seconds: int = 600  # 10 minutes

    # Available RAM thresholds (GB)
    ram_available_warning_gb: float = 1.0
    ram_available_critical_gb: float = 0.5


# ---------------------------------------------------------------------------
# Assessment result
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class GuardianAssessment:
    """Full assessment result from the Resource Guardian."""

    state: CapacityState
    previous_state: CapacityState | None
    reasons: list[str]
    affected_resources: list[str]
    current_metrics: dict[str, Any]
    sustained_metrics: dict[str, Any]
    score: float  # 0.0 (healthy) to 1.0 (critical)
    headroom: dict[str, float]  # remaining capacity per resource
    recommended_action: str | None
    confidence: float  # 0.0 to 1.0
    upgrade_required: bool
    upgrade_reasons: list[str]
    timestamp: float
    evaluation_metadata: dict[str, Any]
    active_warnings: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Alert record
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CapacityAlert:
    """A deduplicated capacity alert."""

    alert_type: str  # resource_capacity_warning, resource_capacity_risk, etc.
    state: CapacityState
    message: str
    timestamp: float
    acknowledged: bool = False


# ---------------------------------------------------------------------------
# Container info
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ContainerInfo:
    """Optional container resource information."""

    name: str
    status: str  # running, exited, etc.
    cpu_percent: float | None = None
    memory_mb: float | None = None
    memory_limit_mb: float | None = None


# ---------------------------------------------------------------------------
# Resource Guardian
# ---------------------------------------------------------------------------

class ResourceGuardian:
    """Production-quality capacity monitoring with state machine and hysteresis.

    Uses the existing ResourceMonitor for metrics collection and adds:
    - State machine with transitions
    - Multi-signal decision engine
    - Hysteresis to prevent flapping
    - Container awareness
    - Alert deduplication
    - Upgrade recommendations
    """

    def __init__(
        self,
        monitor: ResourceMonitor | None = None,
        thresholds: GuardianThresholds | None = None,
    ) -> None:
        self._monitor = monitor or ResourceMonitor()
        self._thresholds = thresholds or GuardianThresholds()
        self._current_state: CapacityState | None = None
        self._previous_state: CapacityState | None = None
        self._last_assessment: GuardianAssessment | None = None
        self._alerts: list[CapacityAlert] = []
        self._alert_dedup_key: str | None = None
        self._state_entered_at: float | None = None
        self._consecutive_critical: int = 0

    @property
    def current_state(self) -> CapacityState | None:
        return self._current_state

    @property
    def monitor(self) -> ResourceMonitor:
        return self._monitor

    @property
    def thresholds(self) -> GuardianThresholds:
        return self._thresholds

    def assess(self) -> GuardianAssessment:
        """Run a full capacity assessment and update state."""
        t = self._thresholds
        current = self._monitor.collect()
        sustained = self._monitor.get_sustained_averages()

        reasons: list[str] = []
        affected_resources: list[str] = []
        upgrade_reasons: list[str] = []
        score_components: list[float] = []

        # --- RAM analysis ---
        ram_status = self._classify_ram(sustained, current, t)
        ram_score = self._score_ram(sustained, current, t)
        score_components.append(ram_score)
        if ram_status != CapacityState.HEALTHY:
            affected_resources.append("RAM")
            if ram_status.rank >= CapacityState.WARNING.rank:
                reasons.append(
                    f"RAM sustained at {sustained['ram_percent']:.1f}% "
                    f"(available: {current.ram_total_gb - current.ram_used_gb:.1f} GB)"
                )
            if ram_status == CapacityState.UPGRADE_REQUIRED:
                upgrade_reasons.append(
                    f"RAM at {sustained['ram_percent']:.1f}% — "
                    f"only {current.ram_total_gb - current.ram_used_gb:.1f} GB available "
                    f"of {current.ram_total_gb:.1f} GB total"
                )

        # --- Swap analysis ---
        swap_status = self._classify_swap(sustained, current, t)
        swap_score = self._score_swap(sustained, t)
        score_components.append(swap_score)
        if swap_status != CapacityState.HEALTHY:
            affected_resources.append("Swap")
            if swap_status.rank >= CapacityState.WARNING.rank:
                reasons.append(
                    f"Swap at {sustained['swap_percent']:.1f}% — "
                    f"memory pressure may cause OOM kills"
                )
            if swap_status == CapacityState.UPGRADE_REQUIRED:
                upgrade_reasons.append(
                    f"Swap at {sustained['swap_percent']:.1f}% — "
                    f"insufficient virtual memory"
                )

        # --- CPU analysis ---
        cpu_status = self._classify_cpu(sustained, current, t)
        cpu_score = self._score_cpu(sustained, current, t)
        score_components.append(cpu_score)
        if cpu_status != CapacityState.HEALTHY:
            affected_resources.append("CPU")
            if cpu_status.rank >= CapacityState.WARNING.rank:
                reasons.append(
                    f"CPU sustained at {sustained['cpu_percent']:.1f}% "
                    f"(load 5m: {sustained['load_avg_5m']:.2f} / {current.cpu_count} cores)"
                )
            if cpu_status == CapacityState.UPGRADE_REQUIRED:
                upgrade_reasons.append(
                    f"CPU at {sustained['cpu_percent']:.1f}% — "
                    f"load average {sustained['load_avg_5m']:.2f} exceeds {current.cpu_count} cores"
                )

        # --- Disk analysis ---
        disk_status = self._classify_disk(sustained, current, t)
        disk_score = self._score_disk(sustained, t)
        score_components.append(disk_score)
        if disk_status != CapacityState.HEALTHY:
            affected_resources.append("Disk")
            if disk_status.rank >= CapacityState.WARNING.rank:
                reasons.append(
                    f"Disk at {sustained['disk_percent']:.1f}% "
                    f"({current.disk_total_gb - current.disk_used_gb:.1f} GB free)"
                )
            if disk_status == CapacityState.UPGRADE_REQUIRED:
                upgrade_reasons.append(
                    f"Disk at {sustained['disk_percent']:.1f}% — "
                    f"only {current.disk_total_gb - current.disk_used_gb:.1f} GB free"
                )

        # --- GoalOS process health ---
        if not current.goalos_process_healthy:
            affected_resources.append("Service")
            reasons.append("GoalOS process not detected as healthy")
            score_components.append(0.3)

        # --- Container awareness (optional, non-fatal) ---
        container_warnings = self._check_containers()
        if container_warnings:
            affected_resources.append("Containers")
            reasons.extend(container_warnings)

        # --- Determine worst state ---
        worst = CapacityState.HEALTHY
        for status in [ram_status, swap_status, cpu_status, disk_status]:
            if status.is_worse_than(worst):
                worst = status

        if not current.goalos_process_healthy:
            if CapacityState.WARNING.is_worse_than(worst):
                worst = CapacityState.WARNING

        # --- Minimum samples gate for upgrade ---
        # Individual classifiers may return UPGRADE_REQUIRED, but we need
        # sufficient samples before confirming upgrade. Downgrade to CRITICAL
        # if samples are insufficient.
        sample_count = sustained.get("sample_count", 0)
        if worst == CapacityState.UPGRADE_REQUIRED and sample_count < t.min_samples_for_upgrade:
            worst = CapacityState.CRITICAL
            reasons.append(
                f"Insufficient samples ({sample_count}) for upgrade recommendation "
                f"(need {t.min_samples_for_upgrade})"
            )

        # --- Track consecutive critical (for upgrade confirmation) ---
        # Only CRITICAL (not UPGRADE_REQUIRED) counts toward consecutive evaluations.
        # UPGRADE_REQUIRED from classifiers already means all thresholds exceeded.
        if worst == CapacityState.CRITICAL:
            self._consecutive_critical += 1
            if self._consecutive_critical >= t.min_samples_for_upgrade:
                worst = CapacityState.UPGRADE_REQUIRED
                reasons.append(
                    f"Sustained critical capacity for {self._consecutive_critical} evaluations"
                )
        elif worst == CapacityState.UPGRADE_REQUIRED:
            # Already UPGRADE_REQUIRED from classifiers (enough samples confirmed by gate)
            self._consecutive_critical = 0
        else:
            self._consecutive_critical = 0

        # --- Hysteresis: prevent state flapping ---
        if self._current_state is not None and worst.is_better_than(self._current_state):
            # Recovery: only allow dropping by one level at a time
            recovery_state = CapacityState(
                list(CapacityState)[self._current_state.rank - 1]
            )
            if worst.is_better_than(recovery_state):
                worst = recovery_state
                reasons.append(
                    f"Hysteresis: recovering from {self._current_state.value} "
                    f"to {worst.value} (gradual recovery)"
                )

        # --- Compute composite score ---
        avg_score = sum(score_components) / len(score_components) if score_components else 0.0
        # Weighted by worst state
        state_weight = worst.rank / 4.0
        score = max(avg_score, state_weight)

        # --- Compute headroom ---
        headroom = {
            "ram_percent": max(0.0, 100.0 - current.ram_percent),
            "cpu_percent": max(0.0, 100.0 - current.cpu_percent),
            "disk_percent": max(0.0, 100.0 - current.disk_percent),
            "swap_percent": max(0.0, 100.0 - current.swap_percent),
            "ram_available_gb": max(0.0, current.ram_total_gb - current.ram_used_gb),
            "disk_free_gb": max(0.0, current.disk_total_gb - current.disk_used_gb),
        }

        # --- Recommended action ---
        recommended_action = None
        if worst == CapacityState.UPGRADE_REQUIRED:
            recommended_action = self._recommend_upgrade(current, sustained, upgrade_reasons)
        elif worst == CapacityState.CRITICAL:
            recommended_action = (
                "Immediate attention required. Consider reducing workload or "
                "preparing for infrastructure upgrade."
            )
        elif worst == CapacityState.CAPACITY_RISK:
            recommended_action = (
                "Monitor closely. Consider optimizing resource usage or "
                "planning capacity expansion."
            )

        # --- Build active warnings ---
        active_warnings = self._build_warnings(worst, reasons, affected_resources)

        # --- Confidence ---
        confidence = min(1.0, sample_count / max(t.min_samples_for_upgrade, 1))

        # --- State transition ---
        previous = self._current_state
        if worst != self._current_state:
            self._previous_state = self._current_state
            self._current_state = worst
            self._state_entered_at = time.time()
            logger.info(
                "Resource Guardian state transition: %s → %s (reasons: %s)",
                previous.value if previous else "None",
                worst.value,
                "; ".join(reasons[:3]),
            )
            # Record alert on transition
            self._record_alert(worst, reasons)

        # --- Evaluation metadata ---
        evaluation_metadata = {
            "sample_count": sample_count,
            "consecutive_critical": self._consecutive_critical,
            "min_samples_for_upgrade": t.min_samples_for_upgrade,
            "evaluation_window_seconds": t.evaluation_window_seconds,
            "state_changed": worst != previous,
            "previous_state": previous.value if previous else None,
            "state_duration_seconds": (
                time.time() - self._state_entered_at
                if self._state_entered_at
                else 0.0
            ),
        }

        assessment = GuardianAssessment(
            state=worst,
            previous_state=previous,
            reasons=reasons,
            affected_resources=affected_resources,
            current_metrics=self._monitor.to_dict(current),
            sustained_metrics=sustained,
            score=round(score, 3),
            headroom=headroom,
            recommended_action=recommended_action,
            confidence=round(confidence, 3),
            upgrade_required=worst == CapacityState.UPGRADE_REQUIRED,
            upgrade_reasons=upgrade_reasons,
            timestamp=time.time(),
            evaluation_metadata=evaluation_metadata,
            active_warnings=active_warnings,
        )
        self._last_assessment = assessment
        return assessment

    # --- Classification helpers ---

    def _classify_ram(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> CapacityState:
        val = sustained["ram_percent"]
        available_gb = current.ram_total_gb - current.ram_used_gb

        # Check absolute available RAM first
        if available_gb <= t.ram_available_critical_gb:
            return CapacityState.CRITICAL
        if available_gb <= t.ram_available_warning_gb:
            if val >= t.ram_risk:
                return CapacityState.CAPACITY_RISK
            return CapacityState.WARNING

        return self._classify(val, t.ram_warning, t.ram_risk, t.ram_critical, t.ram_upgrade)

    def _classify_swap(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> CapacityState:
        val = sustained["swap_percent"]
        if current.swap_total_gb == 0:
            # No swap configured — risk if RAM is high
            if sustained["ram_percent"] >= t.ram_critical:
                return CapacityState.CAPACITY_RISK
            return CapacityState.HEALTHY
        return self._classify(val, t.swap_warning, t.swap_risk, t.swap_critical, t.swap_upgrade)

    def _classify_cpu(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> CapacityState:
        val = sustained["cpu_percent"]

        # Also consider load average
        if current.cpu_count > 0:
            load = sustained["load_avg_5m"]
            load_upgrade_thresh = current.cpu_count * t.load_upgrade_multiplier
            load_critical_thresh = current.cpu_count * t.load_critical_multiplier
            load_risk_thresh = current.cpu_count * t.load_risk_multiplier
            load_warning_thresh = current.cpu_count * t.load_warning_multiplier

            if load >= load_upgrade_thresh:
                return CapacityState.UPGRADE_REQUIRED
            if load >= load_critical_thresh:
                return max(
                    CapacityState.CRITICAL,
                    self._classify(val, t.cpu_warning, t.cpu_risk, t.cpu_critical, t.cpu_upgrade),
                    key=lambda s: s.rank,
                )
            if load >= load_risk_thresh:
                return max(
                    CapacityState.CAPACITY_RISK,
                    self._classify(val, t.cpu_warning, t.cpu_risk, t.cpu_critical, t.cpu_upgrade),
                    key=lambda s: s.rank,
                )
            if load >= load_warning_thresh:
                return max(
                    CapacityState.WARNING,
                    self._classify(val, t.cpu_warning, t.cpu_risk, t.cpu_critical, t.cpu_upgrade),
                    key=lambda s: s.rank,
                )

        return self._classify(val, t.cpu_warning, t.cpu_risk, t.cpu_critical, t.cpu_upgrade)

    def _classify_disk(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> CapacityState:
        val = sustained["disk_percent"]
        free_gb = current.disk_total_gb - current.disk_used_gb

        # Critical disk space
        if free_gb < 1.0:
            return CapacityState.CRITICAL
        if free_gb < 5.0 and val >= t.disk_risk:
            return CapacityState.CAPACITY_RISK

        return self._classify(val, t.disk_warning, t.disk_risk, t.disk_critical, t.disk_upgrade)

    @staticmethod
    def _classify(
        value: float,
        warning: float,
        risk: float,
        critical: float,
        upgrade: float,
    ) -> CapacityState:
        if value >= upgrade:
            return CapacityState.UPGRADE_REQUIRED
        if value >= critical:
            return CapacityState.CRITICAL
        if value >= risk:
            return CapacityState.CAPACITY_RISK
        if value >= warning:
            return CapacityState.WARNING
        return CapacityState.HEALTHY

    # --- Scoring helpers ---

    def _score_ram(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> float:
        val = sustained["ram_percent"]
        if val >= t.ram_upgrade:
            return 1.0
        if val >= t.ram_critical:
            return 0.9
        if val >= t.ram_risk:
            return 0.7
        if val >= t.ram_warning:
            return 0.4
        return val / 100.0 * 0.3

    def _score_swap(
        self,
        sustained: dict[str, float],
        t: GuardianThresholds,
    ) -> float:
        val = sustained["swap_percent"]
        if val >= t.swap_upgrade:
            return 1.0
        if val >= t.swap_critical:
            return 0.9
        if val >= t.swap_risk:
            return 0.7
        if val >= t.swap_warning:
            return 0.4
        return val / 100.0 * 0.2

    def _score_cpu(
        self,
        sustained: dict[str, float],
        current: SystemMetrics,
        t: GuardianThresholds,
    ) -> float:
        val = sustained["cpu_percent"]
        if val >= t.cpu_upgrade:
            return 1.0
        if val >= t.cpu_critical:
            return 0.9
        if val >= t.cpu_risk:
            return 0.7
        if val >= t.cpu_warning:
            return 0.4
        return val / 100.0 * 0.3

    def _score_disk(
        self,
        sustained: dict[str, float],
        t: GuardianThresholds,
    ) -> float:
        val = sustained["disk_percent"]
        if val >= t.disk_upgrade:
            return 1.0
        if val >= t.disk_critical:
            return 0.9
        if val >= t.disk_risk:
            return 0.7
        if val >= t.disk_warning:
            return 0.4
        return val / 100.0 * 0.3

    # --- Container awareness ---

    def _check_containers(self) -> list[str]:
        """Check Docker container status if Docker is available. Non-fatal."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}|{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return []

            warnings: list[str] = []
            for line in result.stdout.strip().splitlines():
                if not line.strip():
                    continue
                parts = line.split("|", 1)
                name = parts[0].strip()
                status = parts[1].strip() if len(parts) > 1 else "unknown"

                # Detect unhealthy containers
                if "unhealthy" in status.lower():
                    warnings.append(f"Container '{name}' is unhealthy: {status}")
                elif "restarting" in status.lower():
                    warnings.append(f"Container '{name}' is restarting: {status}")

            return warnings
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            # Docker not available or not installed — this is fine
            return []

    # --- Alert management ---

    def _record_alert(self, state: CapacityState, reasons: list[str]) -> None:
        """Record a deduplicated alert on state transition."""
        alert_type_map = {
            CapacityState.WARNING: "resource_capacity_warning",
            CapacityState.CAPACITY_RISK: "resource_capacity_risk",
            CapacityState.CRITICAL: "resource_critical",
            CapacityState.UPGRADE_REQUIRED: "resource_upgrade_required",
        }
        alert_type = alert_type_map.get(state)
        if alert_type is None:
            # HEALTHY — record recovery if we were previously elevated
            if self._previous_state is not None and self._previous_state != CapacityState.HEALTHY:
                self._alerts.append(CapacityAlert(
                    alert_type="resource_capacity_recovered",
                    state=CapacityState.HEALTHY,
                    message=f"Capacity recovered from {self._previous_state.value} to HEALTHY",
                    timestamp=time.time(),
                ))
            return

        dedup_key = f"{alert_type}:{state.value}"
        if dedup_key == self._alert_dedup_key:
            return  # Same alert, don't duplicate

        self._alert_dedup_key = dedup_key
        self._alerts.append(CapacityAlert(
            alert_type=alert_type,
            state=state,
            message="; ".join(reasons) if reasons else f"Capacity state: {state.value}",
            timestamp=time.time(),
        ))

    def get_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent capacity alerts."""
        alerts = self._alerts[-limit:]
        return [
            {
                "alert_type": a.alert_type,
                "state": a.state.value,
                "message": a.message,
                "timestamp": a.timestamp,
                "acknowledged": a.acknowledged,
            }
            for a in alerts
        ]

    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False

    # --- Upgrade recommendation ---

    def _recommend_upgrade(
        self,
        current: SystemMetrics,
        sustained: dict[str, float],
        upgrade_reasons: list[str],
    ) -> str:
        """Generate a structured upgrade recommendation."""
        lines = [
            "Infrastructure upgrade recommended.",
            "",
            "Primary reasons:",
        ]
        for reason in upgrade_reasons:
            lines.append(f"  - {reason}")

        lines.append("")
        lines.append("Current capacity:")
        lines.append(f"  - RAM: {current.ram_total_gb:.1f} GB total, "
                      f"{current.ram_used_gb:.1f} GB used, "
                      f"{current.ram_total_gb - current.ram_used_gb:.1f} GB available")
        lines.append(f"  - CPU: {current.cpu_count} cores, "
                      f"load 5m: {sustained.get('load_avg_5m', 0):.2f}")
        lines.append(f"  - Disk: {current.disk_total_gb:.1f} GB total, "
                      f"{current.disk_total_gb - current.disk_used_gb:.1f} GB free")
        if current.swap_total_gb > 0:
            lines.append(f"  - Swap: {current.swap_total_gb:.1f} GB total, "
                          f"{current.swap_used_gb:.1f} GB used")

        lines.append("")
        lines.append("Impact:")
        lines.append("  - Additional workloads may destabilize the system")
        lines.append("  - Resource-intensive operations should be limited")
        lines.append("")
        lines.append("Recommendation:")
        lines.append("  - Increase resources to the next suitable tier")
        lines.append("  - Reassess after upgrade")

        return "\n".join(lines)

    def _build_warnings(
        self,
        state: CapacityState,
        reasons: list[str],
        affected_resources: list[str],
    ) -> list[dict[str, Any]]:
        """Build active warning list."""
        if state == CapacityState.HEALTHY:
            return []
        return [
            {
                "state": state.value,
                "resources": affected_resources,
                "reasons": reasons,
                "timestamp": time.time(),
            }
        ]

    # --- Serialization ---

    def to_dict(self, assessment: GuardianAssessment | None = None) -> dict[str, Any]:
        """Serialize the current state to a dict for API responses."""
        a = assessment or self._last_assessment
        if a is None:
            return {"state": "UNKNOWN", "message": "No assessment has been run yet"}

        return {
            "state": a.state.value,
            "previous_state": a.previous_state.value if a.previous_state else None,
            "score": a.score,
            "reasons": a.reasons,
            "affected_resources": a.affected_resources,
            "headroom": a.headroom,
            "recommended_action": a.recommended_action,
            "confidence": a.confidence,
            "upgrade_required": a.upgrade_required,
            "upgrade_reasons": a.upgrade_reasons,
            "active_warnings": a.active_warnings,
            "current_metrics": a.current_metrics,
            "sustained_metrics": a.sustained_metrics,
            "timestamp": a.timestamp,
            "evaluation_metadata": a.evaluation_metadata,
            "alerts": self.get_alerts(limit=10),
        }
