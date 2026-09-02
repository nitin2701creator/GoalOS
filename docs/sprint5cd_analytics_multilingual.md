# Sprint 5C+5D — WhatsApp Analytics & Multilingual

## Sprint 5C: Conversation Analytics

### Architecture

```
WhatsApp Webhook → Agent Pipeline → Analytics Service → SQLite
                                        ↓
                              WhatsAppAnalytics table
                                        ↓
                              GET /analytics/summary
                              GET /analytics/conversations
                              GET /analytics/conversations/{id}
```

### Tracked Metrics

| Metric | Description |
|---|---|
| `total_messages` | Total messages in conversation |
| `inbound_count` | Customer messages |
| `outbound_count` | Business messages |
| `ai_response_count` | Successful AI responses |
| `failed_response_count` | Failed AI responses |
| `avg_response_latency_ms` | Average AI response time |
| `handoff_count` | Number of handoffs |
| `ai_resolution_rate` | % of AI responses that succeeded (0-100) |
| `conversation_duration_seconds` | Time from first to last message |
| `resolution_status` | resolved / unresolved / escalated / pending |
| `detected_language` | Auto-detected language |

### Quality Metrics (from Summary)

- **AI Resolution Rate**: `ai_response / (ai_response + failed) * 100`
- **Handoff Rate**: `handoffs / conversations * 100`
- **Failed Response Rate**: `failed / (ai + failed) * 100`
- **Avg Response Time**: `total_latency / latency_samples`
- **Avg Conversation Length**: `total_messages / conversations`
- **Language Distribution**: Count per detected language
- **Resolution Breakdown**: Count per resolution status

### API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/whatsapp/analytics/summary` | Aggregate summary with date-range filtering |
| `GET` | `/api/v1/whatsapp/analytics/conversations` | Per-conversation analytics list |
| `GET` | `/api/v1/whatsapp/analytics/conversations/{id}` | Single conversation analytics |

### Date-Range Filtering

```bash
# All time
GET /api/v1/whatsapp/analytics/summary

# Last 7 days
GET /api/v1/whatsapp/analytics/summary?start_date=2026-08-19T00:00:00

# Specific range
GET /api/v1/whatsapp/analytics/summary?start_date=2026-08-01&end_date=2026-08-26

# Per contact
GET /api/v1/whatsapp/analytics/summary?contact_id=1
```

### DB Model

`whatsapp_analytics` table — one record per conversation, updated in-place.

---

## Sprint 5D: Multilingual Support

### Architecture

```
Inbound Message → Language Detection → Augmented System Prompt → LLM → Response
                      ↓
              WhatsAppAnalytics.detected_language
```

### Supported Languages

| Language | Script | Detection Method |
|---|---|---|
| English | Latin | Default |
| Hindi | Devanagari | Unicode range |
| Hinglish | Latin + Devanagari | Word markers + mixed scripts |
| Bengali | Bengali | Unicode range |
| Marathi | Devanagari | Common markers |
| Gujarati | Gujarati | Unicode range |
| Tamil | Tamil | Unicode range |
| Telugu | Telugu | Unicode range |
| Kannada | Kannada | Unicode range |
| Malayalam | Malayalam | Unicode range |
| Punjabi | Gurmukhi | Unicode range |

### Detection Method

1. **Character-range analysis**: Unicode script blocks identify the dominant script
2. **Hinglish detection**: Latin-script text with ≥2 common Hindi/Urdu words in Latin
3. **Marathi vs Hindi**: Devanagari text checked for Marathi-specific markers
4. **Confidence scoring**: Based on ratio of dominant-script characters

### Multilingual Response

The agent's system prompt is augmented with language instructions:
- "Respond in Hindi" for Hindi messages
- "Respond in Hinglish" for Hinglish messages
- No change for English messages
- Language detected and stored in analytics

### Prompt Augmentation Examples

**Hindi input** → System prompt gets:
```
IMPORTANT: The customer is writing in Hindi.
Respond in Hindi. Keep the same professional tone.
```

**Hinglish input** → System prompt gets:
```
IMPORTANT: The customer is writing in Hinglish (Hindi-English mix).
Respond in the same Hinglish style — mix Hindi and English naturally.
```

### Integration Points

- Language detection runs on every inbound message in the agent pipeline
- Detected language stored in `whatsapp_analytics.detected_language`
- System prompt augmented before LLM call
- No additional API calls for detection (pure character analysis)
- Memory context preserved across language switches

---

## KVM2 Resource Impact

- **No new processes** — runs inside GoalOS FastAPI
- **No new databases** — uses existing SQLite
- **No Redis/Kafka/Celery** — lightweight in-process tracking
- **One new DB table** — `whatsapp_analytics` (lightweight)
- **No external API calls** for language detection

## Testing

```bash
# Run analytics+multilingual tests
python -m pytest tests/test_whatsapp_analytics.py -v

# Run full suite
python -m pytest
```

All tests use mocks — no real WhatsApp messages or API calls.
