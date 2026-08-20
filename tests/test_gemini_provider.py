"""Tests for the Gemini LLM provider.

All tests use mocks — no real Gemini API calls are made.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock

import pytest

from app.llm.base_provider import provider_configured


# ---------------------------------------------------------------------------
# Import the provider (google-genai is installed in the test env)
# ---------------------------------------------------------------------------
from app.llm.gemini_provider import GeminiProvider, _DEFAULT_MODEL


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestGeminiConfiguration:
    """Environment-driven configuration."""

    def test_default_model_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()
        assert provider.default_model == _DEFAULT_MODEL

    def test_custom_model_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()
        assert provider.default_model == "gemini-2.5-pro"

    def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key-abc")
        provider = GeminiProvider()
        assert provider.api_key == "test-key-abc"

    def test_api_key_strips_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "  test-key-123  \n")
        provider = GeminiProvider()
        assert provider.api_key == "test-key-123"

    def test_empty_api_key_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "")
        provider = GeminiProvider()
        assert provider.api_key is None

    def test_whitespace_only_api_key_becomes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "   \n  ")
        provider = GeminiProvider()
        assert provider.api_key is None

    def test_health_check_true_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "real-key")
        provider = GeminiProvider()
        assert provider.health_check() is True

    def test_health_check_false_when_no_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()
        assert provider.health_check() is False


# ---------------------------------------------------------------------------
# Provider selection tests
# ---------------------------------------------------------------------------


class TestGeminiProviderSelection:
    """ProviderFactory selects GeminiProvider when LLM_PROVIDER=gemini."""

    def test_factory_returns_gemini_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        from app.llm.provider_factory import ProviderFactory

        provider = ProviderFactory.create()
        assert isinstance(provider, GeminiProvider)

    def test_factory_gemini_is_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        from app.llm.provider_factory import ProviderFactory

        provider = ProviderFactory.create()
        assert provider_configured(provider) is True

    def test_factory_gemini_not_configured_without_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from app.llm.provider_factory import ProviderFactory

        provider = ProviderFactory.create()
        assert provider_configured(provider) is False

    def test_default_provider_not_switched_to_gemini(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unset LLM_PROVIDER must NOT use Gemini."""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        from app.llm.provider_factory import ProviderFactory

        provider = ProviderFactory.create()
        assert not isinstance(provider, GeminiProvider)


# ---------------------------------------------------------------------------
# Request / generation tests (mocked)
# ---------------------------------------------------------------------------


class TestGeminiRequest:
    """GeminiProvider.request() with mocked google-genai client."""

    def test_successful_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        # Mock the client and its response
        mock_response = SimpleNamespace(
            text="Hello from Gemini",
            candidates=None,
        )
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        provider._client = mock_client

        result = provider.request("Say hello")

        assert result["response"] == "Hello from Gemini"
        assert result["model"] == _DEFAULT_MODEL
        assert result["prompt"] == "Say hello"
        mock_client.models.generate_content.assert_called_once_with(
            model=_DEFAULT_MODEL, contents="Say hello"
        )

    def test_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_response = SimpleNamespace(text="Pro response", candidates=None)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        provider._client = mock_client

        result = provider.request("Test", model="gemini-2.5-pro")

        assert result["model"] == "gemini-2.5-pro"
        mock_client.models.generate_content.assert_called_once_with(
            model="gemini-2.5-pro", contents="Test"
        )

    def test_empty_prompt_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        from app.ai.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError, match="empty"):
            provider.request("")

    def test_whitespace_only_prompt_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        from app.ai.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError, match="empty"):
            provider.request("   ")

    def test_empty_response_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_response = SimpleNamespace(text="", candidates=None)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        provider._client = mock_client

        from app.ai.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError, match="did not contain text"):
            provider.request("Hello")

    def test_missing_api_key_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        provider = GeminiProvider()

        with pytest.raises(ValueError, match="GEMINI_API_KEY is not configured"):
            provider.request("Hello")


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestGeminiErrorHandling:
    """Gemini API errors map to existing GoalOS AI exceptions."""

    def test_auth_error_maps_to_llm_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "API_KEY_INVALID: The provided API key is invalid"
        )
        provider._client = mock_client

        from app.ai.exceptions import LLMAuthenticationError

        with pytest.raises(LLMAuthenticationError, match="Gemini API key"):
            provider.request("Hello")

    def test_permission_error_maps_to_llm_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "Permission denied for this API key"
        )
        provider._client = mock_client

        from app.ai.exceptions import LLMAuthenticationError

        with pytest.raises(LLMAuthenticationError, match="Gemini API key"):
            provider.request("Hello")

    def test_timeout_maps_to_llm_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "Request timed out after 30s"
        )
        provider._client = mock_client

        from app.ai.exceptions import LLMError

        with pytest.raises(LLMError, match="timed out"):
            provider.request("Hello")

    def test_generic_error_maps_to_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "Connection refused"
        )
        provider._client = mock_client

        from app.ai.exceptions import LLMConnectionError

        with pytest.raises(LLMConnectionError, match="Gemini API request failed"):
            provider.request("Hello")

    def test_no_api_key_in_error_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """API key must never appear in error messages."""
        monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key-123")
        provider = GeminiProvider()

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Some error")
        provider._client = mock_client

        from app.ai.exceptions import LLMConnectionError

        with pytest.raises(LLMConnectionError) as exc_info:
            provider.request("Hello")

        assert "super-secret-key-123" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Candidate fallback tests
# ---------------------------------------------------------------------------


class TestGeminiCandidateFallback:
    """Tests for response parsing with candidates format."""

    def test_text_from_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When response.text is empty but candidates exist, extract from parts."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_part = SimpleNamespace(text="Candidate text")
        mock_content = SimpleNamespace(parts=[mock_part])
        mock_candidate = SimpleNamespace(content=mock_content)
        mock_response = SimpleNamespace(text="", candidates=[mock_candidate])
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        provider._client = mock_client

        result = provider.request("Hello")
        assert result["response"] == "Candidate text"

    def test_empty_candidates_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both text and candidates are empty, raise."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        provider = GeminiProvider()

        mock_candidate = SimpleNamespace(content=None)
        mock_response = SimpleNamespace(text="", candidates=[mock_candidate])
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        provider._client = mock_client

        from app.ai.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError, match="did not contain text"):
            provider.request("Hello")
