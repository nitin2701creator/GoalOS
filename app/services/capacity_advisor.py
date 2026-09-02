"""GoalOS Capacity Advisor — explainable infrastructure health assessment.

Uses sustained resource measurements from ResourceMonitor to determine:
HEALTHY | WARNING | CAPACITY_RISK | UPGRADE_RECOMMENDED

Never automatically upgrades. Returns explainable reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.resource_monitor import ResourceMonitor


class HealthStatus:
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CAPACITY_RISK = "CAPACITY_RISK"
    UPGRADE_RECOMMENDED = "UPGRADE_RECOMMENDED"


@dataclass(frozen=True, slots=True)
class Thresholds:
    """Configurable thresholds for capacity assessment."""

    ram_warning: float = 70.0
    ram_risk: float = 80.0
    ram_upgrade: float = 85.0

    cpu_warning: float = 70.0
    cpu_risk: float = 80.0
    cpu_upgrade: float = 85.0

    disk_warning: float = 70.0
    disk_risk: float = 80.0
    disk_upgrade: float = 90.0

    swap_warning: float = 5.0
    swap_risk: float = 10.0
    swap_upgrade: float = 15.0

    # Load: upgrade when load_5m exceeds cpu_count * multiplier
    load_warning_multiplier: float = 0.7
    load_risk_multiplier: float = 0.85
    load_upgrade_multiplier: float = 1.0

    min_samples: int = 3  # need at least N samples before upgrading


@dataclass(frozen=True, slots=True)
class CapacityAssessment:
    """Explainable capacity assessment result."""

    status: str  # HealthStatus constant
    reasons: list[str]
    sustained_metrics: dict[str, float]
    current_metrics: dict[str, float]
    recommended_plan: str | None = None
    thresholds_applied: dict[str, Any] = field(default_factory=dict)


def _classify(value: float, warning: float, risk: float, upgrade: float) -> str:
    if value >= upgrade:
        return HealthStatus.UPGRADE_RECOMMENDED
    if value >= risk:
        return HealthStatus.CAPACITY_RISK
    if value >= warning:
        return HealthStatus.WARNING
    return HealthStatus.HEALTHY


def _level_rank(status: str) -> int:
    return {
        HealthStatus.HEALTHY: 0,
        HealthStatus.WARNING: 1,
        HealthStatus.CAPACITY_RISK: 2,
        HealthStatus.UPGRADE_RECOMMENDED: 3,
    }.get(status, 0)


class CapacityAdvisor:
    """Provides explainable capacity assessments from sustained metrics."""

    def __init__(
        self,
        monitor: ResourceMonitor,
        thresholds: Thresholds | None = None,
    ) -> None:
        self.monitor = monitor
        self.thresholds = thresholds or Thresholds()

    def assess(self) -> CapacityAssessment:
        """Run a full capacity assessment."""
        t = self.thresholds
        current = self.monitor.collect()
        sustained = self.monitor.get_sustained_averages()

        reasons: list[str] = []
        worst_status = HealthStatus.HEALTHY

        def _check(
            label: str,
            sustained_val: float,
            current_val: float,
            warning: float,
            risk: float,
            upgrade: float,
        ) -> None:
            nonlocal worst_status
            status = _classify(sustained_val, warning, risk, upgrade)
            if _level_rank(status) > _level_rank(worst_status):
                worst_status = status
            if status == HealthStatus.WARNING:
                reasons.append(
                    f"{label} sustained at {sustained_val:.1f}% "
                    f"(warning threshold: {warning}%)"
                )
            elif status == HealthStatus.CAPACITY_RISK:
                reasons.append(
                    f"{label} sustained at {sustained_val:.1f}% "
                    f"(risk threshold: {risk}%)"
                )
            elif status == HealthStatus.UPGRADE_RECOMMENDED:
                reasons.append(
                    f"{label} sustained at {sustained_val:.1f}% "
                    f"(exceeded upgrade threshold: {upgrade}%)"
                )

        _check("RAM", sustained["ram_percent"], current.ram_percent, t.ram_warning, t.ram_risk, t.ram_upgrade)
        _check("CPU", sustained["cpu_percent"], current.cpu_percent, t.cpu_warning, t.cpu_risk, t.cpu_upgrade)
        _check("Disk", sustained["disk_percent"], current.disk_percent, t.disk_warning, t.disk_risk, t.disk_upgrade)
        _check("Swap", sustained["swap_percent"], current.swap_percent, t.swap_warning, t.swap_risk, t.swap_upgrade)

        # Load average check
        if current.cpu_count > 0:
            load_thresholds = [
                (HealthStatus.WARNING, t.load_warning_multiplier),
                (HealthStatus.CAPACITY_RISK, t.load_risk_multiplier),
                (HealthStatus.UPGRADE_RECOMMENDED, t.load_upgrade_multiplier),
            ]
            for status, mult in load_thresholds:
                threshold = current.cpu_count * mult
                if sustained["load_avg_5m"] >= threshold:
                    reasons.append(
                        f"Load average (5m) at {sustained['load_avg_5m']:.2f} "
                        f"vs {current.cpu_count} CPUs "
                        f"(threshold: {threshold:.2f})"
                    )
                    if _level_rank(status) > _level_rank(worst_status):
                        worst_status = status
                    break

        # GoalOS process health
        if not current.goalos_process_healthy:
            reasons.append("GoalOS process not detected as healthy")
            if _level_rank(HealthStatus.WARNING) > _level_rank(worst_status):
                worst_status = HealthStatus.WARNING

        # Communication workload pressure
        try:
            from app.services.communication_service import get_communication_metrics
            comm_metrics = get_communication_metrics()
            total_comm = comm_metrics["voice_calls_attempted"] + comm_metrics["sms_sent"]
            fail_count = comm_metrics["voice_calls_failed"] + comm_metrics["sms_failed"]
            fallback_count = comm_metrics["fallback_used"]
            if total_comm > 0:
                fail_rate = fail_count / total_comm
                if fail_rate > 0.5 and total_comm >= 5:
                    reasons.append(
                        f"Communication failure rate {fail_rate:.0%} "
                        f"({fail_count}/{total_comm} attempts)"
                    )
                    if _level_rank(HealthStatus.WARNING) > _level_rank(worst_status):
                        worst_status = HealthStatus.WARNING
                if fallback_count > total_comm * 0.3 and total_comm >= 5:
                    reasons.append(
                        f"Communication fallback frequently used "
                        f"({fallback_count}/{total_comm} calls) — "
                        f"primary provider may need attention"
                    )
                    if _level_rank(HealthStatus.WARNING) > _level_rank(worst_status):
                        worst_status = HealthStatus.WARNING
        except Exception:
            pass  # Don't let communication metrics break capacity assessment

        # Minimum samples gate: don't recommend upgrade on insufficient data
        if (
            worst_status == HealthStatus.UPGRADE_RECOMMENDED
            and sustained["sample_count"] < t.min_samples
        ):
            worst_status = HealthStatus.CAPACITY_RISK
            reasons.append(
                f"Insufficient samples ({sustained['sample_count']}) "
                f"for upgrade recommendation (need {t.min_samples})"
            )

        recommended_plan = None
        if worst_status == HealthStatus.UPGRADE_RECOMMENDED:
            recommended_plan = self._recommend_plan(current, sustained)

        return CapacityAssessment(
            status=worst_status,
            reasons=reasons,
            sustained_metrics=sustained,
            current_metrics=self.monitor.to_dict(current),
            recommended_plan=recommended_plan,
            thresholds_applied={
                "ram_warning": t.ram_warning,
                "ram_risk": t.ram_risk,
                "ram_upgrade": t.ram_upgrade,
                "cpu_warning": t.cpu_warning,
                "cpu_risk": t.cpu_risk,
                "cpu_upgrade": t.cpu_upgrade,
                "disk_warning": t.disk_warning,
                "disk_risk": t.disk_risk,
                "disk_upgrade": t.disk_upgrade,
                "swap_warning": t.swap_warning,
                "swap_risk": t.swap_risk,
                "swap_upgrade": t.swap_upgrade,
                "min_samples": t.min_samples,
            },
        )

    def _recommend_plan(
        self, current: Any, sustained: dict[str, float]
    ) -> str:
        """Heuristic plan recommendation based on bottleneck."""
        if sustained.get("ram_percent", 0) >= self.thresholds.ram_upgrade:
            return "KVM 4 (recommended: upgrade RAM)"
        if sustained.get("cpu_percent", 0) >= self.thresholds.cpu_upgrade:
            return "KVM 4 (recommended: upgrade CPU)"
        if sustained.get("disk_percent", 0) >= self.thresholds.disk_upgrade:
            return "KVM 4 (recommended: expand disk)"
        return "KVM 4"
