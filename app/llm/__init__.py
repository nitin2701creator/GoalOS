"""LLM provider package initialization."""

from __future__ import annotations

from app.llm.base_provider import BaseProvider
from app.llm.freellm_provider import FreeLLMProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider
from app.llm.provider_factory import ProviderFactory

__all__ = [
    "BaseProvider",
    "FreeLLMProvider",
    "OpenAICompatibleProvider",
    "ProviderFactory",
]


def _optional_gemini_provider():
    """Lazily expose GeminiProvider when google-genai is installed."""
    try:
        from app.llm.gemini_provider import GeminiProvider  # noqa: WPS433
        return GeminiProvider
    except ImportError:
        return None


GeminiProvider = _optional_gemini_provider()
