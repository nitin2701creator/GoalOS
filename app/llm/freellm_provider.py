"""FreeLLM provider implementation."""

from __future__ import annotations

import os
from typing import Any

from app.llm.base_provider import BaseProvider


class FreeLLMProvider(BaseProvider):
    """Basic FreeLLM provider with configuration support."""

    def __init__(self) -> None:
        self.base_url = os.getenv("FREELLMAPI_BASE_URL", "https://api.freellm.example.com")
        self.api_key = os.getenv("FREELLMAPI_API_KEY")
        self.default_model = os.getenv("DEFAULT_MODEL", "free-llm-small")
        self.timeout = int(os.getenv("LLM_TIMEOUT", "30"))

    def request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        # Placeholder deterministic implementation for planning foundation.
        return {
            "model": self.default_model,
            "prompt": prompt,
            "timeout": self.timeout,
            "response": "free-llm-provider-ready",
            "metadata": kwargs,
        }

    def health_check(self) -> bool:
        return bool(self.base_url and self.default_model)
