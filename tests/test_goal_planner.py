"""Tests for the LLM-driven goal planner (goal → ordered capability plan).

Covers:
- an LLM plan is used, with its ordering respected and names normalized
  to catalog execution capabilities;
- explicit user restrictions are applied as a hard filter — a prohibited
  capability is never planned, even when the LLM suggests it;
- unregistered capability suggestions are never trusted;
- an unparseable/failing LLM falls back to the deterministic resolver
  (identical to the pre-planner behavior);
- with no provider configured the deterministic plan is used unchanged.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.planner_service import PlannerService
from app.db.base import Base
from app.integrations.factory import build_default_registry
from app.repositories.capability_repository import CapabilityRepository
from app.services.capability_service import CapabilityService

SEO_GOAL = "Analyze Organigram's website SEO."
ONLY_WEB_RESEARCH_GOAL = (
    "Use ONLY the web_research capability. Do not use WooCommerce, analytics, "
    "website_analysis, or any other integration. Search the web for Organigram "
    "India organic food."
)


class PlanProvider:
    """Fake provider returning a fixed response for every planning call."""

    api_key = "fake-key"

    def __init__(self, content: str) -> None:
        self.content = content

    def request(self, prompt: str, **kwargs):  # test double
        return {"choices": [{"message": {"content": self.content}}]}


def _planner(tmp_path: Path, provider=None) -> tuple[PlannerService, object]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'planner.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    capability_service = CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
        llm_provider=provider,
    )
    return PlannerService(capability_service, provider), db


def test_planner_uses_llm_ordered_plan_with_normalized_capabilities(
    tmp_path: Path,
) -> None:
    """An LLM plan is used, respecting the LLM's order and normalizing names."""
    content = (
        '{"steps": ['
        '{"capability": "web_search", "goal": "Research Organigram first"},'
        '{"capability": "website_analysis", "goal": "Analyze the site next"}'
        "]}"
    )
    planner, db = _planner(tmp_path, PlanProvider(content))
    try:
        plan = planner.plan_for_goal(SEO_GOAL)
        assert plan.source == "llm"
        # web_search is normalized to its catalog execution capability
        # web_research; the LLM's order is preserved.
        assert plan.capabilities == ["web_research", "website_analysis"]
        assert plan.steps[0].goal == "Research Organigram first"
        assert plan.steps[1].goal == "Analyze the site next"
    finally:
        db.close()


def test_planner_never_plans_prohibited_capabilities(tmp_path: Path) -> None:
    """Restrictions are the final word: prohibited LLM suggestions are dropped."""
    content = (
        '{"steps": ['
        '{"capability": "web_research", "goal": "Search"},'
        '{"capability": "woocommerce_read", "goal": "Read products"}'
        "]}"
    )
    planner, db = _planner(tmp_path, PlanProvider(content))
    try:
        plan = planner.plan_for_goal(ONLY_WEB_RESEARCH_GOAL)
        assert plan.source == "llm"
        assert plan.capabilities == ["web_research"]
    finally:
        db.close()


def test_planner_drops_unregistered_capability_suggestions(tmp_path: Path) -> None:
    """Free-form LLM capability names are never trusted."""
    content = (
        '{"steps": ['
        '{"capability": "invented_capability", "goal": "Nope"},'
        '{"capability": "web_research", "goal": "Yes"}'
        "]}"
    )
    planner, db = _planner(tmp_path, PlanProvider(content))
    try:
        plan = planner.plan_for_goal(SEO_GOAL)
        assert plan.capabilities == ["web_research"]
    finally:
        db.close()


def test_planner_falls_back_to_deterministic_on_unparseable_llm(
    tmp_path: Path,
) -> None:
    """An unusable LLM plan must never break resolution; fall back."""
    planner, db = _planner(tmp_path, PlanProvider("I cannot produce JSON here."))
    try:
        plan = planner.plan_for_goal(SEO_GOAL)
        assert plan.source == "deterministic"
        deterministic = planner._deterministic_plan(SEO_GOAL)
        assert plan.capabilities == deterministic.capabilities
        resolution = planner.capability_service.resolve_for_goal(SEO_GOAL)
        assert plan.capabilities == list(resolution.execution_capabilities)
    finally:
        db.close()


def test_planner_falls_back_to_deterministic_when_all_steps_prohibited(
    tmp_path: Path,
) -> None:
    """A plan whose steps are all prohibited falls back, never executes them."""
    content = (
        '{"steps": ['
        '{"capability": "sales_analysis", "goal": "Sell stuff"},'
        '{"capability": "website_analysis", "goal": "Crawl"}'
        "]}"
    )
    planner, db = _planner(tmp_path, PlanProvider(content))
    try:
        plan = planner.plan_for_goal(ONLY_WEB_RESEARCH_GOAL)
        assert plan.source == "deterministic"
        assert "sales_analysis" not in plan.capabilities
        assert "website_analysis" not in plan.capabilities
    finally:
        db.close()


def test_planner_without_provider_uses_deterministic_plan(tmp_path: Path) -> None:
    """No LLM configured → deterministic plan identical to the engine's resolution."""
    planner, db = _planner(tmp_path, provider=None)
    try:
        plan = planner.plan_for_goal(SEO_GOAL)
        assert plan.source == "deterministic"
        resolution = planner.capability_service.resolve_for_goal(SEO_GOAL)
        assert plan.capabilities == list(resolution.execution_capabilities)
    finally:
        db.close()
