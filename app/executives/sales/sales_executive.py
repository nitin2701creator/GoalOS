"""Production-ready sales implementation of the GoalOS executive contract."""

from __future__ import annotations

from typing import Any, Mapping

from app.executives.base_executive import BaseExecutive
from app.executives.executive_models import (
    ExecutiveAlert,
    ExecutivePriority,
    ExecutiveRecommendation,
)
from app.executives.sales.sales_models import SalesKPI, SalesSummary
from app.executives.sales.sales_service import SalesService


class SalesExecutive(BaseExecutive):
    """Own sales reporting and future sales-system integration orchestration."""

    def __init__(self, service: SalesService | None = None) -> None:
        """Create a Sales executive with an injectable local service."""

        super().__init__("Sales", "Owns revenue operations and sales performance.")
        self._service = service or SalesService()

    def initialize(self) -> None:
        """Initialize the local sales service."""

        self._service.initialize()

    def shutdown(self) -> None:
        """Shut down the local sales service."""

        self._service.shutdown()

    def health_check(self) -> bool:
        """Return whether sales reporting is ready to operate."""

        return self._service.health_check()

    def get_summary(self) -> SalesSummary:
        """Return the current sales summary."""

        return self._service.get_summary()

    def get_kpis(self) -> tuple[SalesKPI, ...]:
        """Return current sales KPIs."""

        return self._service.get_kpis()

    def get_alerts(self) -> tuple[ExecutiveAlert, ...]:
        """Return active sales alerts."""

        return self._service.get_alerts()

    def get_priorities(self) -> tuple[ExecutivePriority, ...]:
        """Return ranked sales priorities."""

        return self._service.get_priorities()

    def get_recommendations(self) -> tuple[ExecutiveRecommendation, ...]:
        """Return current sales recommendations."""

        return self._service.get_recommendations()

    def execute(self, action: str, **kwargs: Any) -> Mapping[str, Any]:
        """Execute a safe sales action through the local service."""

        return self._service.execute(action, **kwargs)

    def supported_integrations(self) -> tuple[str, ...]:
        """Return the external systems available through placeholder hooks."""

        return self._service.supported_integrations()
