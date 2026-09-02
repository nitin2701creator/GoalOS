"""STT and TTS provider abstractions for GoalOS voice pipeline.

Provider-neutral interfaces for speech-to-text and text-to-speech.
Implements Deepgram as the primary cloud provider.

Architecture:
  KVM2 = GoalOS orchestration only
  External providers = speech/LLM compute
  No local speech models unless demonstrably lightweight
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class VoiceSpeechConfig:
    """Configuration for voice speech providers."""

    def __init__(self) -> None:
        self.stt_provider: str = os.getenv("VOICE_STT_PROVIDER", "none").strip().lower()
        self.tts_provider: str = os.getenv("VOICE_TTS_PROVIDER", "none").strip().lower()
        self.default_language: str = os.getenv("VOICE_LANGUAGE", "en").strip()
        self.tts_voice: str = os.getenv("VOICE_TTS_VOICE", "asteria").strip()
        self.max_call_seconds: int = int(os.getenv("VOICE_MAX_CALL_SECONDS", "600"))
        self.stt_sample_rate: int = int(os.getenv("VOICE_STT_SAMPLE_RATE", "16000"))
        # Deepgram
        self.deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "").strip()
        self.deepgram_api_url: str = os.getenv(
            "DEEPGRAM_API_URL", "https://api.deepgram.com"
        ).strip()
        # Timeouts
        self.stt_timeout_seconds: float = float(os.getenv("VOICE_STT_TIMEOUT", "10"))
        self.tts_timeout_seconds: float = float(os.getenv("VOICE_TTS_TIMEOUT", "15"))

    @property
    def stt_configured(self) -> bool:
        return self.stt_provider not in ("none", "") and bool(self.deepgram_api_key)

    @property
    def tts_configured(self) -> bool:
        return self.tts_provider not in ("none", "") and bool(self.deepgram_api_key)


_config = VoiceSpeechConfig()


def get_speech_config() -> VoiceSpeechConfig:
    """Return the current speech configuration."""
    return _config


# ---------------------------------------------------------------------------
# STT Provider Abstraction
# ---------------------------------------------------------------------------

class BaseSTTProvider(ABC):
    """Abstract STT provider interface."""

    name: str = "base"

    @abstractmethod
    def transcribe(
        self,
        audio_data: bytes,
        *,
        language: str = "en",
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        """Transcribe audio to text.

        Returns:
            {
                "text": str,
                "confidence": float,
                "language": str,
                "duration_ms": int,
                "words": list[dict],
                "provider": str,
            }
        """
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Check provider availability."""
        ...


class DeepgramSTTProvider(BaseSTTProvider):
    """Deepgram cloud STT provider.

    Uses Deepgram REST API for audio transcription.
    Supports streaming via WebSocket (future) and batch via REST.
    """

    name = "deepgram"

    def __init__(self, config: VoiceSpeechConfig | None = None) -> None:
        self._config = config or get_speech_config()

    @property
    def is_configured(self) -> bool:
        return bool(self._config.deepgram_api_key)

    def transcribe(
        self,
        audio_data: bytes,
        *,
        language: str = "en",
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        """Transcribe audio via Deepgram REST API."""
        if not self.is_configured or not audio_data:
            return {
                "text": "",
                "confidence": 0.0,
                "language": language,
                "duration_ms": 0,
                "words": [],
                "provider": self.name,
            }

        start = time.monotonic()

        # Map language to Deepgram language code
        dg_lang = _deepgram_language_code(language)

        # Build request URL
        url = (
            f"{self._config.deepgram_api_url}/v1/listen"
            f"?model=nova-2"
            f"&language={dg_lang}"
            f"&smart_format=true"
            f"& punctuate=true"
            f"& paragraphs=true"
            f"&detect_language=true"
            f"&sample_rate={self._config.stt_sample_rate}"
        )

        try:
            req = urllib.request.Request(
                url,
                data=audio_data,
                method="POST",
                headers={
                    "Authorization": f"Token {self._config.deepgram_api_key}",
                    "Content-Type": f"audio/{audio_format}",
                },
            )

            with urllib.request.urlopen(
                req, timeout=self._config.stt_timeout_seconds
            ) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Extract results
            alternatives = body.get("results", {}).get("channels", [{}])[0].get(
                "alternatives", [{}]
            )
            if not alternatives:
                return {
                    "text": "",
                    "confidence": 0.0,
                    "language": language,
                    "duration_ms": elapsed_ms,
                    "words": [],
                    "provider": self.name,
                }

            best = alternatives[0]
            detected_lang = body.get("results", {}).get("channels", [{}])[0].get(
                "detected_language", language
            )

            # Extract word-level data
            words = []
            for w in best.get("words", []):
                words.append({
                    "word": w.get("word", ""),
                    "confidence": w.get("confidence", 0.0),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                })

            return {
                "text": best.get("transcript", ""),
                "confidence": best.get("confidence", 0.0),
                "language": detected_lang,
                "duration_ms": elapsed_ms,
                "words": words,
                "provider": self.name,
            }

        except urllib.error.HTTPError as exc:
            logger.warning("Deepgram STT HTTP error: %s", exc.code)
            return {
                "text": "",
                "confidence": 0.0,
                "language": language,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "words": [],
                "provider": self.name,
                "error": f"HTTP_{exc.code}",
            }
        except Exception as exc:
            logger.warning("Deepgram STT error: %s", exc)
            return {
                "text": "",
                "confidence": 0.0,
                "language": language,
                "duration_ms": int((time.monotonic() - start) * 1000),
                "words": [],
                "provider": self.name,
                "error": str(exc),
            }

    def health_check(self) -> dict[str, Any]:
        """Check Deepgram API key validity."""
        if not self.is_configured:
            return {"status": "not_configured", "provider": self.name}

        try:
            url = f"{self._config.deepgram_api_url}/v1/projects"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Token {self._config.deepgram_api_key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return {"status": "healthy", "provider": self.name}
        except Exception as exc:
            return {"status": "error", "provider": self.name, "error": str(exc)}

        return {"status": "unknown", "provider": self.name}


class NoopSTTProvider(BaseSTTProvider):
    """Fallback STT provider when none configured."""

    name = "none"

    def transcribe(
        self,
        audio_data: bytes,
        *,
        language: str = "en",
        audio_format: str = "wav",
    ) -> dict[str, Any]:
        return {
            "text": "",
            "confidence": 0.0,
            "language": language,
            "duration_ms": 0,
            "words": [],
            "provider": self.name,
        }

    def health_check(self) -> dict[str, Any]:
        return {"status": "not_configured", "provider": self.name}


# ---------------------------------------------------------------------------
# TTS Provider Abstraction
# ---------------------------------------------------------------------------

class BaseTTSProvider(ABC):
    """Abstract TTS provider interface."""

    name: str = "base"

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        voice: str | None = None,
        output_format: str = "wav",
    ) -> dict[str, Any]:
        """Synthesize text to audio.

        Returns:
            {
                "audio_data": bytes,
                "audio_url": str,
                "duration_ms": int,
                "format": str,
                "provider": str,
                "sample_rate": int,
            }
        """
        ...

    @abstractmethod
    def list_voices(self) -> list[dict[str, Any]]:
        """List available voices for this provider."""
        ...

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        """Check provider availability."""
        ...


class DeepgramTTSProvider(BaseTTSProvider):
    """Deepgram cloud TTS provider.

    Uses Deepgram TTS REST API for text-to-speech synthesis.
    Supports multiple voices and languages.
    """

    name = "deepgram"

    def __init__(self, config: VoiceSpeechConfig | None = None) -> None:
        self._config = config or get_speech_config()

    @property
    def is_configured(self) -> bool:
        return bool(self._config.deepgram_api_key)

    def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        voice: str | None = None,
        output_format: str = "wav",
    ) -> dict[str, Any]:
        """Synthesize text via Deepgram TTS API."""
        if not self.is_configured or not text:
            return {
                "audio_data": b"",
                "audio_url": "",
                "duration_ms": 0,
                "format": output_format,
                "provider": self.name,
                "sample_rate": self._config.stt_sample_rate,
            }

        start = time.monotonic()
        tts_voice = voice or self._config.tts_voice

        # Deepgram TTS endpoint
        url = f"{self._config.deepgram_api_url}/v1/speak"

        payload = json.dumps({
            "text": text,
            "model": "aura-asteria-en",
            "encoding": output_format,
            "sample_rate": self._config.stt_sample_rate,
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Token {self._config.deepgram_api_key}",
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(
                req, timeout=self._config.tts_timeout_seconds
            ) as resp:
                audio_data = resp.read()

            elapsed_ms = int((time.monotonic() - start) * 1000)

            return {
                "audio_data": audio_data,
                "audio_url": "",
                "duration_ms": elapsed_ms,
                "format": output_format,
                "provider": self.name,
                "sample_rate": self._config.stt_sample_rate,
            }

        except urllib.error.HTTPError as exc:
            logger.warning("Deepgram TTS HTTP error: %s", exc.code)
            return {
                "audio_data": b"",
                "audio_url": "",
                "duration_ms": int((time.monotonic() - start) * 1000),
                "format": output_format,
                "provider": self.name,
                "sample_rate": self._config.stt_sample_rate,
                "error": f"HTTP_{exc.code}",
            }
        except Exception as exc:
            logger.warning("Deepgram TTS error: %s", exc)
            return {
                "audio_data": b"",
                "audio_url": "",
                "duration_ms": int((time.monotonic() - start) * 1000),
                "format": output_format,
                "provider": self.name,
                "sample_rate": self._config.stt_sample_rate,
                "error": str(exc),
            }

    def list_voices(self) -> list[dict[str, Any]]:
        """Return known Deepgram Aura voices."""
        return [
            {"id": "asteria", "name": "Asteria", "language": "en", "gender": "female"},
            {"id": "luna", "name": "Luna", "language": "en", "gender": "female"},
            {"id": "stella", "name": "Stella", "language": "en", "gender": "female"},
            {"id": "athena", "name": "Athena", "language": "en", "gender": "female"},
            {"id": "hera", "name": "Hera", "language": "en", "gender": "female"},
            {"id": "orion", "name": "Orion", "language": "en", "gender": "male"},
            {"id": "arcas", "name": "Arcas", "language": "en", "gender": "male"},
            {"id": "perseus", "name": "Perseus", "language": "en", "gender": "male"},
            {"id": "angus", "name": "Angus", "language": "en", "gender": "male"},
            {"id": "orpheus", "name": "Orpheus", "language": "en", "gender": "male"},
        ]

    def health_check(self) -> dict[str, Any]:
        """Check Deepgram API key validity."""
        if not self.is_configured:
            return {"status": "not_configured", "provider": self.name}

        try:
            url = f"{self._config.deepgram_api_url}/v1/projects"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Token {self._config.deepgram_api_key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return {"status": "healthy", "provider": self.name}
        except Exception as exc:
            return {"status": "error", "provider": self.name, "error": str(exc)}

        return {"status": "unknown", "provider": self.name}


class NoopTTSProvider(BaseTTSProvider):
    """Fallback TTS provider when none configured."""

    name = "none"

    def synthesize(
        self,
        text: str,
        *,
        language: str = "en",
        voice: str | None = None,
        output_format: str = "wav",
    ) -> dict[str, Any]:
        return {
            "audio_data": b"",
            "audio_url": "",
            "duration_ms": 0,
            "format": output_format,
            "provider": self.name,
            "sample_rate": 0,
        }

    def list_voices(self) -> list[dict[str, Any]]:
        return []

    def health_check(self) -> dict[str, Any]:
        return {"status": "not_configured", "provider": self.name}


# ---------------------------------------------------------------------------
# Provider Factories
# ---------------------------------------------------------------------------

def get_stt_provider(config: VoiceSpeechConfig | None = None) -> BaseSTTProvider:
    """Get the configured STT provider."""
    cfg = config or get_speech_config()
    if cfg.stt_provider == "deepgram" and cfg.deepgram_api_key:
        return DeepgramSTTProvider(cfg)
    return NoopSTTProvider()


def get_tts_provider(config: VoiceSpeechConfig | None = None) -> BaseTTSProvider:
    """Get the configured TTS provider."""
    cfg = config or get_speech_config()
    if cfg.tts_provider == "deepgram" and cfg.deepgram_api_key:
        return DeepgramTTSProvider(cfg)
    return NoopTTSProvider()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Language code mapping for Deepgram
_DEEPGRAM_LANG_MAP: dict[str, str] = {
    "en": "en",
    "hi": "hi",
    "hinglish": "hi",  # Hindi closest match
    "bn": "bn",
    "mr": "hi",  # Marathi not supported, fallback to Hindi
    "gu": "hi",  # Gujarati not supported, fallback to Hindi
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "ml": "ml",
    "pa": "hi",  # Punjabi not supported, fallback to Hindi
}


def _deepgram_language_code(language: str) -> str:
    """Map GoalOS language code to Deepgram language code."""
    normalized = language.strip().lower()[:2]
    return _DEEPGRAM_LANG_MAP.get(normalized, "en")


def get_voice_status() -> dict[str, Any]:
    """Get voice STT/TTS provider status."""
    cfg = get_speech_config()
    stt = get_stt_provider(cfg)
    tts = get_tts_provider(cfg)

    return {
        "stt": {
            "provider": stt.name,
            "configured": cfg.stt_configured,
            "health": stt.health_check(),
        },
        "tts": {
            "provider": tts.name,
            "configured": cfg.tts_configured,
            "health": tts.health_check(),
            "voices": len(tts.list_voices()),
        },
        "config": {
            "language": cfg.default_language,
            "voice": cfg.tts_voice,
            "max_call_seconds": cfg.max_call_seconds,
            "sample_rate": cfg.stt_sample_rate,
        },
    }
