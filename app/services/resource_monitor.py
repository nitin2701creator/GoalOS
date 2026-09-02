"""GoalOS Resource Monitor — lightweight system metrics collection.

Collects CPU, RAM, swap, disk, load average, process count, and
GoalOS process health. All metrics are normalized to [0, 1] or
percentage ranges. Uses psutil for cross-platform metrics.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


def _available() -> bool:
    return psutil is not None


@dataclass(frozen=True, slots=True)
class SystemMetrics:
    """Normalized system metrics snapshot."""

    cpu_percent: float  # 0-100
    ram_percent: float  # 0-100
    swap_percent: float  # 0-100
    disk_percent: float  # 0-100
    load_avg_1m: float  # raw
    load_avg_5m: float
    load_avg_15m: float
    cpu_count: int  # logical CPUs
    ram_total_gb: float
    ram_used_gb: float
    swap_total_gb: float
    swap_used_gb: float
    disk_total_gb: float
    disk_used_gb: float
    process_count: int
    goalos_process_healthy: bool
    timestamp: float  # time.time()


@dataclass(slots=True)
class ResourceHistory:
    """Rolling window of metrics for sustained-measurement analysis."""

    window_seconds: int = 600  # 10 minutes default
    samples: list[SystemMetrics] = field(default_factory=list)

    def add(self, metrics: SystemMetrics) -> None:
        cutoff = metrics.timestamp - self.window_seconds
        self.samples = [s for s in self.samples if s.timestamp >= cutoff]
        self.samples.append(metrics)

    def average(self, attr: str) -> float:
        if not self.samples:
            return 0.0
        values = [getattr(s, attr) for s in self.samples]
        return sum(values) / len(values)


class ResourceMonitor:
    """Collects and returns normalized system metrics."""

    def __init__(self) -> None:
        self._history = ResourceHistory()
        self._last_metrics: SystemMetrics | None = None

    @property
    def available(self) -> bool:
        return _available()

    def collect(self) -> SystemMetrics:
        """Collect a fresh snapshot of system metrics."""
        if not self.available:
            return self._fallback_metrics()

        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        load = os.getloadavg()
        cpu_count = psutil.cpu_count(logical=True) or 1
        proc_count = len(psutil.pids())

        goalos_healthy = self._check_goalos_health()

        metrics = SystemMetrics(
            cpu_percent=cpu,
            ram_percent=ram.percent,
            swap_percent=swap.percent if swap.total > 0 else 0.0,
            disk_percent=disk.percent,
            load_avg_1m=load[0],
            load_avg_5m=load[1],
            load_avg_15m=load[2],
            cpu_count=cpu_count,
            ram_total_gb=round(ram.total / (1024**3), 2),
            ram_used_gb=round(ram.used / (1024**3), 2),
            swap_total_gb=round(swap.total / (1024**3), 2),
            swap_used_gb=round(swap.used / (1024**3), 2),
            disk_total_gb=round(disk.total / (1024**3), 2),
            disk_used_gb=round(disk.used / (1024**3), 2),
            process_count=proc_count,
            goalos_process_healthy=goalos_healthy,
            timestamp=time.time(),
        )
        self._history.add(metrics)
        self._last_metrics = metrics
        return metrics

    def get_history(self) -> ResourceHistory:
        return self._history

    def get_sustained_averages(self) -> dict[str, float]:
        """Return sustained (windowed average) metrics for capacity analysis."""
        h = self._history
        return {
            "cpu_percent": h.average("cpu_percent"),
            "ram_percent": h.average("ram_percent"),
            "swap_percent": h.average("swap_percent"),
            "disk_percent": h.average("disk_percent"),
            "load_avg_1m": h.average("load_avg_1m"),
            "load_avg_5m": h.average("load_avg_5m"),
            "load_avg_15m": h.average("load_avg_15m"),
            "sample_count": len(h.samples),
        }

    def _check_goalos_health(self) -> bool:
        """Check if the GoalOS process is running and responsive."""
        goalos_pid = os.getenv("GOALOS_PID")
        if goalos_pid:
            try:
                proc = psutil.Process(int(goalos_pid))
                return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, ValueError):
                return False
        # Heuristic: check if uvicorn/fastapi is running
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if "goalos" in cmdline.lower() or "uvicorn" in cmdline.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False

    @staticmethod
    def _fallback_metrics() -> SystemMetrics:
        """Return empty metrics when psutil is not available."""
        return SystemMetrics(
            cpu_percent=0.0,
            ram_percent=0.0,
            swap_percent=0.0,
            disk_percent=0.0,
            load_avg_1m=0.0,
            load_avg_5m=0.0,
            load_avg_15m=0.0,
            cpu_count=1,
            ram_total_gb=0.0,
            ram_used_gb=0.0,
            swap_total_gb=0.0,
            swap_used_gb=0.0,
            disk_total_gb=0.0,
            disk_used_gb=0.0,
            process_count=0,
            goalos_process_healthy=False,
            timestamp=time.time(),
        )

    def to_dict(self, metrics: SystemMetrics | None = None) -> dict[str, Any]:
        m = metrics or self._last_metrics or self.collect()
        return {
            "cpu_percent": m.cpu_percent,
            "ram_percent": m.ram_percent,
            "swap_percent": m.swap_percent,
            "disk_percent": m.disk_percent,
            "load_avg_1m": m.load_avg_1m,
            "load_avg_5m": m.load_avg_5m,
            "load_avg_15m": m.load_avg_15m,
            "cpu_count": m.cpu_count,
            "ram_total_gb": m.ram_total_gb,
            "ram_used_gb": m.ram_used_gb,
            "swap_total_gb": m.swap_total_gb,
            "swap_used_gb": m.swap_used_gb,
            "disk_total_gb": m.disk_total_gb,
            "disk_used_gb": m.disk_used_gb,
            "process_count": m.process_count,
            "goalos_process_healthy": m.goalos_process_healthy,
            "timestamp": m.timestamp,
        }
