"""Tests for the production Sales executive."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.executives import BaseExecutive, ExecutiveLoader
from app.executives.sales import (
    SalesExecutive,
    SalesIntegrationHook,
    SalesKPI,
    SalesSummary,
)
from app.executives.sales.sales_service import SalesService


def test_sales_executive_implements_runtime_lifecycle_and_reporting() -> None:
    """SalesExecutive satisfies the shared contract with typed sales responses."""

    executive = SalesExecutive()

    assert isinstance(executive, BaseExecutive)
    assert not executive.health_check()
    executive.initialize()
    assert executive.health_check()

    summary = executive.get_summary()
    assert isinstance(summary, SalesSummary)
    assert summary.executive_name == "Sales"
    assert summary.status == "ready"
    assert summary.total_revenue == 0.0
    assert all(isinstance(kpi, SalesKPI) for kpi in executive.get_kpis())
    assert executive.get_alerts() == ()
    assert executive.get_priorities() == ()
    assert executive.get_recommendations() == ()

    executive.shutdown()
    assert not executive.health_check()


def test_sales_models_validate_sales_metric_bounds() -> None:
    """Sales models inherit runtime validation and reject invalid business values."""

    kpi = SalesKPI(title="Revenue", category=" revenue ", period=" monthly ")
    summary = SalesSummary(executive_name=" Sales ", title=" Snapshot ", win_rate=1)

    assert kpi.category == "revenue"
    assert kpi.period == "monthly"
    assert summary.executive_name == "Sales"
    with pytest.raises(ValidationError):
        SalesSummary(executive_name="Sales", title="Snapshot", total_revenue=-1)
    with pytest.raises(ValidationError):
        SalesSummary(executive_name="Sales", title="Snapshot", win_rate=1.1)


def test_sales_integration_hooks_are_explicit_and_do_not_connect() -> None:
    """Integration placeholders expose stable metadata without provider clients."""

    service = SalesService()

    assert service.supported_integrations() == ("woocommerce", "twenty_crm", "email")
    assert tuple(service.integration_hooks) == service.supported_integrations()
    for integration in service.supported_integrations():
        hook = service.get_integration_hook(integration)
        assert isinstance(hook, SalesIntegrationHook)
        assert hook.integration == integration
        assert not hook.configured
        assert hook.status == "not_configured"
    with pytest.raises(LookupError, match="not supported"):
        service.get_integration_hook("stripe")


def test_sales_actions_are_safe_and_delegated_to_the_service() -> None:
    """The refresh seam remains a no-op and reporting actions return typed data."""

    executive = SalesExecutive()

    refresh = executive.execute(" refresh ")
    summary = executive.execute("summary")
    assert refresh["status"] == "accepted"
    assert "no external API call" in refresh["message"]
    assert isinstance(summary["result"], SalesSummary)
    with pytest.raises(ValueError, match="unsupported sales action"):
        executive.execute("delete")
    with pytest.raises(ValueError, match="unsupported action arguments"):
        executive.execute("refresh", force=True)


def test_loader_discovers_and_initializes_sales_executive() -> None:
    """The Sprint 10.1 loader discovers the concrete Sales executive."""

    loader = ExecutiveLoader()

    assert "Sales" in loader.discover()
    executive = loader.load_executive("sales")
    assert isinstance(executive, SalesExecutive)
    assert executive.health_check()
