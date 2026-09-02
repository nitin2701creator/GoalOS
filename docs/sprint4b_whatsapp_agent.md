# Sprint 4B — WhatsApp AI Auto-Reply Agent

## Overview

GoalOS now has a production-ready AI conversation agent for WhatsApp. When enabled, inbound WhatsApp messages automatically trigger an AI response pipeline that uses GoalOS memory and the existing LLM abstraction.

## Architecture

```
WhatsApp webhook
    ↓
GoalOS /api/v1/whatsapp/webhook
    ↓
Provider adapter parses payload → WhatsAppWebhookEvent
    ↓
Auto-Reply Agent (if enabled):
    1. Idempotency check (deduplicate webhooks)
    2. Validate inbound message
    3. Persist inbound message to DB
    4. Retrieve relevant GoalOS memory for this contact
    5. Construct AI context (system prompt + memory + message)
    6. Generate response via GoalOS LLM provider
    7. Send response through WhatsApp provider
    8. Persist outbound message + memory
```

## Pipeline Details

### 1. Idempotency

Duplicate webhook deliveries are detected by message ID. The agent maintains an in-memory cache of recently processed message IDs (bounded to 10,000 entries, auto-evicts after 1 hour). Duplicate messages are acknowledged but not re-processed.

### 2. Memory Retrieval

For each inbound message, the agent retrieves relevant memory for the specific contact:

```python
entity = f"whatsapp:{contact_name}"
memory = search(entity, limit=5)
```

**Memory isolation**: Each contact's memory is scoped to their entity. Contact A's conversation history never appears in Contact B's context.

### 3. AI Context Construction

The LLM prompt is built from:

1. **System prompt** (configurable via `WHATSAPP_AGENT_SYSTEM_PROMPT`)
2. **Memory context** (recent inbound/outbound messages for this contact)
3. **Current customer message**

Example prompt structure:
```
You are a helpful AI assistant for GoalOS, responding via WhatsApp.
[... rules ...]

Recent conversation context:
Customer: Previous question
Assistant: Previous answer

Customer: Current message

Respond concisely (under 500 characters):
```

### 4. Response Generation

Uses the existing GoalOS LLM abstraction (`ProviderFactory.create()`). Supports any configured LLM provider (OpenAI-compatible, FreeLLM, Gemini).

**Fallback**: If the LLM is unavailable or not configured, returns a polite fallback message: "Thank you for your message! A team member will respond shortly."

### 5. Outbound Reply

The response is sent through the existing WhatsApp provider (OpenWA or Meta Cloud API) via `send_message()`. The auto-reply uses `has_approved_context=True` since reading/responding is automatic.

### 6. Memory Persistence

Both inbound and outbound messages are fed into the GoalOS memory system:

```python
# Inbound
MemoryRecord(
    entity="whatsapp:ContactName",
    content="[WhatsApp inbound] Customer message",
    memory_type=MemoryType.CONVERSATION,
    source="whatsapp:meta",
)

# Outbound  
MemoryRecord(
    entity="whatsapp:ContactName",
    content="[WhatsApp outbound] AI response",
    memory_type=MemoryType.CONVERSATION,
    source="whatsapp:meta",
)
```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `WHATSAPP_AUTO_REPLY_ENABLED` | No | `false` | Enable/disable auto-reply |
| `WHATSAPP_AGENT_SYSTEM_PROMPT` | No | Built-in default | Custom system prompt for AI |
| `WHATSAPP_PROVIDER` | Yes | — | `openwa` or `meta` |
| `LLM_PROVIDER` | Yes | `freellm` | LLM provider for responses |
| `LLM_BASE_URL` | Yes | — | LLM API endpoint |
| `LLM_MODEL` | Yes | — | Model to use |

### Enabling Auto-Reply

```bash
# In .env:
WHATSAPP_AUTO_REPLY_ENABLED=true
WHATSAPP_PROVIDER=meta
META_WHATSAPP_ACCESS_TOKEN=your_token
META_WHATSAPP_PHONE_NUMBER_ID=your_phone_id
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=http://host.docker.internal:3001/v1
LLM_MODEL=free-llm-small
```

## API Endpoints

### GET /api/v1/whatsapp/agent/status

Returns agent configuration status (no secrets):

```json
{
  "auto_reply_enabled": true,
  "llm_configured": true,
  "llm_provider": "OpenAICompatibleProvider",
  "system_prompt_length": 342,
  "recent_messages_cached": 0
}
```

### POST /api/v1/whatsapp/webhook

When `WHATSAPP_AUTO_REPLY_ENABLED=true`, inbound messages automatically trigger the AI response pipeline.

## Safety & Action Policy

### Automatic Actions (no approval needed)
- Reading inbound messages
- Generating AI responses
- Sending auto-replies

### Approval Required (existing Action Policy)
- Any consequential GoalOS action mentioned in a response
- Manual outbound messages via API
- Actions that modify external systems

The auto-reply agent never bypasses the Action Policy. If a customer asks the agent to perform an action (e.g., "send me an invoice"), the agent explains what it would do but does not execute it without human approval.

## Conversation Isolation

Each WhatsApp contact has isolated memory:

```
Contact A (Alice) → entity: "whatsapp:Alice" → memory: [Alice's messages]
Contact B (Bob)   → entity: "whatsapp:Bob"   → memory: [Bob's messages]
```

Alice's conversation history is never included in Bob's LLM context, and vice versa.

## LLM Fallback

If the LLM provider is unavailable, unconfigured, or returns an empty response, the agent returns a polite fallback:

> "Thank you for your message! A team member will respond shortly. If this is urgent, please call our support line."

This ensures customers always receive a response even when AI is down.

## Testing

```bash
# Run agent tests only
python -m pytest tests/test_whatsapp_agent.py -v

# Run all WhatsApp tests (Sprint 3 + 4A + 4B)
python -m pytest tests/test_whatsapp.py tests/test_whatsapp_meta.py tests/test_whatsapp_agent.py -v

# Run full suite
python -m pytest
```

## Security

- No real WhatsApp messages sent during tests
- No real LLM calls made during tests
- Memory isolation enforced per-contact
- Webhook signature validation preserved
- Action Policy preserved for all outbound actions
- Credentials never logged or exposed

## What This Sprint Does NOT Include

- Multi-turn conversation state management (beyond memory)
- WhatsApp template message support
- Media processing (images, documents)
- Human handoff/escalation workflow
- Conversation scoring/analytics
- A/B testing of responses
- Sentiment analysis
- Intent classification

## Recommended Next Sprint

- **Sprint 5A**: Human handoff — detect when AI should escalate to a human agent
- **Sprint 5B**: WhatsApp template messages for business communications
- **Sprint 5C**: Conversation analytics and response quality tracking
