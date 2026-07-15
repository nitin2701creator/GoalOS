"""Factory for selecting LLM provider implementations."""

from __future__ import annotations

import os

from app.llm.base_provider import BaseProvider
from app.llm.freellm_provider import FreeLLMProvider


class ProviderFactory:
    """Returns configured provider implementations."""

    @staticmethod
    def create() -> BaseProvider:
        provider_name = os.getenv("LLM_PROVIDER", "freellm").lower()
        if provider_name == "freellm":
            return FreeLLMProvider()
        raise ValueError(f"Unsupported LLM provider: {provider_name}")
