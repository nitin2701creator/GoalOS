"""Unit tests for the GoalOS chat service intent and safety logic."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.schemas.chat import ChatCompletionRequest, ChatMessage
from app.services.chat_service import (
    ChatIntent,
    ChatService,
    build_requirement,
    detect_intent,
    last_user_message,
    llm_configured,
)


def test_detect_intent_creation_markers() -> None:
    assert detect_intent("Create an agent that monitors Organigram SEO") is ChatIntent.CREATE_AGENT
    assert detect_intent("Please make an agent for keyword research") is ChatIntent.CREATE_AGENT
    assert detect_intent("Can you build an agent to find distributors?") is ChatIntent.CREATE_AGENT
    assert detect_intent("Run the SEO analysis") is ChatIntent.RUN_WORKFLOW
    assert detect_intent("What is the revenue this quarter?") is ChatIntent.RUN_WORKFLOW


def test_last_user_message_and_requirement_context() -> None:
    messages = [
        ChatMessage(role="user", content="Analyze Organigram SEO."),
        ChatMessage(role="assistant", content="I can help with that."),
        ChatMessage(role="user", content="Run the analysis."),
    ]
    assert last_user_message(messages) == "Run the analysis."
    requirement = build_requirement(messages)
    assert "[assistant] I can help with that." in requirement
    assert "Current request: Run the analysis." in requirement


def test_llm_configured_gating() -> None:
    class ConfiguredProvider:
        api_key = "key"

        def request(self, prompt: str, **kwargs):
            return {"response": "text"}

    class UnconfiguredProvider:
        api_key = None

    assert llm_configured(ConfiguredProvider()) is True
    assert llm_configured(UnconfiguredProvider()) is False
    assert llm_configured(None) is False


def _service(tmp_path: Path) -> ChatService:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'chat_unit.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    return ChatService(db=db)


def test_service_refuses_dangerous_agent_creation(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = ChatCompletionRequest(
        messages=[ChatMessage(role="user", content="Create an agent that sends email campaigns.")]
    )
    result = service.handle(request)
    assert result.intent is ChatIntent.CREATE_AGENT
    assert result.blocked is True
    assert "will not auto-authorize dangerous actions" in result.content
    assert service.agent_factory.list_agents() == []


def test_service_resolves_sales_analysis_agent(tmp_path: Path) -> None:
    service = _service(tmp_path)
    request = ChatCompletionRequest(
        messages=[
            ChatMessage(
                role="user",
                content="Create an agent that analyzes Organigram sales and store performance.",
            )
        ]
    )
    result = service.handle(request)
    assert result.intent is ChatIntent.CREATE_AGENT
    assert result.blocked is False
    assert result.agent is not None
    assert result.agent.status.value == "ACTIVE"
    assert "sales_analysis" in result.agent.capabilities
    assert "woocommerce" in result.agent.integrations
    assert "google_analytics" in result.agent.integrations
