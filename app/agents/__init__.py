"""Agent foundations for GoalOS."""

from __future__ import annotations

from app.agents.agent_definitions import AgentDefinition, AgentStatus
from app.agents.agent_loader import AgentLoader
from app.agents.agent_registry import AgentRegistry
from app.agents.base_agent import AgentContext, AgentResult, BaseAgent
from app.agents.developer_agent import DeveloperAgent

__all__ = [
    "AgentContext",
    "AgentDefinition",
    "AgentLoader",
    "AgentRegistry",
    "AgentResult",
    "AgentStatus",
    "BaseAgent",
    "DeveloperAgent",
]
