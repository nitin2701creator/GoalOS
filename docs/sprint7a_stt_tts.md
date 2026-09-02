# Sprint 7A — Real-Time STT/TTS

## Overview

Turns the existing outbound voice call into a real-time AI voice conversation.
GoalOS remains the orchestration layer — external providers handle speech/LLM compute.

## Architecture

```
Caller speaks
    ↓
Audio Stream (WebRTC/SIP/WebSocket)
    ↓
STT Provider (Deepgram)
    ↓
Text + Confidence + Language
    ↓
GoalOS Voice Conversation Engine
    ↓
Memory Retrieval (GoalOS Memory Service)
    ↓
LLM Response Generation (GoalOS LLM Provider)
    ↓
TTS Provider (Deepgram Aura)
    ↓
Audio Stream → Caller
```

## Providers

### STT — Deepgram Nova 2

| Feature | Support |
|---|---|
| Batch transcription | ✅ REST API |
| Streaming (WebSocket) | Planned Sprint 7B |
| Auto language detection | ✅ |
| Word-level timestamps | ✅ |
| Smart formatting | ✅ |
| Indian languages | ✅ Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam |

### TTS — Deepgram Aura

| Feature | Support |
|---|---|
| Text-to-speech | ✅ REST API |
| Streaming synthesis | Planned Sprint 7B |
| Multiple voices | ✅ 10 voices |
| Indian language TTS | Limited (Hindi supported) |
| Low latency | ~200-500ms per utterance |

## Files Created

| File | Purpose |
|---|---|
| `app/services/voice_speech.py` | STT/TTS provider abstractions, Deepgram adapters, config |
| `app/services/voice_conversation.py` | Voice conversation engine (STT → Memory → LLM → TTS) |
| `tests/test_voice_speech.py` | 70 mocked tests |

## Files Modified

| File | Change |
|---|---|
| `app/services/voice_service.py` | Integrated speech providers, added conversation endpoints |
| `app/api/v1/communications.py` | Added voice speech status + conversation API endpoints |

## Configuration

### Required Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `VOICE_STT_PROVIDER` | STT provider (`deepgram` or `none`) | `none` |
| `VOICE_TTS_PROVIDER` | TTS provider (`deepgram` or `none`) | `none` |
| `DEEPGRAM_API_KEY` | Deepgram API key | *(empty)* |
| `DEEPGRAM_API_URL` | Deepgram API base URL | `https://api.deepgram.com` |
| `VOICE_LANGUAGE` | Default voice language | `en` |
| `VOICE_TTS_VOICE` | Default TTS voice name | `asteria` |
| `VOICE_MAX_CALL_SECONDS` | Maximum call duration | `600` |
| `VOICE_STT_SAMPLE_RATE` | Audio sample rate | `16000` |
| `VOICE_STT_TIMEOUT` | STT request timeout (seconds) | `10` |
| `VOICE_TTS_TIMEOUT` | TTS request timeout (seconds) | `15` |
| `VOICE_AGENT_SYSTEM_PROMPT` | Custom AI agent system prompt | *(auto-generated)* |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/communications/voice/speech/status` | STT/TTS provider status |
| `POST` | `/api/v1/communications/voice/conversation/start` | Start AI voice conversation |
| `POST` | `/api/v1/communications/voice/conversation/turn` | Process audio turn |
| `POST` | `/api/v1/communications/voice/conversation/text` | Process text turn (skip STT) |
| `POST` | `/api/v1/communications/voice/conversation/end` | End conversation + memory |

## Voice Conversation Engine

### Pipeline per turn:

1. **Transcribe** — STT provider converts audio to text with confidence + language
2. **Handoff check** — Detect explicit human requests, low confidence, repeated failures
3. **Memory retrieval** — Fetch relevant GoalOS memories for this caller
4. **LLM response** — Generate AI response through GoalOS LLM provider
5. **Synthesize** — TTS provider converts response text to audio
6. **History** — Update conversation turn tracking

### Handoff Triggers

- Explicit keywords: "human", "agent", "operator", "real person", "speak to someone", etc.
- Low confidence: STT confidence < 0.3 after turn 1
- Repeated failures (future Sprint 7C)

### Fallback Behavior

- STT failure → empty text, engine continues
- LLM failure → fallback response ("I apologize...")
- TTS failure → error returned, caller can retry
- Memory failure → non-fatal, conversation continues

## Supported Languages

| Language | STT | TTS | Handoff Response |
|---|---|---|---|
| English | ✅ | ✅ | ✅ |
| Hindi | ✅ | Limited | ✅ |
| Bengali | ✅ | ❌ | ❌ |
| Tamil | ✅ | ❌ | ❌ |
| Telugu | ✅ | ❌ | ❌ |
| Kannada | ✅ | ❌ | ❌ |
| Malayalam | ✅ | ❌ | ❌ |
| Marathi | Fallback to Hindi | ❌ | ❌ |
| Gujarati | Fallback to Hindi | ❌ | ❌ |
| Punjabi | Fallback to Hindi | ❌ | ❌ |

## Cost Estimate

| Component | Cost per minute |
|---|---|
| Deepgram STT (Nova 2) | ~$0.0043/min |
| Deepgram TTS (Aura) | ~$0.013/min |
| LLM (via existing provider) | Variable |
| **Total (1 min conversation)** | **~$0.02-0.05** |

## KVM2 Impact

| Metric | Impact |
|---|---|
| Additional RAM | <2MB (no speech models) |
| Additional CPU | Negligible (HTTP calls only) |
| New processes | None |
| New databases | None |
| New services | None (cloud API) |
| Storage | None |

## Tests

| Suite | Tests | Status |
|---|---|---|
| `test_voice_speech.py` (new) | 70 | ✅ all pass |
| `test_voice.py` | 41 | ✅ all pass |
| **Full collectable suite** | **1119** | **✅ 0 failed** |

## Manual KVM Setup

| Step | Description |
|---|---|
| 1 | Create Deepgram account at https://console.deepgram.com |
| 2 | Generate API key |
| 3 | Set `VOICE_STT_PROVIDER=deepgram` in `.env` |
| 4 | Set `VOICE_TTS_PROVIDER=deepgram` in `.env` |
| 5 | Set `DEEPGRAM_API_KEY=<your-key>` in `.env` |
| 6 | Restart GoalOS container |

## Remaining Limitations

| Limitation | Impact | Mitigation |
|---|---|---|
| No WebSocket streaming | Full audio must be received before processing | Batch mode sufficient for MVP |
| Limited Indian TTS | Only Hindi for non-English TTS | Use provider-native TTS for calls |
| No incoming call routing | Cannot receive inbound calls | Sprint 7B |
| No real-time audio streaming | Audio buffers before/after each turn | Sprint 7B adds WebSocket |

## Recommended Next Sprint

- **Sprint 7B**: WebSocket streaming for real-time STT/TTS
- **Sprint 7C**: Incoming call handling + operator transfer
- **Sprint 7D**: Voice-based human handoff with live operator
