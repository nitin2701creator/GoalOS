"""OpenAI-compatible provider built on the shared GoalOS LLM infrastructure.

This provider adapts the existing GoalOS language-model stack — the
environment-driven :class:`LLMConfig`, the retrying HTTP
:class:`FreeLLMClient`, and the :class:`LLMGateway` text extraction — to
the :class:`BaseProvider` contract. It introduces no new API-key
mechanism: base URL, key, and model come from the same environment
configuration the rest of GoalOS uses (``LLM_BASE_URL``, ``LLM_API_KEY``,
``LLM_MODEL``, with legacy ``FREELLM_*`` names still honoured), and the
endpoint is any OpenAI-compatible completion service.
"""

from __future__ import annotations

from typing import Any

from app.ai.config import LLMConfig
from app.ai.free_llm_client import FreeLLMClient
from app.ai.llm_gateway import LLMGateway
from app.llm.base_provider import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Talk to an OpenAI-compatible service through the shared client."""

    def __init__(
        self,
        config: LLMConfig | None = None,
        gateway: LLMGateway | None = None,
    ) -> None:
        """Initialize the provider with the configured or shared client.

        Args:
            config: Runtime configuration; defaults to the environment.
            gateway: Optional pre-built gateway for dependency injection.
        """
        self._config = config or LLMConfig.from_env()
        client = FreeLLMClient(self._config)
        self._gateway = gateway or LLMGateway(client)

    def request(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        """Generate a completion for ``prompt`` and return its payload.

        Args:
            prompt: The instruction sent to the language model.
            **kwargs: Optional overrides, including ``model``.

        Returns:
            A provider payload whose ``response`` key holds the text.
        """
        model = kwargs.pop("model", None)
        response_text = self._gateway.generate(prompt, model=model, **kwargs)
        return {
            "model": model or self._config.default_model,
            "prompt": prompt,
            "response": response_text,
        }

    def health_check(self) -> bool:
        """Return whether the provider is configured for real calls.

        The OpenAI-compatible endpoint needs a base URL and a model.
        An API key is not always required — local providers such as
        Ollama, vLLM, or LM Studio operate without one.
        """
        return bool(self._config.base_url and self._config.default_model)
