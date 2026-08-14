"""Tests for sequential, result-chained execution of a persisted goal plan.

The execution runtime accepts an approved workflow whose ``plan`` holds an
ordered list of capability steps. These tests prove:

- the plan's order is the execution order (not the catalog order);
- each step's input includes ``previous_outputs`` — the accumulated
  outputs of the steps that already completed (result chaining);
- explicit user restrictions are re-enforced at runtime: a prohibited
  step persisted in a plan is never executed or persisted;
- a plan step whose integration is unavailable fails honestly with
  INTEGRATION_NOT_CONFIGURED — never fabricated;
- a plan-less workflow keeps the existing deterministic behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.runtime_execution import RuntimeExecutionStatus
from app.integrations.factory import build_default_registry
from app.repositories.agent_repository import AgentRepository
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.project import ProjectCreateRequest
from app.schemas.workflow import WorkflowCreateRequest
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.workflow_service import WorkflowService
from tests.integration_helpers import FakeUrlOpener

SEO_GOAL = "Analyse Organigram's website SEO at https://www.organigram.com."
ONLY_WEB_RESEARCH_GOAL = (
    "Use ONLY the web_research capability. Do not use WooCommerce, analytics, "
    "website_analysis, or any other integration. Search the web for Organigram "
    "India organic food."
)


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'plan_execution.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _capability_service(db) -> CapabilityService:
    return CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
    )


def _runtime(db) -> ExecutionRuntimeService:
    return ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        _capability_service(db),
        workflow_repository=WorkflowRepository(db),
    )


def _agent_factory(db) -> AgentFactoryService:
    return AgentFactoryService(AgentRepository(db), SkillRepository(db))


def _workflow(db) -> object:
    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="Plan execution project",
            description="Project for plan execution tests.",
            owner="GoalOS",
            department="Autonomous",
            priority="High",
        )
    )
    return WorkflowRepository(db).create(
        WorkflowCreateRequest(project_id=project.id, name="Plan execution workflow")
    )


def test_plan_steps_execute_in_plan_order_with_chained_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted plan runs step-by-step; later steps receive earlier outputs."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    # Plan order deliberately differs from the catalog order
    # (keyword_research, website_analysis) to prove the plan is authoritative.
    plan = [
        {"capability": "web_research", "goal": "Find Organigram SEO issues"},
        {"capability": "website_analysis", "goal": "Analyze the site from research"},
    ]
    approved = workflow_service.approve(
        workflow.id,
        SEO_GOAL,
        capability_service=_capability_service(db),
        plan=plan,
    )
    assert approved.plan == plan

    runtime = _runtime(db)
    result = runtime.run_workflow(workflow.id, agent_factory=_agent_factory(db))

    assert result.workflow.status == "Completed"
    assert result.workflow.evaluation["passed"] is True
    assert result.workflow.evaluation["total_steps"] == 2
    # The plan order, not the catalog order, is the execution order.
    assert [step["capability"] for step in result.workflow.steps] == [
        "web_research",
        "website_analysis",
    ]
    assert all(step["status"] == "Completed" for step in result.workflow.steps)
    assert result.workflow.results["web_research"]["source"] == "web.search"
    assert result.workflow.results["website_analysis"]["source"] == "website.crawl"

    # One persisted execution per plan step, in plan order.
    assert [execution.capability for execution in result.executions] == [
        "web_research",
        "website_analysis",
    ]
    assert all(
        execution.status is RuntimeExecutionStatus.SUCCEEDED
        for execution in result.executions
    )

    # Result chaining: the second step received the first step's output as
    # previous_outputs in its persisted input.
    second = result.executions[1]
    previous = (second.input or {}).get("previous_outputs") or {}
    assert "web_research" in previous
    assert previous["web_research"]["source"] == "web.search"
    # The first step saw no accumulated outputs.
    first = result.executions[0]
    assert (first.input or {}).get("previous_outputs") == {}
    db.close()


def test_runtime_never_executes_prohibited_plan_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prohibited step persisted in a plan is filtered out before execution.

    This is the runtime-side guard: even if a plan somehow contains a
    capability the user explicitly prohibited, it is never executed or
    persisted as a step.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    # A "bad" plan that includes the prohibited sales_analysis step.
    plan = [
        {"capability": "web_research", "goal": "Search"},
        {"capability": "sales_analysis", "goal": "Should never run"},
    ]
    workflow_service.approve(
        workflow.id,
        ONLY_WEB_RESEARCH_GOAL,
        capability_service=_capability_service(db),
        plan=plan,
    )

    runtime = _runtime(db)
    result = runtime.run_workflow(workflow.id, agent_factory=_agent_factory(db))

    assert result.workflow.status == "Completed"
    assert [step["capability"] for step in result.workflow.steps] == ["web_research"]
    assert [execution.capability for execution in result.executions] == ["web_research"]
    assert "sales_analysis" not in (result.workflow.results or {})
    db.close()


def test_plan_step_unavailable_returns_integration_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plan step whose integration is unconfigured fails the run honestly."""
    monkeypatch.delenv("GOALOS_SEARCH_PROVIDER", raising=False)

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    plan = [{"capability": "web_research", "goal": "Search"}]
    workflow_service.approve(
        workflow.id,
        ONLY_WEB_RESEARCH_GOAL,
        capability_service=_capability_service(db),
        plan=plan,
    )

    runtime = _runtime(db)
    result = runtime.run_workflow(workflow.id, agent_factory=_agent_factory(db))

    assert result.workflow.status == "Failed"
    assert result.workflow.evaluation["passed"] is False
    assert "web.search" in (result.workflow.error_message or "")
    assert result.workflow.steps[0]["status"] == "Blocked"
    blocked = [
        execution
        for execution in result.executions
        if execution.status is RuntimeExecutionStatus.BLOCKED
    ]
    assert len(blocked) == 1
    assert blocked[0].capability == "web_research"
    assert blocked[0].error_code == "INTEGRATION_NOT_CONFIGURED"
    assert "web.search" in (blocked[0].error or "")
    db.close()


def test_plan_less_workflow_resolves_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a persisted plan the runtime keeps the existing behavior."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    workflow_service.approve(
        workflow.id, SEO_GOAL, capability_service=_capability_service(db)
    )

    runtime = _runtime(db)
    result = runtime.run_workflow(workflow.id, agent_factory=_agent_factory(db))

    assert result.workflow.status == "Completed"
    assert [step["capability"] for step in result.workflow.steps] == [
        "keyword_research",
        "website_analysis",
    ]
    assert len(result.executions) == 2
    db.close()
