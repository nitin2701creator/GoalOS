"""Service tests for the autonomous agent workflow run.

Covers the full Organigram flow: business goal -> capability analysis ->
agent/skill creation -> execution through the existing agent runtime ->
persisted step results/evaluation, plus agent reuse, duplicate
prevention, failure paths, the dangerous-permission guard, and restart
durability.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.goal import Goal
from app.db.models.project import Project
from app.db.models.workflow import Workflow, WorkflowStatus
from app.repositories.agent_repository import AgentRepository
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.agent_factory import AgentFactoryService
from app.services.workflow_service import WorkflowService

ORGANIGRAM_REQUIREMENT = (
    "Research SEO keywords and analyze the Organigram website's SEO at "
    "https://www.organigram.com to improve organic search performance."
)


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflows.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db(session_factory) -> Session:
    session = session_factory()
    yield session
    session.close()


def _create_goal_project_workflow(db: Session, name: str = "Organigram SEO workflow") -> Workflow:
    goal = Goal(
        title="Organigram SEO",
        description="Improve organic search performance for the Organigram website.",
        executive_owner="CMO",
        department="Marketing",
        priority="High",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    project = Project(
        goal_id=goal.id,
        title="Organigram SEO research",
        description="Research and analysis for the Organigram website.",
        owner="Growth",
        department="Marketing",
        priority="High",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    workflow = Workflow(project_id=project.id, name=name)
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


@pytest.fixture
def workflow(db: Session) -> Workflow:
    return _create_goal_project_workflow(db)


@pytest.fixture
def service(db: Session) -> WorkflowService:
    return WorkflowService(WorkflowRepository(db), ExecutionRepository(db))


@pytest.fixture
def factory(db: Session) -> AgentFactoryService:
    return AgentFactoryService(AgentRepository(db), SkillRepository(db))


def test_full_organigram_workflow_run(service: WorkflowService, factory: AgentFactoryService, workflow: Workflow) -> None:
    """The Organigram goal is resolved into capabilities, executed, and persisted."""
    response = service.run_agent_workflow(workflow.id, ORGANIGRAM_REQUIREMENT, factory)

    assert response.status == "Completed"
    assert response.progress_percentage == 100
    assert response.requirement == ORGANIGRAM_REQUIREMENT

    capabilities = [step["capability"] for step in response.steps]
    assert capabilities == ["keyword_research", "website_analysis", "content_analysis", "web_research"]
    assert all(step["status"] == "Completed" for step in response.steps)

    assert "organigram best practices" in response.results["keyword_research"]["keywords"]
    assert response.results["website_analysis"]["findings"][0].startswith("structure analyzed for https://www.organigram.com")
    assert response.results["content_analysis"]["word_count"] > 0
    assert response.results["web_research"]["findings"]

    assert response.evaluation["passed"] is True
    assert response.evaluation["completed_steps"] == 4
    assert "Keyword Research Agent" in response.evaluation["summary"]

    # The agent and its skills were created and registered.
    assert "Keyword Research Agent" in factory.agent_registry.list_agents()
    skill_names = {skill.name for skill in factory.skill_repository.list()}
    assert skill_names == {"keyword_research", "website_analysis", "content_analysis", "web_research"}

    # The persisted workflow row carries the run state.
    persisted = service.get(workflow.id)
    assert persisted is not None
    assert persisted.status == "Completed"
    assert persisted.steps and persisted.results and persisted.evaluation


def test_agent_and_skills_are_reused_across_runs(service: WorkflowService, factory: AgentFactoryService, db: Session) -> None:
    """A second workflow run reuses the existing agent and skills."""
    first = _create_goal_project_workflow(db, "First run")
    second = _create_goal_project_workflow(db, "Second run")

    first_response = service.run_agent_workflow(first.id, ORGANIGRAM_REQUIREMENT, factory)
    assert first_response.status == "Completed"

    second_factory = AgentFactoryService(AgentRepository(db), SkillRepository(db))
    second_response = service.run_agent_workflow(second.id, ORGANIGRAM_REQUIREMENT, second_factory)

    assert second_response.status == "Completed"
    assert len(second_factory.agent_repository.list()) == 1
    assert len(second_factory.skill_repository.list()) == 4


def test_duplicate_run_is_rejected(service: WorkflowService, factory: AgentFactoryService, workflow: Workflow) -> None:
    """A workflow cannot be run twice."""
    service.run_agent_workflow(workflow.id, ORGANIGRAM_REQUIREMENT, factory)

    with pytest.raises(ValueError, match="already been run"):
        service.run_agent_workflow(workflow.id, ORGANIGRAM_REQUIREMENT, factory)


def test_unresolvable_requirement_fails_cleanly(service: WorkflowService, factory: AgentFactoryService, workflow: Workflow) -> None:
    """A requirement with no capabilities fails with a persisted reason."""
    response = service.run_agent_workflow(workflow.id, "xyzzy zork", factory)

    assert response.status == "Failed"
    assert response.error_message == "no capabilities could be resolved from the requirement"
    assert response.evaluation["passed"] is False
    assert response.steps == []


def test_dangerous_capability_requires_authorization(
    service: WorkflowService, factory: AgentFactoryService, db: Session
) -> None:
    """A run whose agent needs a dangerous permission fails without it."""
    workflow = _create_goal_project_workflow(db, "Calculation workflow")
    response = service.run_agent_workflow(
        workflow.id,
        "Create an agent capable of calculating the sum of two numbers.",
        factory,
    )

    assert response.status == "Failed"
    assert "dangerous permissions require explicit authorization" in (response.error_message or "")
    assert response.evaluation["passed"] is False


def test_restart_does_not_lose_workflow_state(session_factory, tmp_path: Path) -> None:
    """A fresh process over the same database sees the full run state."""
    session = session_factory()
    service = WorkflowService(WorkflowRepository(session), ExecutionRepository(session))
    factory = AgentFactoryService(AgentRepository(session), SkillRepository(session))
    workflow = _create_goal_project_workflow(session)
    response = service.run_agent_workflow(workflow.id, ORGANIGRAM_REQUIREMENT, factory)
    workflow_id = workflow.id
    assert response.status == "Completed"
    session.close()

    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflows.db'}",
        connect_args={"check_same_thread": False},
    )
    Session2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session2 = Session2()
    try:
        restarted = session2.get(Workflow, workflow_id)
        assert restarted is not None
        assert restarted.status == WorkflowStatus.COMPLETED
        assert restarted.requirement == ORGANIGRAM_REQUIREMENT
        assert len(restarted.steps) == 4
        assert restarted.steps[0]["status"] == "Completed"
        assert restarted.evaluation["passed"] is True
        assert restarted.results["keyword_research"]["keywords"]

        # The agent can be re-executed from the persisted definition.
        restarted_factory = AgentFactoryService(AgentRepository(session2), SkillRepository(session2))
        agent = restarted_factory.get_agent_by_name("Keyword Research Agent")
        assert agent is not None
        assert agent.status == "ACTIVE"
        execution = restarted_factory.execute_agent(
            agent.id, ORGANIGRAM_REQUIREMENT, {"topic": "organigram"}
        )
        assert execution.results["keyword_research"]["keywords"]
    finally:
        session2.close()
        engine.dispose()
