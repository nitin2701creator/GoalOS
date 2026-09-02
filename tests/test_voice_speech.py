"""Tests for Voice STT/TTS providers and Conversation Engine.

Comprehensive mocked tests for:
- STT provider selection and configuration
- TTS provider selection and configuration
- Deepgram STT adapter (mocked HTTP)
- Deepgram TTS adapter (mocked HTTP)
- Provider fallback
- Language selection and fallback
- Voice conversation engine pipeline
- STT → Memory → LLM → TTS flow
- Text input flow
- Human handoff triggers
- Conversation history
- Call duration limits
- Credential redaction
- Error handling
- Health checks

NO real API calls during tests.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.voice_speech import (
    VoiceSpeechConfig,
    BaseSTTProvider,
    BaseTTSProvider,
    DeepgramSTTProvider,
    DeepgramTTSProvider,
    NoopSTTProvider,
    NoopTTSProvider,
    get_stt_provider,
    get_tts_provider,
    get_voice_status,
    _deepgram_language_code,
)
from app.services.voice_conversation import (
    VoiceConversationContext,
    VoiceConversationEngine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def speech_config():
    """Return a test speech configuration."""
    return VoiceSpeechConfig()


@pytest.fixture
def deepgram_config():
    """Return config with Deepgram API key set."""
    with patch.dict("os.environ", {
        "VOICE_STT_PROVIDER": "deepgram",
        "VOICE_TTS_PROVIDER": "deepgram",
        "DEEPGRAM_API_KEY": "test-key-12345",
        "VOICE_LANGUAGE": "en",
        "VOICE_TTS_VOICE": "asteria",
        "VOICE_MAX_CALL_SECONDS": "300",
    }):
        yield VoiceSpeechConfig()


# ---------------------------------------------------------------------------
# 1. VoiceSpeechConfig
# ---------------------------------------------------------------------------


class TestVoiceSpeechConfig:
    def test_default_config(self, speech_config):
        assert speech_config.stt_provider == "none"
        assert speech_config.tts_provider == "none"
        assert speech_config.default_language == "en"
        assert speech_config.max_call_seconds == 600
        assert speech_config.stt_configured is False
        assert speech_config.tts_configured is False

    def test_configured_config(self, deepgram_config):
        assert deepgram_config.stt_provider == "deepgram"
        assert deepgram_config.tts_provider == "deepgram"
        assert deepgram_config.stt_configured is True
        assert deepgram_config.tts_configured is True

    def test_missing_key_not_configured(self):
        with patch.dict("os.environ", {
            "VOICE_STT_PROVIDER": "deepgram",
            "DEEPGRAM_API_KEY": "",
        }):
            cfg = VoiceSpeechConfig()
            assert cfg.stt_configured is False


# ---------------------------------------------------------------------------
# 2. Language Code Mapping
# ---------------------------------------------------------------------------


class TestLanguageCodeMapping:
    def test_english(self):
        assert _deepgram_language_code("en") == "en"

    def test_hindi(self):
        assert _deepgram_language_code("hi") == "hi"

    def test_bengali(self):
        assert _deepgram_language_code("bn") == "bn"

    def test_tamil(self):
        assert _deepgram_language_code("ta") == "ta"

    def test_telugu(self):
        assert _deepgram_language_code("te") == "te"

    def test_marathi_fallback(self):
        assert _deepgram_language_code("mr") == "hi"

    def test_gujarati_fallback(self):
        assert _deepgram_language_code("gu") == "hi"

    def test_punjabi_fallback(self):
        assert _deepgram_language_code("pa") == "hi"

    def test_unknown_fallback(self):
        assert _deepgram_language_code("xx") == "en"

    def test_empty_fallback(self):
        assert _deepgram_language_code("") == "en"


# ---------------------------------------------------------------------------
# 3. STT Providers
# ---------------------------------------------------------------------------


class TestNoopSTT:
    def test_transcribe_returns_empty(self):
        provider = NoopSTTProvider()
        result = provider.transcribe(b"audio-data", language="en")
        assert result["text"] == ""
        assert result["confidence"] == 0.0
        assert result["provider"] == "none"

    def test_health_check(self):
        provider = NoopSTTProvider()
        health = provider.health_check()
        assert health["status"] == "not_configured"


class TestDeepgramSTT:
    def test_not_configured(self):
        provider = DeepgramSTTProvider(VoiceSpeechConfig())
        assert provider.is_configured is False

    def test_configured(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        assert provider.is_configured is True

    def test_transcribe_empty_audio(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        result = provider.transcribe(b"")
        assert result["text"] == ""

    def test_transcribe_success(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        mock_response = json.dumps({
            "results": {
                "channels": [{
                    "alternatives": [{
                        "transcript": "hello world",
                        "confidence": 0.95,
                        "words": [
                            {"word": "hello", "confidence": 0.98, "start": 0.0, "end": 0.5},
                            {"word": "world", "confidence": 0.92, "start": 0.6, "end": 1.1},
                        ],
                    }],
                    "detected_language": "en",
                }],
            },
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("app.services.voice_speech.urllib.request.urlopen", return_value=mock_resp):
            result = provider.transcribe(b"fake-audio", language="en")

        assert result["text"] == "hello world"
        assert result["confidence"] == 0.95
        assert result["language"] == "en"
        assert len(result["words"]) == 2
        assert result["provider"] == "deepgram"

    def test_transcribe_http_error(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        import urllib.error
        with patch("app.services.voice_speech.urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(
                       url="", code=401, msg="Unauthorized",
                       hdrs=None, fp=None
                   )):
            result = provider.transcribe(b"fake-audio")
        assert result["text"] == ""
        assert result["error"] == "HTTP_401"

    def test_transcribe_network_error(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        with patch("app.services.voice_speech.urllib.request.urlopen",
                   side_effect=ConnectionError("timeout")):
            result = provider.transcribe(b"fake-audio")
        assert result["text"] == ""
        assert "timeout" in result["error"]

    def test_health_check_configured(self, deepgram_config):
        provider = DeepgramSTTProvider(deepgram_config)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("app.services.voice_speech.urllib.request.urlopen", return_value=mock_resp):
            health = provider.health_check()
        assert health["status"] == "healthy"

    def test_health_check_not_configured(self):
        provider = DeepgramSTTProvider(VoiceSpeechConfig())
        health = provider.health_check()
        assert health["status"] == "not_configured"


# ---------------------------------------------------------------------------
# 4. TTS Providers
# ---------------------------------------------------------------------------


class TestNoopTTS:
    def test_synthesize_returns_empty(self):
        provider = NoopTTSProvider()
        result = provider.synthesize("hello", language="en")
        assert result["audio_data"] == b""
        assert result["provider"] == "none"

    def test_list_voices(self):
        provider = NoopTTSProvider()
        assert provider.list_voices() == []


class TestDeepgramTTS:
    def test_not_configured(self):
        provider = DeepgramTTSProvider(VoiceSpeechConfig())
        assert provider.is_configured is False

    def test_configured(self, deepgram_config):
        provider = DeepgramTTSProvider(deepgram_config)
        assert provider.is_configured is True

    def test_synthesize_empty_text(self, deepgram_config):
        provider = DeepgramTTSProvider(deepgram_config)
        result = provider.synthesize("")
        assert result["audio_data"] == b""

    def test_synthesize_success(self, deepgram_config):
        provider = DeepgramTTSProvider(deepgram_config)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"fake-audio-bytes"
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("app.services.voice_speech.urllib.request.urlopen", return_value=mock_resp):
            result = provider.synthesize("Hello, how can I help?")

        assert result["audio_data"] == b"fake-audio-bytes"
        assert result["provider"] == "deepgram"
        assert result["duration_ms"] >= 0

    def test_synthesize_http_error(self, deepgram_config):
        provider = DeepgramTTSProvider(deepgram_config)
        import urllib.error
        with patch("app.services.voice_speech.urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(
                       url="", code=500, msg="Server Error",
                       hdrs=None, fp=None
                   )):
            result = provider.synthesize("Hello")
        assert result["audio_data"] == b""
        assert result["error"] == "HTTP_500"

    def test_list_voices(self, deepgram_config):
        provider = DeepgramTTSProvider(deepgram_config)
        voices = provider.list_voices()
        assert len(voices) == 10
        assert any(v["id"] == "asteria" for v in voices)


# ---------------------------------------------------------------------------
# 5. Provider Factories
# ---------------------------------------------------------------------------


class TestProviderFactories:
    def test_stt_default(self):
        provider = get_stt_provider()
        assert isinstance(provider, NoopSTTProvider)

    def test_tts_default(self):
        provider = get_tts_provider()
        assert isinstance(provider, NoopTTSProvider)

    def test_stt_deepgram(self, deepgram_config):
        provider = get_stt_provider(deepgram_config)
        assert isinstance(provider, DeepgramSTTProvider)

    def test_tts_deepgram(self, deepgram_config):
        provider = get_tts_provider(deepgram_config)
        assert isinstance(provider, DeepgramTTSProvider)


# ---------------------------------------------------------------------------
# 6. Voice Status
# ---------------------------------------------------------------------------


class TestVoiceStatus:
    def test_status_no_providers(self):
        status = get_voice_status()
        assert status["stt"]["configured"] is False
        assert status["tts"]["configured"] is False
        assert status["config"]["language"] == "en"

    def test_status_with_providers(self, deepgram_config):
        with patch("app.services.voice_speech._config", deepgram_config):
            status = get_voice_status()
        assert status["stt"]["provider"] == "deepgram"
        assert status["tts"]["provider"] == "deepgram"


# ---------------------------------------------------------------------------
# 7. VoiceConversationContext
# ---------------------------------------------------------------------------


class TestVoiceConversationContext:
    def test_creation(self):
        ctx = VoiceConversationContext(
            call_id=1,
            destination_number="+15551234567",
            caller_number="+15559876543",
            language="en",
        )
        assert ctx.call_id == 1
        assert ctx.turn_number == 0
        assert ctx.handoff_requested is False

    def test_to_dict(self):
        ctx = VoiceConversationContext(call_id=1, language="hi")
        d = ctx.to_dict()
        assert d["call_id"] == 1
        assert d["language"] == "hi"
        assert d["error"] == ""


# ---------------------------------------------------------------------------
# 8. VoiceConversationEngine — STT/LLM/TTS Pipeline
# ---------------------------------------------------------------------------


class TestVoiceConversationEngine:
    def test_engine_creation(self):
        engine = VoiceConversationEngine()
        assert engine.stt_configured is False
        assert engine.tts_configured is False

    def test_engine_with_providers(self, deepgram_config):
        stt = DeepgramSTTProvider(deepgram_config)
        tts = DeepgramTTSProvider(deepgram_config)
        engine = VoiceConversationEngine(
            stt_provider=stt,
            tts_provider=tts,
            config=deepgram_config,
        )
        assert engine.stt_configured is True
        assert engine.tts_configured is True

    def test_text_input_handoff_keyword(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx = engine.process_text_input(ctx, "I want to speak to a human")
        assert ctx.handoff_requested is True
        assert "human" in ctx.handoff_reason

    def test_text_input_low_confidence_handoff(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx.turn_number = 2
        ctx.transcription_confidence = 0.2
        # Need to simulate a STT result with low confidence
        # The _check_handoff_triggers checks context.transcription_confidence
        # which is set by STT, not by text input. For text input, confidence is 1.0.
        # So we test with a direct call to _check_handoff_triggers after setting low confidence
        ctx = engine._check_handoff_triggers(ctx)
        assert ctx.handoff_requested is True

    def test_text_input_stores_history(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx = engine.process_text_input(ctx, "hello")
        assert len(ctx.conversation_history) == 2
        assert ctx.conversation_history[0]["content"] == "hello"

    def test_text_input_fallback_on_llm_error(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        mock_factory = MagicMock()
        mock_provider = MagicMock()
        mock_provider.generate.return_value = None
        mock_factory.create.return_value = mock_provider
        with patch("app.services.voice_conversation._provider_factory", mock_factory):
            ctx = engine.process_text_input(ctx, "test message")
        assert ctx.ai_response != ""
        assert ctx.ai_confidence < 0.8

    def test_text_input_hindi_fallback(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="hi")
        mock_factory = MagicMock()
        mock_provider = MagicMock()
        mock_provider.generate.return_value = None
        mock_factory.create.return_value = mock_provider
        with patch("app.services.voice_conversation._provider_factory", mock_factory):
            ctx = engine.process_text_input(ctx, "test message")
        assert "Maaf kijiye" in ctx.ai_response

    def test_get_status(self):
        engine = VoiceConversationEngine()
        status = engine.get_status()
        assert "stt_provider" in status
        assert "tts_provider" in status
        assert "max_call_seconds" in status


# ---------------------------------------------------------------------------
# 9. Handoff Trigger Keywords
# ---------------------------------------------------------------------------


class TestHandoffTriggers:
    @pytest.mark.parametrize("keyword", [
        "human", "agent", "person", "speak to someone",
        "not a bot", "operator", "representative",
        "manager", "transfer me",
    ])
    def test_explicit_handoff_keywords(self, keyword):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx = engine.process_text_input(ctx, f"I want to talk to a {keyword}")
        assert ctx.handoff_requested is True
        assert keyword in ctx.handoff_reason

    def test_real_person_handoff(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx = engine.process_text_input(ctx, "I want to talk to a real person")
        assert ctx.handoff_requested is True
        assert "person" in ctx.handoff_reason

    def test_no_handoff_for_normal_message(self):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language="en")
        ctx = engine.process_text_input(ctx, "What is the weather today?")
        assert ctx.handoff_requested is False


# ---------------------------------------------------------------------------
# 10. Language Support
# ---------------------------------------------------------------------------


class TestLanguageSupport:
    @pytest.mark.parametrize("lang", [
        "en", "hi", "bn", "ta", "te", "kn", "ml",
    ])
    def test_language_passed_through(self, lang):
        engine = VoiceConversationEngine()
        ctx = VoiceConversationContext(call_id=1, language=lang)
        ctx = engine.process_text_input(ctx, "test")
        assert ctx.language == lang

    def test_language_detection_updates_context(self, deepgram_config):
        stt = DeepgramSTTProvider(deepgram_config)
        tts = NoopTTSProvider()
        engine = VoiceConversationEngine(
            stt_provider=stt,
            tts_provider=tts,
            config=deepgram_config,
        )

        mock_response = json.dumps({
            "results": {
                "channels": [{
                    "alternatives": [{
                        "transcript": "namaste",
                        "confidence": 0.9,
                        "words": [],
                    }],
                    "detected_language": "hi",
                }],
            },
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        ctx = VoiceConversationContext(call_id=1, language="en")
        mock_factory = MagicMock()
        mock_provider = MagicMock()
        mock_provider.generate.return_value = "Namaste!"
        mock_factory.create.return_value = mock_provider
        with patch("app.services.voice_speech.urllib.request.urlopen", return_value=mock_resp):
            with patch("app.services.voice_conversation._provider_factory", mock_factory):
                ctx = engine.process_audio_input(ctx, b"audio", audio_format="wav")

        assert ctx.language == "hi"


# ---------------------------------------------------------------------------
# 11. Credential Redaction
# ---------------------------------------------------------------------------


class TestCredentialRedaction:
    def test_api_key_not_in_status(self, deepgram_config):
        status = get_voice_status()
        status_str = json.dumps(status)
        assert "test-key-12345" not in status_str

    def test_api_key_not_in_error(self, deepgram_config):
        # Verify that error messages from provider exceptions don't leak API keys
        # The error field captures the exception string, so we test that the
        # provider itself never logs or exposes the key in its own error handling
        provider = DeepgramSTTProvider(deepgram_config)
        with patch("app.services.voice_speech.urllib.request.urlopen",
                   side_effect=Exception("Connection refused")):
            result = provider.transcribe(b"audio")
        # The provider should return a structured error without the API key
        assert "error" in result
        assert result["text"] == ""
        # Verify API key is not in the provider's own attributes
        assert provider._config.deepgram_api_key not in json.dumps(result)


# ---------------------------------------------------------------------------
# 12. Call Duration Limits
# ---------------------------------------------------------------------------


class TestCallDurationLimits:
    def test_configurable_limit(self):
        with patch.dict("os.environ", {"VOICE_MAX_CALL_SECONDS": "120"}):
            cfg = VoiceSpeechConfig()
        assert cfg.max_call_seconds == 120

    def test_default_limit(self):
        cfg = VoiceSpeechConfig()
        assert cfg.max_call_seconds == 600
