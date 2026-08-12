"""HTTP client implementation for the configured FreeLLM-compatible service."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.config import LLMConfig
from app.ai.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
)

UrlOpener = Callable[..., Any]


class FreeLLMClient:
    """Communicate with a FreeLLM-compatible HTTP endpoint.

    Provider-specific payload and response handling deliberately remains in
    this client so agents only need to depend on :class:`LLMGateway`.
    """

    def __init__(self, config: LLMConfig | None = None, opener: UrlOpener = urlopen) -> None:
        """Initialize the client with configuration and an optional HTTP opener."""

        self.config = config or LLMConfig.from_env()
        self._opener = opener

    def request(
        self,
        prompt: str,
        *,
        model: str | None = None,
        **parameters: Any,
    ) -> dict[str, Any]:
        """Send a completion request and return the decoded response payload.

        Args:
            prompt: The instruction sent to the language model.
            model: Optional model override.
            **parameters: Additional provider request parameters.

        Raises:
            LLMError: If communication or response processing fails.
        """

        if not prompt.strip():
            raise LLMResponseError("Prompt must not be empty")

        payload: dict[str, Any] = {
            "model": model or self.config.default_model,
            "prompt": prompt,
            **parameters,
        }
        return self._request_with_retries(payload)

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **parameters: Any,
    ) -> dict[str, Any]:
        """Send an OpenAI-compatible chat completion request.

        The request is posted to the standard ``/v1/chat/completions``
        endpoint (or ``LLM_CHAT_PATH`` when configured), so the gateway
        can be pointed at any OpenAI-compatible provider without
        rewriting GoalOS.

        Args:
            messages: Conversation messages as ``{role, content}`` dicts.
            model: Optional model override.
            temperature: Optional sampling temperature.
            max_tokens: Optional completion token cap.
            **parameters: Additional provider request parameters.

        Raises:
            LLMError: If communication or response processing fails.
        """

        if not messages:
            raise LLMResponseError("Messages must not be empty")

        payload: dict[str, Any] = {
            "model": model or self.config.default_model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        payload.update(parameters)
        return self._request_with_retries(payload, url=self.chat_url)

    @property
    def chat_url(self) -> str:
        """Full URL for OpenAI-compatible chat completions.

        Accepts a base URL that already names the endpoint
        (``.../chat/completions``), a versioned API root (``.../v1``, the
        form FreeLLMAPI documents), or a bare origin. ``LLM_CHAT_PATH``
        (default ``/v1/chat/completions``) supplies the missing path, and a
        ``v1`` segment is never duplicated when the base URL already ends
        with one.
        """
        base = self.config.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        path = self.config.chat_path.strip("/")
        if base.endswith("/v1") and path.startswith("v1/"):
            path = path[len("v1/"):]
        return f"{base}/{path}"

    def _request_with_retries(
        self, payload: Mapping[str, Any], *, url: str | None = None
    ) -> dict[str, Any]:
        """Send a request, retrying transient connection failures."""

        attempts = self.config.max_retries + 1
        last_error: LLMError | None = None
        for _ in range(attempts):
            try:
                return self._send_request(payload, url=url)
            except (LLMTimeoutError, LLMConnectionError) as error:
                last_error = error
        assert last_error is not None
        raise last_error

    def _send_request(
        self, payload: Mapping[str, Any], *, url: str | None = None
    ) -> dict[str, Any]:
        """Perform one HTTP request and decode its JSON response."""

        request = Request(
            url or self.config.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.config.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            if error.code in {401, 403}:
                raise LLMAuthenticationError("Language-model authentication failed") from error
            raise LLMResponseError(f"Language-model service returned HTTP {error.code}") from error
        except TimeoutError as error:
            raise LLMTimeoutError("Language-model request timed out") from error
        except URLError as error:
            if isinstance(error.reason, socket.timeout):
                raise LLMTimeoutError("Language-model request timed out") from error
            raise LLMConnectionError("Could not connect to language-model service") from error
        except OSError as error:
            raise LLMConnectionError("Could not connect to language-model service") from error

        try:
            response_payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise LLMResponseError("Language-model service returned invalid JSON") from error
        if not isinstance(response_payload, dict):
            raise LLMResponseError("Language-model response must be a JSON object")
        return response_payload

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers, including authorization when configured."""

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers
