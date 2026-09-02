"""Factory for selecting LLM provider implementations."""

from __future__ import annotations

import os

from app.llm.base_provider import BaseProvider
from app.llm.freellm_provider import FreeLLMProvider
from app.llm.openai_compatible_provider import OpenAICompatibleProvider


class ProviderFactory:
    """Returns configured provider implementations."""

    @staticmethod
    def create() -> BaseProvider:
        provider_name = os.getenv("LLM_PROVIDER", "openai_compatible").lower()
        if provider_name == "freellm":
            return FreeLLMProvider()
        if provider_name in {"openai", "openai_compatible"}:
            return OpenAICompatibleProvider()
        if provider_name == "gemini":
            from app.llm.gemini_provider import GeminiProvider

            return GeminiProvider()
        raise ValueError(f"Unsupported LLM provider: {provider_name}")
