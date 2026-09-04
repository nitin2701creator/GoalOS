"""Resource Guardian monitoring loop.

Runs as a lightweight background task that periodically evaluates
system capacity and records state transitions. Integrates with the
existing GoalOS scheduler/worker infrastructure without creating
an unmanaged infinite process.

Key properties:
- Configurable polling interval (default: 300s / 5 minutes)
- Non-blocking: runs in a background asyncio task
- Lightweight: one psutil snapshot per cycle
- Deduplicates alerts on state transitions
- Supports hysteresis/recovery (via ResourceGuardian)
- Never modifies infrastructure; advisory only
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.services.resource_guardian import (
    CapacityState,
    ResourceGuardian,
    GuardianThresholds,
)

logger = logging.getLogger(__name__)


class ResourceGuardianMonitor:
    """Background monitor that periodically evaluates system capacity.

    Uses a single asyncio task per process. The monitor is lightweight:
    one psutil snapshot per cycle, with the heavy lifting done by
    ResourceGuardian's state machine and hysteresis logic.
    """

    def __init__(
        self,
        guardian: ResourceGuardian | None = None,
        interval_seconds: float | None = None,
    ) -> None:
        self._guardian = guardian or ResourceGuardian()
        self._interval = interval_seconds or self._get_default_interval()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self.is_running = False
        self.last_evaluated_at: str | None = None
        self.last_assessment: dict[str, Any] | None = None
        self.eval_count = 0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        """Whether monitoring is enabled by configuration."""
        import os
        return os.getenv("GOALOS_RESOURCE_GUARDIAN_ENABLED", "1").strip() not in {"0", "false", "False"}

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def guardian(self) -> ResourceGuardian:
        return self._guardian

    def start(self) -> bool:
        """Start the monitoring loop (idempotent; refuses duplicates in-process)."""
        with self._lock:
            if self._task is not None:
                return False
            if not self.enabled:
                logger.info("resource guardian monitor is disabled by configuration")
                return False
            self._task = asyncio.create_task(self._run())
            self.is_running = True
            logger.info(
                "resource guardian monitor started (interval=%ss)",
                self._interval,
            )
            return True

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        with self._lock:
            task = self._task
            if task is None:
                return
            if self._stop_event is not None:
                self._stop_event.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("resource guardian monitor task cancelled during shutdown")
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "resource guardian monitor task exited during shutdown: %s",
                    exc,
                )
            self._task = None
            self.is_running = False
            logger.info("resource guardian monitor stopped")

    async def _run(self) -> None:
        self._stop_event = asyncio.Event()
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._interval,
                    )
                    break  # stop requested
                except asyncio.TimeoutError:
                    pass
                await self.tick()
        except asyncio.CancelledError:
            pass
        finally:
            self.is_running = False

    async def tick(self) -> None:
        """Run one evaluation cycle (blocking work off the event loop)."""
        self.last_evaluated_at = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        try:
            assessment = await asyncio.to_thread(self._guardian.assess)
            self.last_assessment = self._guardian.to_dict(assessment)
            self.eval_count += 1

            # Log state transitions
            if self.last_assessment.get("evaluation_metadata", {}).get("state_changed"):
                prev = assessment.previous_state
                curr = assessment.state
                logger.info(
                    "Resource Guardian: %s → %s (score=%.2f, reasons=%s)",
                    prev.value if prev else "None",
                    curr.value,
                    assessment.score,
                    "; ".join(assessment.reasons[:3]) if assessment.reasons else "none",
                )

                # Log upgrade recommendation prominently
                if assessment.upgrade_required:
                    logger.warning(
                        "Resource Guardian: UPGRADE REQUIRED — %s",
                        "; ".join(assessment.upgrade_reasons[:3]),
                    )

        except Exception:
            logger.exception("resource guardian evaluation failed")

    def get_status(self) -> dict[str, Any]:
        """Return current monitor status."""
        return {
            "is_running": self.is_running,
            "enabled": self.enabled,
            "interval_seconds": self._interval,
            "eval_count": self.eval_count,
            "last_evaluated_at": self.last_evaluated_at,
            "current_state": (
                self._guardian.current_state.value
                if self._guardian.current_state
                else "UNKNOWN"
            ),
        }

    @staticmethod
    def _get_default_interval() -> float:
        """Read the default interval from environment."""
        import os
        try:
            return float(os.getenv("GOALOS_RESOURCE_GUARDIAN_INTERVAL", "300"))
        except (ValueError, TypeError):
            return 300.0


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_monitor_instance: ResourceGuardianMonitor | None = None
_start_lock = threading.Lock()


def get_resource_guardian_monitor() -> ResourceGuardianMonitor:
    """Return or create the process-wide Resource Guardian monitor."""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ResourceGuardianMonitor()
    return _monitor_instance


def start_resource_guardian_monitor(
    monitor: ResourceGuardianMonitor | None = None,
) -> bool:
    """Start the singleton monitor; returns False when already running."""
    target = monitor or get_resource_guardian_monitor()
    with _start_lock:
        return target.start()


async def stop_resource_guardian_monitor(
    monitor: ResourceGuardianMonitor | None = None,
) -> None:
    """Stop the singleton monitor (called from application shutdown)."""
    target = monitor or get_resource_guardian_monitor()
    await target.stop()
