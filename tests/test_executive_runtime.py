"""Tests for the implementation-independent executive runtime."""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from app.executives import (
    BaseExecutive,
    ExecutiveAlert,
    ExecutiveKPI,
    ExecutiveLoader,
    ExecutivePriority,
    ExecutiveRecommendation,
    ExecutiveRegistry,
    ExecutiveSummary,
)


class ExampleExecutive(BaseExecutive):
    """Small concrete executive used to exercise the shared contract."""

    def __init__(self) -> None:
        """Create an uninitialized example executive."""

        super().__init__("Sales", "Owns the revenue operation.")
        self.initialized = False
        self.shutdown_called = False

    def initialize(self) -> None:
        """Mark this executive as initialized."""

        self.initialized = True

    def shutdown(self) -> None:
        """Mark this executive as shut down."""

        self.shutdown_called = True
        self.initialized = False

    def health_check(self) -> bool:
        """Return the current test health state."""

        return self.initialized

    def get_summary(self) -> ExecutiveSummary:
        """Return an example summary."""

        return ExecutiveSummary(executive_name=self.name, title="Sales summary")

    def get_kpis(self) -> tuple[ExecutiveKPI, ...]:
        """Return an empty KPI collection."""

        return ()

    def get_alerts(self) -> tuple[ExecutiveAlert, ...]:
        """Return an empty alert collection."""

        return ()

    def get_priorities(self) -> tuple[ExecutivePriority, ...]:
        """Return an empty priority collection."""

        return ()

    def get_recommendations(self) -> tuple[ExecutiveRecommendation, ...]:
        """Return an empty recommendation collection."""

        return ()

    def execute(self, action: str, **kwargs: Any) -> str:
        """Return the requested test action."""

        del kwargs
        return action

    def supported_integrations(self) -> tuple[str, ...]:
        """Return the test executive's integration names."""

        return ("crm",)


def test_base_executive_contract_and_identity_validation() -> None:
    """Concrete executives expose a stable shared interface."""

    executive = ExampleExecutive()

    assert executive.name == "Sales"
    assert executive.execute("forecast") == "forecast"
    assert executive.supported_integrations() == ("crm",)
    with pytest.raises(ValueError, match="name is required"):
        BaseExecutive._require_text("   ", "name")


def test_registry_prevents_duplicates_and_normalizes_names() -> None:
    """The registry owns executive instances under normalized names."""

    registry = ExecutiveRegistry()
    executive = ExampleExecutive()
    registry.register(executive)

    assert registry.exists(" SALES ")
    assert registry.get("sales") is executive
    assert registry.list() == ("sales",)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(ExampleExecutive())
    assert registry.unregister("Sales") is executive
    assert registry.get("sales") is None
    with pytest.raises(TypeError, match="BaseExecutive"):
        registry.register(object())  # type: ignore[arg-type]


def test_loader_discovers_loads_and_reloads_concrete_executives() -> None:
    """Discovery works from an imported module without runtime-specific imports."""

    module = ModuleType("test_executive_module")
    executive_class = type(
        "DiscoveredExecutive",
        (ExampleExecutive,),
        {"__module__": module.__name__},
    )
    setattr(module, executive_class.__name__, executive_class)
    loader = ExecutiveLoader()

    assert loader.discover(module) == ("Sales",)
    loaded = loader.load_executive("sales")
    assert loaded is loader.registry.get("Sales")
    assert loaded.health_check()
    reloaded = loader.reload("sales")
    assert reloaded is loaded
    assert loaded.shutdown_called
    assert loader.load_all()["sales"] is loaded


def test_executive_models_validate_required_and_bounded_fields() -> None:
    """Runtime response models normalize defaults and reject invalid values."""

    summary = ExecutiveSummary(executive_name=" CEO ", title=" Daily briefing ")
    assert summary.executive_name == "CEO"
    assert summary.title == "Daily briefing"
    assert summary.metadata == {}

    with pytest.raises(ValidationError):
        ExecutiveAlert(title="", severity="high")
    with pytest.raises(ValidationError):
        ExecutivePriority(title="Close deal", priority=0)
    with pytest.raises(ValidationError):
        ExecutiveRecommendation(title="Expand", unexpected=True)  # type: ignore[call-arg]
