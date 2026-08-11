"""Tests for the skill/agent integration layer.

Covers SkillDefinition.required_integrations, AgentDefinition.integrations,
persistence, the integration registry passthrough into skill execution,
AgentFactory integration blockers, and honest failure when a required
integration is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.agent_definitions import build_agent_definition
from app.agents.agent_registry import AgentRegistry
from app.agents.permissions import Permission
from app.db.base import Base
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.web import DuckDuckGoSearchProvider, WebConnector
from app.integrations.website import WebsiteConnector
from app.repositories.agent_repository import AgentRepository
from app.repositories.skill_repository import SkillRepository
from app.schemas.agent import AgentCreateRequest
from app.services.agent_factory import AgentFactoryService
from app.skills.definitions import BUILTIN_SKILLS
from app.skills.skill_registry import SkillRegistry
from tests.integration_helpers import make_fake_opener


@pytest.fixture
def db(tmp_path: Path) -> Session:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'skills.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service(db: Session) -> AgentFactoryService:
    return AgentFactoryService(
        AgentRepository(db),
        SkillRepository(db),
        AgentRegistry(),
        SkillRegistry(),
    )


def test_skill_definitions_declare_required_integrations() -> None:
    """SEO/email/ecommerce/meta skills declare their integrations."""
    assert BUILTIN_SKILLS["website_analysis"].required_integrations == ("web", "website")
    assert BUILTIN_SKILLS["keyword_research"].required_integrations == ("web",)
    assert BUILTIN_SKILLS["email_drafting"].required_integrations == ("gmail",)
    assert BUILTIN_SKILLS["lead_qualification"].required_integrations == ("google_analytics",)
    assert BUILTIN_SKILLS["calculation"].required_integrations == ()


def test_agent_definition_collects_integrations() -> None:
    """Capability resolution flows into the agent's integrations."""
    definition = build_agent_definition(
        "Research SEO keywords and analyze the Organigram website's SEO.",
        ("keyword_research", "website_analysis", "web_research"),
    )

    assert definition.integrations == ("web", "website")
    assert definition.skills == ("keyword_research", "website_analysis", "web_research")


def test_agent_persists_and_exposes_integrations(service: AgentFactoryService) -> None:
    """Created agents persist and expose their required integrations."""
    agent = service.create_agent(
        AgentCreateRequest(
            name="Organigram SEO Agent",
            purpose="Research SEO keywords and analyze the Organigram website's SEO.",
            required_capabilities=["keyword_research", "website_analysis", "web_research"],
        )
    )

    assert agent.status == "ACTIVE"
    assert agent.integrations == ["web", "website"]
    assert agent.permissions == [Permission.READ_WEBSITE]

    persisted = service.get_agent(agent.id)
    assert persisted is not None
    assert persisted.integrations == ["web", "website"]

    skill = service.skill_repository.get_by_name("website_analysis")
    assert skill is not None
    assert skill.required_integrations == ["web", "website"]


def test_skills_use_real_connectors_when_registry_provided(
    service: AgentFactoryService, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration-backed skills call the real crawl/search pipelines."""
    opener = make_fake_opener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    registry = ConnectorRegistry()
    registry.register(WebConnector(search_provider=DuckDuckGoSearchProvider()))
    registry.register(WebsiteConnector())

    agent = service.create_agent(
        AgentCreateRequest(
            name="Organigram SEO Agent",
            purpose="Research SEO keywords and analyze the Organigram website's SEO.",
            required_capabilities=["keyword_research", "website_analysis", "web_research"],
        )
    )

    result = service.execute_agent(
        agent.id,
        goal="Analyze the Organigram website's SEO",
        inputs={
            "topic": "organigram",
            "url": "https://www.organigram.com",
            "query": "organigram seo",
        },
        integrations=registry,
    )

    assert result.errors == []
    assert result.results["keyword_research"].get("source") == "web.search"
    assert "Organigram SEO Guide" in result.results["keyword_research"]["keywords"]
    website = result.results["website_analysis"]
    assert website.get("source") == "website.crawl"
    assert website["total_pages"] >= 2
    assert any("multiple H1s" in finding for finding in website["findings"])
    assert result.results["web_research"].get("source") == "web.search"


def test_skills_fall_back_to_deterministic_without_registry(service: AgentFactoryService) -> None:
    """Without an integration registry the deterministic scaffold runs."""
    agent = service.create_agent(
        AgentCreateRequest(
            name="Organigram SEO Agent",
            purpose="Research SEO keywords and analyze the Organigram website's SEO.",
            required_capabilities=["keyword_research", "website_analysis", "web_research"],
        )
    )

    result = service.execute_agent(
        agent.id,
        goal="Analyze the Organigram website's SEO",
        inputs={"topic": "organigram", "url": "https://www.organigram.com", "query": "x"},
    )

    assert result.errors == []
    assert result.results["website_analysis"].get("deterministic") is True


def test_factory_integration_blockers_report_missing_integration(
    service: AgentFactoryService, db: Session
) -> None:
    """A registry without the required integration blocks the agent."""
    agent = service.create_agent(
        AgentCreateRequest(
            name="Organigram SEO Agent",
            purpose="Research SEO keywords and analyze the Organigram website's SEO.",
            required_capabilities=["keyword_research", "website_analysis"],
        )
    )
    registry = ConnectorRegistry()  # no web/website registered

    persisted = service.agent_repository.get(agent.id)
    assert persisted is not None
    blockers = service.integration_blockers(persisted, registry)

    assert any("'web'" in blocker for blocker in blockers)
    assert any("'website'" in blocker for blocker in blockers)


def test_execute_agent_fails_honestly_when_integration_missing(
    service: AgentFactoryService, db: Session
) -> None:
    """Execution with an unconfigured required integration never fakes."""
    agent = service.create_agent(
        AgentCreateRequest(
            name="Organigram SEO Agent",
            purpose="Research SEO keywords and analyze the Organigram website's SEO.",
            required_capabilities=["keyword_research", "website_analysis"],
        )
    )
    registry = ConnectorRegistry()

    with pytest.raises(ValueError, match="cannot execute"):
        service.execute_agent(
            agent.id,
            goal="Analyze",
            inputs={"url": "https://www.organigram.com"},
            integrations=registry,
        )
