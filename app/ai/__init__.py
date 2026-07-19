"""Shared AI infrastructure for GoalOS agents."""

from app.ai.config import LLMConfig
from app.ai.llm_gateway import LLMGateway

__all__ = ["LLMConfig", "LLMGateway"]
