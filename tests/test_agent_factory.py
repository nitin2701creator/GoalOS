"""Service tests for the GoalOS agent factory.

Covers every required scenario: creating, validating, registering, skill
reuse/creation, duplicate prevention, permission enforcement, disabling,
capability resolution, execution through the existing agent contract, and
persistence after database restart — plus the end-to-end "sum of two
numbers" agent creation flow.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.agent_definitions import AgentStatus
from app.agents.agent_registry import AgentRegistry
from app.agents.base_agent import AgentContext
from app.agents.permissions import Permission
from app.db.base import Base
from app.repositories.agent_repository import AgentRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import AgentCreateRequest
from app.services.agent_factory import AgentFactoryService
from app.skills.skill_registry import SkillRegistry


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'agents.db'}",
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


@pytest.fixture
def service(db: Session) -> AgentFactoryService:
    return AgentFactoryService(
        AgentRepository(db),
        SkillRepository(db),
        AgentRegistry(),
        SkillRegistry(),
    )


def _create_sum_agent(service: AgentFactoryService):
    """Create the canonical calculation agent with explicit authorization."""
    return service.create_agent(
        AgentCreateRequest(
            name="Calculation Agent",
            purpose="Calculate the sum of two numbers.",
            required_capabilities=["calculation"],
            permissions=[Permission.EXECUTE_CODE],
        )
    )


def test_create_agent_persists_valid_definition(service: AgentFactoryService) -> None:
    """Creating an agent persists the full structured definition as ACTIVE."""
    response = _create_sum_agent(service)

    assert response.status == AgentStatus.ACTIVE
    assert response.name == "Calculation Agent"
    assert response.capabilities == ["calculation"]
    assert response.skills == ["calculation"]
    assert response.permissions == [Permission.EXECUTE_CODE]
    assert response.input_schema["calculation"] == {
        "a": "number",
        "b": "number",
        "operation": "string",
    }
    assert response.output_schema["calculation"] == {"result": "number"}
    assert response.system_instructions
    assert response.version == "1.0"
    assert response.created_at is not None


def test_validate_agent_marks_invalid_definition_failed(service: AgentFactoryService) -> None:
    """An agent with an unsupported capability fails validation."""
    agent = _create_sum_agent(service)

    # Corrupt the persisted definition so validation must reject it.
    persisted = service.agent_repository.get(agent.id)
    assert persisted is not None
    service.agent_repository.update(persisted, {"capabilities": ["nonsense"]})
    refreshed = service.agent_repository.get(agent.id)
    assert refreshed is not None
    assert refreshed.capabilities == ["nonsense"]

    result = service.validate_agent(agent.id)

    assert result.status == AgentStatus.FAILED
    assert "unsupported capability" in (result.status_reason or "")


def test_validate_agent_never_activates_without_validation(service: AgentFactoryService) -> None:
    """An agent persisted directly as DRAFT cannot reach ACTIVE unvalidated."""
    service._ensure_skills(("web_research",))
    persisted = service.agent_repository.create(
        {
            "name": "Draft Agent",
            "purpose": "Never active until validated.",
            "capabilities": ["web_research"],
            "skills": ["web_research"],
            "permissions": [Permission.READ_WEBSITE.value],
            "input_schema": {"web_research": {"query": "string"}},
            "output_schema": {"web_research": {"findings": ["string"]}},
            "status": AgentStatus.DRAFT,
        }
    )
    assert persisted.status == AgentStatus.DRAFT

    result = service.validate_agent(persisted.id)
    assert result.status == AgentStatus.ACTIVE


def test_register_agent_exposes_dynamic_agent_to_registry(service: AgentFactoryService) -> None:
    """After creation the dynamic agent is discoverable in the runtime registry."""
    _create_sum_agent(service)

    assert "Calculation Agent" in service.agent_registry.list_agents()
    instance = service.get_runtime_agent("Calculation Agent")
    assert instance is not None
    assert instance.agent_name == "Calculation Agent"
    assert instance.definition.capabilities == ("calculation",)

    # Registering a second time is a no-op, not a duplicate.
    registered = service.agent_registry.list_agents()
    agent = service.agent_repository.get_by_name("Calculation Agent")
    assert agent is not None
    service.register_agent(agent.id)
    assert service.agent_registry.list_agents() == registered


def test_attach_existing_skill_reuses_definition(service: AgentFactoryService) -> None:
    """A second agent reuses the already-persisted skill definition."""
    _create_sum_agent(service)
    assert len(service.skill_repository.list()) == 1

    other = service.create_agent(
        AgentCreateRequest(
            name="Math Tutor Agent",
            purpose="Tutor arithmetic.",
            required_capabilities=["calculation"],
            permissions=[Permission.EXECUTE_CODE],
        )
    )

    assert other.status == AgentStatus.ACTIVE
    assert len(service.skill_repository.list()) == 1


def test_create_missing_skill_from_catalog(service: AgentFactoryService) -> None:
    """A capability without a persisted skill creates it from the catalog."""
    response = service.create_agent(
        AgentCreateRequest(
            name="SEO Agent",
            purpose="Research SEO keywords and analyze website SEO.",
            required_capabilities=["keyword_research", "website_analysis"],
        )
    )

    assert response.status == AgentStatus.ACTIVE
    skill_names = {skill.name for skill in service.skill_repository.list()}
    assert skill_names == {"keyword_research", "website_analysis"}
    assert response.permissions == [Permission.READ_WEBSITE]


def test_prevent_duplicate_skills(service: AgentFactoryService) -> None:
    """Multiple agents sharing a capability never duplicate its skill."""
    for name, purpose in [
        ("SEO Agent", "Research SEO keywords."),
        ("Marketing Agent", "Improve keyword reach."),
        ("Growth Agent", "Analyze website growth signals."),
    ]:
        response = service.create_agent(
            AgentCreateRequest(
                name=name,
                purpose=purpose,
                required_capabilities=["keyword_research", "website_analysis"],
            )
        )
        assert response.status == AgentStatus.ACTIVE

    assert len(service.skill_repository.list()) == 2


def test_prevent_duplicate_agents(service: AgentFactoryService) -> None:
    """The same agent name cannot be created twice."""
    _create_sum_agent(service)

    with pytest.raises(ValueError, match="agent already exists"):
        _create_sum_agent(service)


def test_enforce_permissions(service: AgentFactoryService) -> None:
    """Dangerous capabilities require explicit authorization."""
    with pytest.raises(ValueError, match="dangerous permissions require explicit authorization"):
        service.create_agent(
            AgentCreateRequest(
                name="Calculator Without Authorization",
                purpose="Sum numbers.",
                required_capabilities=["calculation"],
            )
        )

    # Non-dangerous capabilities are granted implicitly.
    research = service.create_agent(
        AgentCreateRequest(
            name="Research Agent",
            purpose="Research topics on the web.",
            required_capabilities=["web_research"],
        )
    )
    assert research.status == AgentStatus.ACTIVE
    assert research.permissions == [Permission.READ_WEBSITE]


def test_disable_and_enable_agent(service: AgentFactoryService) -> None:
    """A disabled agent cannot execute; enabling re-validates it."""
    agent = _create_sum_agent(service)

    disabled = service.disable_agent(agent.id)
    assert disabled.status == AgentStatus.DISABLED

    with pytest.raises(ValueError, match="not ACTIVE"):
        service.execute_agent(agent.id, "Sum", {"a": 1, "b": 2})

    enabled = service.enable_agent(agent.id)
    assert enabled.status == AgentStatus.ACTIVE

    result = service.execute_agent(agent.id, "Sum", {"a": 1, "b": 2})
    assert result.results["calculation"]["result"] == 3.0


def test_resolve_requirement_into_existing_agent(service: AgentFactoryService) -> None:
    """A requirement covered by an ACTIVE agent resolves to that agent."""
    service.create_agent(
        AgentCreateRequest(
            name="SEO Agent",
            purpose="Research SEO keywords and analyze website SEO.",
            required_capabilities=[
                "keyword_research",
                "website_analysis",
                "content_analysis",
                "web_research",
            ],
        )
    )

    resolved = service.resolve("research SEO keywords and analyze website")

    assert resolved.agent is not None
    assert resolved.specification is None
    assert resolved.agent.name == "SEO Agent"


def test_resolve_requirement_into_new_specification(service: AgentFactoryService) -> None:
    """An uncovered requirement produces a deterministic specification."""
    resolved = service.resolve("find organic food distributors in India")

    assert resolved.agent is None
    assert resolved.specification is not None
    assert resolved.specification.capabilities == ["web_research", "company_discovery"]
    assert resolved.specification.name == "Web Research Agent"
    assert resolved.specification.permissions == [Permission.READ_WEBSITE]
    assert resolved.specification.skills == ["web_research", "company_discovery"]

    with pytest.raises(ValueError, match="no capabilities could be resolved"):
        service.resolve("xyzzy zork")


def test_execute_dynamic_agent_through_existing_contract(service: AgentFactoryService) -> None:
    """A dynamic agent executes through the existing BaseAgent lifecycle."""
    agent = _create_sum_agent(service)
    instance = service.get_runtime_agent("Calculation Agent")
    assert instance is not None
    assert not instance.is_initialized

    result = service.execute_agent(agent.id, "Sum 2 and 3", {"a": 2, "b": 3})

    assert result.agent_name == "Calculation Agent"
    assert result.errors == []
    assert result.results["calculation"] == {"result": 5.0}
    # The runtime instance is re-registered per execution with its context.
    refreshed = service.get_runtime_agent("Calculation Agent")
    assert refreshed is not None
    assert refreshed.is_initialized

    # The existing orchestration contract (plan/report) also works.
    import asyncio

    plan = asyncio.run(instance.plan(AgentContext(goal="Sum numbers")))
    assert plan.agent_name == "Calculation Agent"
    report = asyncio.run(instance.report(AgentContext(goal="Sum numbers")))
    assert report.metadata["skills"] == ("calculation",)


def test_execution_survives_restart(session_factory, tmp_path: Path) -> None:
    """Persistence: a fresh service over the same database can re-execute."""
    session = session_factory()
    service = AgentFactoryService(
        AgentRepository(session),
        SkillRepository(session),
        AgentRegistry(),
        SkillRegistry(),
    )
    agent = _create_sum_agent(service)
    agent_id = agent.id
    session.close()

    engine = create_engine(
        f"sqlite:///{tmp_path / 'agents.db'}",
        connect_args={"check_same_thread": False},
    )
    Session2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session2 = Session2()
    try:
        restarted_service = AgentFactoryService(
            AgentRepository(session2),
            SkillRepository(session2),
            AgentRegistry(),
            SkillRegistry(),
        )
        restarted = restarted_service.get_agent(agent_id)
        assert restarted is not None
        assert restarted.status == AgentStatus.ACTIVE
        assert restarted.capabilities == ["calculation"]
        assert restarted.permissions == [Permission.EXECUTE_CODE]

        # The runtime instance is rebuilt from the persisted definition.
        result = restarted_service.execute_agent(agent_id, "Sum 40 and 2", {"a": 40, "b": 2})
        assert result.results["calculation"] == {"result": 42.0}
    finally:
        session2.close()
        engine.dispose()


def test_end_to_end_sum_of_two_numbers_agent(service: AgentFactoryService) -> None:
    """Requirement -> resolve -> create -> register -> execute -> correct result.

    No special-casing: the same flow works for any catalog capability.
    """
    requirement = "Create an agent capable of calculating the sum of two numbers."

    # 1. Receive the requirement and resolve it.
    resolved = service.resolve(requirement)
    assert resolved.agent is None
    spec = resolved.specification
    assert spec is not None
    assert spec.capabilities == ["calculation"]

    # 2. Create the missing agent (with explicit authorization for code).
    agent = service.create_agent(
        AgentCreateRequest(
            name=spec.name,
            purpose=spec.purpose,
            required_capabilities=list(spec.capabilities),
            permissions=[Permission.EXECUTE_CODE],
        )
    )
    assert agent.status == AgentStatus.ACTIVE

    # 3. The missing skill was created and registered.
    skill = service.skill_repository.get_by_name("calculation")
    assert skill is not None
    assert skill.enabled

    # 4. The agent is registered with the orchestrator's registry.
    assert spec.name in service.agent_registry.list_agents()

    # 5. Execute and collect the result.
    result = service.execute_agent(agent.id, "Sum 2 and 3", {"a": 2, "b": 3})
    assert result.errors == []
    assert result.results["calculation"] == {"result": 5.0}


def test_update_agent_keeps_disabled_state(service: AgentFactoryService) -> None:
    """Updating a disabled agent does not silently re-activate it."""
    agent = _create_sum_agent(service)
    service.disable_agent(agent.id)

    from app.schemas.agent import AgentUpdateRequest

    updated = service.update_agent(agent.id, AgentUpdateRequest(purpose="Sum any numbers."))

    assert updated.status == AgentStatus.DISABLED
    assert updated.purpose == "Sum any numbers."


def test_get_and_list_agents(service: AgentFactoryService) -> None:
    """Agents are queryable by id and listed deterministically."""
    first = _create_sum_agent(service)
    second = service.create_agent(
        AgentCreateRequest(
            name="SEO Agent",
            purpose="Research SEO keywords.",
            required_capabilities=["keyword_research"],
        )
    )

    by_id = service.get_agent(first.id)
    assert by_id is not None
    assert by_id.name == "Calculation Agent"

    by_name = service.get_agent_by_name("SEO Agent")
    assert by_name is not None
    assert by_name.id == second.id

    names = [agent.name for agent in service.list_agents()]
    assert names == ["Calculation Agent", "SEO Agent"]

    assert service.get_agent(uuid.uuid4()) is None
