"""Validated, sales-specific data structures for the Sales executive."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.executives.executive_models import ExecutiveKPI, ExecutiveSummary


class SalesKPI(ExecutiveKPI):
    """A KPI reported by the sales organization."""

    category: str = Field(default="revenue", min_length=1)
    period: str = Field(default="current", min_length=1)


class SalesSummary(ExecutiveSummary):
    """A concise snapshot of the current sales operation."""

    total_revenue: float = Field(default=0.0, ge=0)
    revenue_target: float = Field(default=0.0, ge=0)
    pipeline_value: float = Field(default=0.0, ge=0)
    open_deals: int = Field(default=0, ge=0)
    win_rate: float = Field(default=0.0, ge=0, le=1)


class SalesIntegrationHook(ExecutiveSummary):
    """Metadata for an intentionally inactive sales integration hook."""

    integration: Literal["woocommerce", "twenty_crm", "email"]
    configured: bool = False
    status: Literal["not_configured"] = "not_configured"
