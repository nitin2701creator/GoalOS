"""Voice Conversation Engine for GoalOS.

Orchestrates the real-time AI voice conversation pipeline:
  Audio Input → STT → Memory Context → LLM → TTS → Audio Output

GoalOS remains the orchestration layer.
External providers handle speech/LLM compute.
KVM2 stays lightweight — no local speech models.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.voice_speech import (
    BaseSTTProvider,
    BaseTTSProvider,
    VoiceSpeechConfig,
    get_speech_config,
    get_stt_provider,
    get_tts_provider,
)

# Lazy import to avoid circular dependencies
_provider_factory = None


def _get_provider_factory():
    global _provider_factory
    if _provider_factory is None:
        from app.llm.provider_factory import ProviderFactory
        _provider_factory = ProviderFactory
    return _provider_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation context
# ---------------------------------------------------------------------------


class VoiceConversationContext:
    """Context for a single voice conversation turn.

    Carries STT result, memory context, and conversation history
    between the STT, LLM, and TTS stages.
    """

    def __init__(
        self,
        *,
        call_id: int | None = None,
        destination_number: str = "",
        caller_number: str = "",
        language: str = "en",
        conversation_id: str | None = None,
    ) -> None:
        self.call_id = call_id
        self.destination_number = destination_number
        self.caller_number = caller_number
        self.language = language
        self.conversation_id = conversation_id

        # STT result
        self.transcribed_text: str = ""
        self.transcription_confidence: float = 0.0
        self.transcription_words: list[dict[str, Any]] = []

        # Memory context
        self.memory_context: str = ""
        self.relevant_facts: list[str] = []

        # LLM result
        self.ai_response: str = ""
        self.ai_confidence: float = 0.8

        # TTS result
        self.audio_data: bytes = b""
        self.audio_duration_ms: int = 0

        # Conversation turn tracking
        self.turn_number: int = 0
        self.conversation_history: list[dict[str, str]] = []

        # Flags
        self.handoff_requested: bool = False
        self.handoff_reason: str = ""
        self.error: str = ""
        self.error_stage: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/metrics (no raw audio)."""
        return {
            "call_id": self.call_id,
            "language": self.language,
            "transcribed_text": self.transcribed_text[:200],
            "transcription_confidence": self.transcription_confidence,
            "ai_response": self.ai_response[:200],
            "ai_confidence": self.ai_confidence,
            "turn_number": self.turn_number,
            "handoff_requested": self.handoff_requested,
            "error": self.error,
            "error_stage": self.error_stage,
        }


# ---------------------------------------------------------------------------
# Conversation Engine
# ---------------------------------------------------------------------------


class VoiceConversationEngine:
    """Orchestrates real-time AI voice conversations.

    Pipeline per turn:
      1. Transcribe incoming audio (STT)
      2. Retrieve relevant GoalOS memory
      3. Generate AI response (LLM)
      4. Synthesize response to audio (TTS)
      5. Track conversation state

    Supports multilingual conversations and human handoff triggers.
    """

    def __init__(
        self,
        stt_provider: BaseSTTProvider | None = None,
        tts_provider: BaseTTSProvider | None = None,
        config: VoiceSpeechConfig | None = None,
    ) -> None:
        self._config = config or get_speech_config()
        self._stt = stt_provider or get_stt_provider(self._config)
        self._tts = tts_provider or get_tts_provider(self._config)

    @property
    def stt_configured(self) -> bool:
        return self._stt.name != "none"

    @property
    def tts_configured(self) -> bool:
        return self._tts.name != "none"

    def process_audio_input(
        self,
        context: VoiceConversationContext,
        audio_data: bytes,
        *,
        audio_format: str = "wav",
    ) -> VoiceConversationContext:
        """Process one turn of audio input through the full pipeline.

        STT → Memory → LLM → TTS
        """
        context.turn_number += 1

        # Stage 1: Transcribe audio
        context = self._transcribe(context, audio_data, audio_format)
        if context.error:
            return context

        # Check for human handoff trigger in transcription
        context = self._check_handoff_triggers(context)
        if context.handoff_requested:
            return context

        # Stage 2: Memory context
        context = self._retrieve_memory(context)

        # Stage 3: Generate AI response
        context = self._generate_response(context)
        if context.error:
            return context

        # Stage 4: Synthesize audio
        context = self._synthesize(context)

        # Update conversation history
        context.conversation_history.append({
            "role": "user",
            "content": context.transcribed_text,
        })
        context.conversation_history.append({
            "role": "assistant",
            "content": context.ai_response,
        })

        return context

    def process_text_input(
        self,
        context: VoiceConversationContext,
        text: str,
    ) -> VoiceConversationContext:
        """Process text input (skip STT, go directly to Memory → LLM → TTS).

        Useful when text is available directly (e.g., from DTMF or API).
        """
        context.turn_number += 1
        context.transcribed_text = text
        context.transcription_confidence = 1.0

        # Check for human handoff trigger
        context = self._check_handoff_triggers(context)
        if context.handoff_requested:
            return context

        # Memory context
        context = self._retrieve_memory(context)

        # Generate AI response
        context = self._generate_response(context)
        if context.error:
            return context

        # Synthesize audio
        context = self._synthesize(context)

        # Update history
        context.conversation_history.append({
            "role": "user",
            "content": text,
        })
        context.conversation_history.append({
            "role": "assistant",
            "content": context.ai_response,
        })

        return context

    def _transcribe(
        self,
        context: VoiceConversationContext,
        audio_data: bytes,
        audio_format: str,
    ) -> VoiceConversationContext:
        """Stage 1: Transcribe audio to text."""
        if not audio_data:
            context.error = "No audio data provided"
            context.error_stage = "stt_input"
            return context

        result = self._stt.transcribe(
            audio_data,
            language=context.language,
            audio_format=audio_format,
        )

        context.transcribed_text = result.get("text", "")
        context.transcription_confidence = result.get("confidence", 0.0)
        context.transcription_words = result.get("words", [])

        # Use detected language if available
        detected_lang = result.get("language", "")
        if detected_lang:
            context.language = detected_lang

        if result.get("error"):
            context.error = f"STT error: {result['error']}"
            context.error_stage = "stt"

        return context

    def _check_handoff_triggers(
        self,
        context: VoiceConversationContext,
    ) -> VoiceConversationContext:
        """Check if the conversation should escalate to a human."""
        text = context.transcribed_text.lower().strip()

        # Explicit human request keywords
        handoff_keywords = [
            "human", "agent", "person", "speak to someone",
            "talk to someone", "real person", "not a bot",
            "call me", "operator", "representative", "manager",
            " supervisor", "transfer me",
        ]

        for keyword in handoff_keywords:
            if keyword in text:
                context.handoff_requested = True
                context.handoff_reason = f"caller_requested: '{keyword}'"
                return context

        # Low confidence triggers handoff after 2 consecutive low-confidence turns
        if context.transcription_confidence < 0.3 and context.turn_number > 1:
            context.handoff_requested = True
            context.handoff_reason = (
                f"low_confidence: {context.transcription_confidence:.2f}"
            )
            return context

        return context

    def _retrieve_memory(
        self,
        context: VoiceConversationContext,
    ) -> VoiceConversationContext:
        """Stage 2: Retrieve relevant GoalOS memory for this conversation."""
        try:
            from app.services.memory_service import MemoryService

            memory_service = MemoryService()

            # Search for relevant memories related to this caller
            entity = f"voice:{context.caller_number or context.destination_number}"
            memories = memory_service.search(
                query=context.transcribed_text,
                entity=entity,
                memory_types=None,  # Search all types
            )

            if memories:
                context.memory_context = "\n".join(
                    m.get("content", "") for m in memories[:5]
                )
                context.relevant_facts = [
                    m.get("content", "") for m in memories[:3]
                ]

        except Exception as exc:
            # Memory retrieval failure is non-fatal
            logger.debug("Voice memory retrieval failed: %s", exc)

        return context

    def _generate_response(
        self,
        context: VoiceConversationContext,
    ) -> VoiceConversationContext:
        """Stage 3: Generate AI response using GoalOS LLM."""
        try:
            # Build the conversation prompt
            system_prompt = self._build_system_prompt(context)
            messages = self._build_messages(context, system_prompt)

            # Generate response through GoalOS LLM
            ProviderFactory = _get_provider_factory()
            provider = ProviderFactory.create()
            response_text = provider.generate("\n".join(
                f"{m['role']}: {m['content']}" for m in messages
            ))

            if response_text:
                # Truncate for voice (limit response length for TTS)
                max_chars = 500  # ~30-40 seconds of speech
                if len(response_text) > max_chars:
                    response_text = response_text[:max_chars].rsplit(" ", 1)[0] + "."

                context.ai_response = response_text
                context.ai_confidence = 0.8
            else:
                # Fallback response
                context.ai_response = self._fallback_response(context)
                context.ai_confidence = 0.5

        except Exception as exc:
            logger.warning("Voice LLM generation failed: %s", exc)
            context.ai_response = self._fallback_response(context)
            context.ai_confidence = 0.3

        return context

    def _synthesize(
        self,
        context: VoiceConversationContext,
    ) -> VoiceConversationContext:
        """Stage 4: Synthesize AI response to audio."""
        if not context.ai_response:
            context.error = "No response to synthesize"
            context.error_stage = "tts_input"
            return context

        result = self._tts.synthesize(
            context.ai_response,
            language=context.language,
        )

        context.audio_data = result.get("audio_data", b"")
        context.audio_duration_ms = result.get("duration_ms", 0)

        if result.get("error"):
            context.error = f"TTS error: {result['error']}"
            context.error_stage = "tts"

        return context

    def _build_system_prompt(
        self,
        context: VoiceConversationContext,
    ) -> str:
        """Build the system prompt for the voice AI agent."""
        custom_prompt = __import__("os").getenv(
            "VOICE_AGENT_SYSTEM_PROMPT", ""
        )

        if custom_prompt:
            return custom_prompt

        parts = [
            "You are a helpful AI assistant on a phone call.",
            "Speak naturally and concisely.",
            "Keep responses under 3 sentences for voice delivery.",
            "Use simple, clear language.",
        ]

        if context.language and context.language != "en":
            lang_names = {
                "hi": "Hindi", "bn": "Bengali", "mr": "Marathi",
                "gu": "Gujarati", "ta": "Tamil", "te": "Telugu",
                "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi",
            }
            lang_name = lang_names.get(context.language, context.language)
            parts.append(
                f"Respond in {lang_name} if the caller speaks in {lang_name}."
            )

        if context.memory_context:
            parts.append(f"Relevant context: {context.memory_context[:500]}")

        return "\n".join(parts)

    def _build_messages(
        self,
        context: VoiceConversationContext,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        """Build message list for LLM."""
        messages = [{"role": "system", "content": system_prompt}]

        # Add conversation history (last 10 turns)
        for entry in context.conversation_history[-10:]:
            messages.append(entry)

        # Add current user message
        if context.transcribed_text:
            messages.append({
                "role": "user",
                "content": context.transcribed_text,
            })

        return messages

    def _fallback_response(
        self,
        context: VoiceConversationContext,
    ) -> str:
        """Generate a fallback response when LLM is unavailable."""
        if context.language == "hi":
            return (
                "Maaf kijiye, main abhi aapki madad nahi kar pa raha hoon. "
                "Kripya baad mein try karein."
            )
        return (
            "I apologize, I'm having trouble processing your request right now. "
            "Please try again in a moment."
        )

    def get_status(self) -> dict[str, Any]:
        """Get engine status for diagnostics."""
        return {
            "stt_provider": self._stt.name,
            "tts_provider": self._tts.name,
            "stt_configured": self.stt_configured,
            "tts_configured": self.tts_configured,
            "max_call_seconds": self._config.max_call_seconds,
            "default_language": self._config.default_language,
            "tts_voice": self._config.tts_voice,
        }
