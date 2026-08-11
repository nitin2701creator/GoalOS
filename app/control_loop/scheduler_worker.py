"""Persisted scheduler worker loop.

The worker runs inside the GoalOS application process and polls the
persisted schedule every ``GOALOS_SCHEDULER_INTERVAL`` seconds, executing
due runs through the SAME :class:`SchedulerService` /
:class:`ExecutionRuntimeService` path as manual execution.

Duplicate-loop safety:

- One loop per process: the module-level singleton refuses a second
  ``start()`` while a task is already running (application restart and
  repeated app instances in the same process never stack loops).
- Multiple processes/workers: each due run is claimed atomically in the
  database (compare-and-set on ``next_run_at``), so only one worker
  executes a given run even when uvicorn runs multiple workers.
- In-flight runs are never re-cloned (the scheduler service refuses while
  a run instance is still pending/running), and the execution runtime has
  its own in-flight guard per workflow.

The worker reports its state through :func:`get_scheduler_worker` so the
health endpoints can surface scheduler readiness honestly.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import RuntimeSettings

logger = logging.getLogger(__name__)

#: A scheduler service factory returns (service, db_session_to_close).
ServiceFactory = Callable[[], tuple[Any, Any]]


class SchedulerWorker:
    """Background loop that executes due persisted schedules."""

    def __init__(
        self,
        settings: RuntimeSettings | None = None,
        service_factory: ServiceFactory | None = None,
    ) -> None:
        self.settings = settings or RuntimeSettings.from_env()
        self._service_factory = service_factory or self._default_service_factory
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None
        self.is_running = False
        self.last_tick_at: str | None = None
        self.last_tick: dict[str, Any] | None = None
        self.tick_count = 0

    @property
    def enabled(self) -> bool:
        """Whether the scheduler is enabled by configuration."""
        return self.settings.scheduler_enabled

    @property
    def interval(self) -> float:
        """Poll interval in seconds."""
        return self.settings.scheduler_interval

    def start(self) -> bool:
        """Start the loop (idempotent; refuses duplicates in-process)."""
        if self._task is not None:
            return False
        if not self.enabled:
            logger.info("scheduler worker is disabled by configuration")
            return False
        self._task = asyncio.create_task(self._run())
        self.is_running = True
        logger.info("scheduler worker started (interval=%ss)", self.interval)
        return True

    async def stop(self) -> None:
        """Stop the loop and await its shutdown."""
        task = self._task
        if task is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.debug("scheduler worker task cancelled during shutdown")
        except Exception as exc:  # noqa: BLE001 - shutdown must always finish
            logger.debug("scheduler worker task exited during shutdown: %s", exc)
        self._task = None
        self.is_running = False
        logger.info("scheduler worker stopped")

    async def _run(self) -> None:
        self._stop_event = asyncio.Event()
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval)
                    break  # stop requested
                except asyncio.TimeoutError:
                    pass
                await self.tick()
        except asyncio.CancelledError:
            pass
        finally:
            self.is_running = False

    async def tick(self) -> None:
        """Run one scheduler poll (blocking work off the event loop)."""
        self.last_tick_at = datetime.now(timezone.utc).isoformat()
        try:
            summary = await asyncio.to_thread(self._run_due)
            self.last_tick = summary
            self.tick_count += 1
        except Exception:
            logger.exception("scheduler tick failed")
            self.last_tick = {"error": "tick failed"}

    def _run_due(self) -> dict[str, Any]:
        service, db = self._service_factory()
        try:
            return service.run_due()
        finally:
            db.close()

    def _default_service_factory(self) -> tuple[Any, Any]:
        """Compose a SchedulerService over the application database session."""
        from app.db.session import SessionLocal
        from app.integrations.factory import build_default_registry
        from app.integrations.scheduler import SchedulerConnector
        from app.llm.provider_factory import ProviderFactory
        from app.repositories.agent_repository import AgentRepository
        from app.repositories.capability_repository import CapabilityRepository
        from app.repositories.runtime_execution_repository import (
            RuntimeExecutionRepository,
        )
        from app.repositories.skill_repository import SkillRepository
        from app.repositories.workflow_repository import WorkflowRepository
        from app.services.agent_factory import AgentFactoryService
        from app.services.capability_service import CapabilityService
        from app.services.execution_runtime import ExecutionRuntimeService
        from app.services.scheduler_service import SchedulerService

        db = SessionLocal()
        provider = None
        try:
            provider = ProviderFactory.create()
        except ValueError:
            provider = None
        capability_service = CapabilityService(
            CapabilityRepository(db),
            integration_registry=build_default_registry(session=db),
            llm_provider=provider,
        )
        workflow_repository = WorkflowRepository(db)
        runtime = ExecutionRuntimeService(
            RuntimeExecutionRepository(db),
            capability_service,
            workflow_repository=workflow_repository,
        )
        agent_factory = AgentFactoryService(AgentRepository(db), SkillRepository(db))
        service = SchedulerService(
            SchedulerConnector(db=db),
            workflow_repository,
            runtime,
            agent_factory,
            claim_horizon=timedelta(seconds=self.settings.scheduler_claim_horizon),
        )
        return service, db


#: Process-wide scheduler worker singleton. One loop per process, guarded
#: by the lock below so restarts cannot stack duplicate loops.
_scheduler_worker = SchedulerWorker()
_start_lock = threading.Lock()


def get_scheduler_worker() -> SchedulerWorker:
    """Return the process-wide scheduler worker (for health/readiness)."""
    return _scheduler_worker


def start_scheduler_worker(worker: SchedulerWorker | None = None) -> bool:
    """Start the singleton worker; returns False when already running."""
    target = worker or _scheduler_worker
    with _start_lock:
        return target.start()


async def stop_scheduler_worker(worker: SchedulerWorker | None = None) -> None:
    """Stop the singleton worker (called from application shutdown)."""
    target = worker or _scheduler_worker
    await target.stop()
