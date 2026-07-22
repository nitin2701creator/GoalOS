"""Tests for Digital CEO executive coordination."""

from __future__ import annotations

import pytest

from app.agents import AgentContext
from app.agents.ceo import CEOAgent, ExecutiveRegistry


class FakeExecutive:
    def __init__(
        self, name: str, status: str, priorities: tuple[str, ...], recommendations: tuple[str, ...]
    ) -> None:
        self.name = name
        self.status = status
        self.priorities = priorities
        self.recommendations = recommendations
        self.executed_actions: list[object] = []

    def get_status(self) -> str:
        return self.status

    def get_kpis(self) -> dict[str, int]:
        return {"pipeline": 10}

    def get_priorities(self) -> tuple[str, ...]:
        return self.priorities

    def get_recommendations(self) -> tuple[str, ...]:
        return self.recommendations

    def execute(self, action: object) -> dict[str, object]:
        self.executed_actions.append(action)
        return {"executed": action}


def test_ceo_discovers_registered_executives() -> None:
    registry = ExecutiveRegistry()
    registry.register(FakeExecutive("Sales", "On Track", (), ()))
    registry.register(FakeExecutive("Marketing", "On Track", (), ()))
    ceo = CEOAgent(registry)

    assert ceo.discover_executives() == ("marketing", "sales")


def test_ceo_aggregates_department_summaries_and_prioritizes_actions() -> None:
    registry = ExecutiveRegistry()
    registry.register(
        FakeExecutive(
            "Sales", "At Risk", ("Follow up enterprise pipeline",),
            ("Revenue decline risk requires attention.",),
        )
    )
    registry.register(
        FakeExecutive("Marketing", "On Track", ("Publish launch campaign",), ("Expand partner reach.",))
    )
    brief = CEOAgent(registry).generate_executive_briefing()

    assert [summary.department for summary in brief.department_summaries] == ["sales", "marketing"]
    assert brief.department_summaries[0].kpis == {"pipeline": 10}
    assert [action.rank for action in brief.today_priorities] == [1, 2]
    assert "Revenue decline risk requires attention." in brief.top_risks
    assert "Expand partner reach." in brief.top_opportunities
    assert brief.ai_recommendations == (
        "Revenue decline risk requires attention.", "Expand partner reach.",
    )


def test_ceo_delegates_objectives_and_work_to_executives() -> None:
    executive = FakeExecutive("Procurement", "On Track", (), ())
    registry = ExecutiveRegistry()
    registry.register(executive)
    ceo = CEOAgent(registry)

    assert ceo.delegate_work("procurement", "Review supplier quote") == {"executed": "Review supplier quote"}
    assert ceo.assign_objective("procurement", "Reduce supplier costs") == {
        "executed": {"type": "objective", "objective": "Reduce supplier costs"}
    }
    assert ceo.delegate_work("missing", "No-op") is None
    assert executive.executed_actions[0] == "Review supplier quote"


@pytest.mark.asyncio
async def test_ceo_survives_missing_executives_and_uses_agent_runtime() -> None:
    ceo = CEOAgent()

    brief = ceo.generate_executive_briefing()
    report = await ceo.report(AgentContext(goal="Run Organigram"))
    execution = await ceo.execute(AgentContext(goal="Run Organigram"))

    assert brief.department_summaries == ()
    assert brief.today_priorities == ()
    assert report.metadata["executive_count"] == 0
    assert execution.metadata["delegated"] is False
