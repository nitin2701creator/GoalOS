# Sprint 5A — WhatsApp Human Handoff

## Architecture

```
Inbound WhatsApp Message
    ↓
Webhook → WhatsApp Agent
    ↓
Check Handoff State (should_block_ai_reply?)
    ├─ HUMAN_REQUESTED / HUMAN_ACTIVE → Block AI reply, skip processing
    └─ AI_ACTIVE → Continue
    ↓
Detect Escalation Trigger
    ├─ Explicit keyword → request_handoff()
    ├─ Low confidence × N → request_handoff()
    └─ No trigger → Generate AI response normally
    ↓
If escalated:
    1. Create HUMAN_REQUESTED handoff record
    2. Send brief acknowledgment to customer
    3. Expose conversation for human operator via API
    ↓
Human Operator:
    POST /api/v1/whatsapp/handoff/activate → HUMAN_ACTIVE
    POST /api/v1/whatsapp/handoff/resolve → RESOLVED
    POST /api/v1/whatsapp/handoff/resolve (return_to_ai=true) → AI_ACTIVE
```

## Conversation States

| State | AI Responds | Description |
|---|---|---|
| `ai_active` | ✅ Yes | Normal AI auto-reply mode |
| `human_requested` | ❌ No | Customer requested human; waiting for operator |
| `human_active` | ❌ No | Human operator has taken over |
| `resolved` | ✅ Yes (after return_to_ai) | Issue resolved; ready to return to AI |

## Escalation Triggers

### 1. Explicit Keywords
Messages containing these keywords trigger immediate escalation:

**Default keywords:**
- "human", "agent", "person", "someone"
- "speak to someone", "talk to someone"
- "call me", "real person", "operator"
- "manager", "supervisor", "escalate"
- "not a bot", "not a robot"

**Custom keywords** via environment variable:
```bash
WHATSAPP_HANDOFF_KEYWORDS=custom_word,another_word
```

### 2. Low Confidence
When AI confidence falls below threshold for consecutive messages:

```bash
WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD=0.3  # default
WHATSAPP_HANDOFF_MAX_FAILURES=3           # consecutive failures before escalation
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/whatsapp/handoffs` | List pending handoff requests |
| `GET` | `/api/v1/whatsapp/conversations/{id}/handoff` | Get handoff status + context |
| `POST` | `/api/v1/whatsapp/handoff/request` | Request human handoff |
| `POST` | `/api/v1/whatsapp/handoff/activate` | Human operator takes over |
| `POST` | `/api/v1/whatsapp/handoff/resolve` | Resolve handoff, optionally return to AI |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `WHATSAPP_HANDOFF_KEYWORDS` | (built-in list) | Comma-separated escalation keywords |
| `WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD` | `0.3` | Confidence below which escalation triggers |
| `WHATSAPP_HANDOFF_MAX_FAILURES` | `3` | Consecutive low-confidence responses before escalation |

## Database

New table: `whatsapp_handoffs`

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment ID |
| `conversation_id` | INTEGER FK | References `whatsapp_conversations.id` (unique) |
| `state` | ENUM | Current handoff state |
| `escalation_reason` | VARCHAR(256) | Why escalation was triggered |
| `escalation_detail` | TEXT | Additional context |
| `assigned_to` | VARCHAR(128) | Human operator name |
| `resolution_notes` | TEXT | How the issue was resolved |
| `requested_at` | DATETIME | When handoff was requested |
| `activated_at` | DATETIME | When human took over |
| `resolved_at` | DATETIME | When issue was resolved |
| `created_at` | DATETIME | Record creation time |
| `updated_at` | DATETIME | Last update time |

## How to Run Without Real WhatsApp

1. Set environment variables:
```bash
WHATSAPP_PROVIDER=meta
WHATSAPP_AUTO_REPLY_ENABLED=true
WHATSAPP_HANDOFF_KEYWORDS=human,agent
```

2. Start GoalOS
3. Send test webhook to `/api/v1/whatsapp/webhook`
4. Use API to manage handoffs

## How It Works

### Requesting Handoff
```bash
curl -X POST http://localhost:8000/api/v1/whatsapp/handoff/request \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": 1, "reason": "explicit_user_request"}'
```

### Activating Human
```bash
curl -X POST http://localhost:8000/api/v1/whatsapp/handoff/activate \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": 1, "assigned_to": "John Support"}'
```

### Getting Context
```bash
curl http://localhost:8000/api/v1/whatsapp/conversations/1/handoff
```

### Resolving
```bash
curl -X POST http://localhost:8000/api/v1/whatsapp/handoff/resolve \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": 1, "resolution_notes": "Issue fixed", "return_to_ai": true}'
```

## Security

- No credentials exposed in API responses
- Handoff records contain only operational metadata
- Conversation isolation preserved (each contact's handoff is separate)
- Action Policy still enforced for all outbound messages

## KVM Resource Impact

- **No new processes** — runs inside GoalOS FastAPI
- **No new databases** — uses existing SQLite
- **No Redis/Kafka/Celery** — in-memory failure tracking only
- **One new DB table** — `whatsapp_handoffs` (lightweight)

## Next Sprint

- Sprint 5B: WhatsApp template messages for business communications
- Sprint 5C: Conversation analytics and response quality tracking
- Sprint 5D: Multi-language handoff routing
