# Sprint 3 — WhatsApp Capability for GoalOS

## Overview

GoalOS now has a first-class WhatsApp capability with a provider-neutral interface. OpenWA (self-hosted WhatsApp Web automation) is the initial adapter. The architecture supports adding Meta WhatsApp Cloud API as a future production adapter without changing business logic.

## Architecture

```
app/integrations/whatsapp/
├── __init__.py           # Package init
├── models.py             # Provider-neutral request/response/status models
├── base.py               # BaseWhatsAppAdapter ABC
├── factory.py            # get_active_provider(), is_configured()
└── openwa_adapter.py     # OpenWA REST API adapter

app/db/models/
└── whatsapp.py           # WhatsAppContact, WhatsAppConversation, WhatsAppMessage

app/repositories/
└── whatsapp_repository.py  # DB persistence for contacts/conversations/messages

app/services/
└── whatsapp_service.py    # Orchestration: policy → provider → DB → memory

app/api/v1/
└── whatsapp_api.py        # POST /send, /webhook, GET /status, /contacts, /conversations
```

## Capabilities Registered

| Capability | Category | Approval Required | Status |
|---|---|---|---|
| `whatsapp_send_message` | communication | Yes | Implemented |
| `whatsapp_send_media` | communication | Yes | Implemented |
| `whatsapp_receive_message` | communication | No | Implemented |
| `whatsapp_get_status` | communication | No | Implemented |

All outbound WhatsApp actions require the existing Action Policy approval flow.

## Provider Interface

The `BaseWhatsAppAdapter` ABC defines the contract:

```python
class BaseWhatsAppAdapter(abc.ABC):
    name: str
    
    @property
    def is_configured(self) -> bool: ...
    
    @abc.abstractmethod
    def send_message(self, request: SendMessageRequest) -> SendMessageResponse: ...
    
    @abc.abstractmethod
    def parse_webhook(self, payload: dict) -> WhatsAppWebhookEvent | None: ...
    
    def verify_webhook(self, payload: bytes, signature: str | None) -> bool: ...
    
    def get_status(self) -> dict: ...
```

To add Meta WhatsApp Cloud API later:

1. Create `app/integrations/whatsapp/meta_adapter.py`
2. Subclass `BaseWhatsAppAdapter`
3. Implement `send_message()`, `parse_webhook()`, `verify_webhook()`
4. Register in `_PROVIDER_CLASSES` in `factory.py`

## OpenWA Adapter

OpenWA (https://github.com/rmyndharis/OpenWA) is a self-hosted WhatsApp Web automation library.

### OpenWA Deployment Architecture

```
GoalOS FastAPI (this app)
    ↓ HTTP REST API
OpenWA Process (separate container/service)
    ↓ WhatsApp Web protocol
WhatsApp
```

OpenWA runs as a **separate service**. GoalOS communicates with it via its REST API — never embedding the OpenWA runtime directly. This keeps GoalOS lightweight and avoids embedding a heavyweight WhatsApp Web session.

### OpenWA Requirements

- OpenWA must be running as a separate service (Docker container or process)
- The OpenWA REST API must be accessible from GoalOS (same network or localhost)
- A WhatsApp session must be authenticated in OpenWA

## Database Models

### WhatsAppContact
- `provider`: which provider (openwa, meta_cloud)
- `external_id`: provider-assigned contact ID
- `phone_number`: E.164 formatted
- `name`, `profile_pic_url`, `is_business`, `last_seen_at`

### WhatsAppConversation
- `provider`, `external_conversation_id`
- `contact_id` (FK → WhatsAppContact)
- `direction` (inbound/outbound)
- `message_count`, `is_active`, `last_message_at`

### WhatsAppMessage
- `provider`, `external_message_id` (unique)
- `conversation_id` (FK → WhatsAppConversation)
- `direction`, `media_type` (text/image/video/audio/document)
- `content`, `media_url`, `caption`
- `status` (pending/sent/delivered/read/failed)
- `error_code`, `error_message`
- `sent_at`, `delivered_at`, `read_at`

## Memory Integration

WhatsApp conversations automatically feed the GoalOS memory system:

```
WhatsApp message received/sent
    ↓
WhatsApp service creates MemoryRecord
    ↓
Memory type: CONVERSATION
Entity: "whatsapp:ContactName"
Source: "whatsapp:openwa"
    ↓
Memory service stores in DB
    ↓
Later recallable: "What did we discuss with this customer?"
```

Each inbound/outbound message creates a memory record with:
- `memory_type`: CONVERSATION
- `entity`: `whatsapp:{contact_name}`
- `content`: `[WhatsApp inbound] Hello from customer`
- `importance`: 0.6
- `source`: `whatsapp:openwa`

## Webhook Flow

```
WhatsApp → OpenWA → GoalOS /api/v1/whatsapp/webhook
    ↓
Provider adapter parses payload → WhatsAppWebhookEvent
    ↓
WhatsApp service processes event:
  - MESSAGE_RECEIVED → create DB record + memory
  - MESSAGE_DELIVERED → update message status
  - MESSAGE_READ → update message status
  - MESSAGE_FAILED → update message status with error
```

## Required Environment Variables

### OpenWA (initial provider)

| Variable | Required | Description |
|---|---|---|
| `WHATSAPP_PROVIDER` | Yes | Set to `openwa` |
| `OPENWA_API_URL` | Yes | Base URL of OpenWA REST API |
| `OPENWA_AUTH_TOKEN` | No | Authentication token |
| `OPENWA_WEBHOOK_SECRET` | No | HMAC-SHA256 secret for webhook verification |

### Meta WhatsApp Cloud API (future adapter)

| Variable | Required | Description |
|---|---|---|
| `WHATSAPP_META_ACCESS_TOKEN` | Yes | Meta Business API token |
| `WHATSAPP_META_PHONE_NUMBER_ID` | Yes | Phone number ID |
| `WHATSAPP_META_BUSINESS_ACCOUNT_ID` | Yes | Business account ID |
| `WHATSAPP_META_VERIFY_TOKEN` | Yes | Webhook verification token |

## API Endpoints

### POST /api/v1/whatsapp/send

Send an outbound WhatsApp message.

```json
{
  "destination_number": "+919876543210",
  "message": "Hello from GoalOS",
  "media_url": null,
  "media_type": "text",
  "approved": true
}
```

### POST /api/v1/whatsapp/webhook

Receive provider webhook events. Validates signature when configured.

### GET /api/v1/whatsapp/status

Provider connection status (no secrets exposed).

### GET /api/v1/whatsapp/contacts

List WhatsApp contacts with pagination.

### GET /api/v1/whatsapp/conversations

List conversations with optional contact_id and active_only filters.

### GET /api/v1/whatsapp/conversations/{id}/messages

List messages in a conversation.

## Security

- Never logs: tokens, webhook secrets, session credentials
- Uses existing `redact_whatsapp_config()` for all status/config responses
- Webhook signature verification via HMAC-SHA256 (when secret configured)
- All outbound actions require Action Policy approval
- E.164 number normalization prevents injection

## Capacity Advisor Integration

WhatsApp workload metrics are tracked and exposed via:
- `/api/v1/whatsapp/status` — provider health
- The WhatsApp service tracks provider status for capacity advisor

## Testing

All tests use mocks — no real WhatsApp messages are sent.

```bash
# Run WhatsApp tests only
python -m pytest tests/test_whatsapp.py -v

# Run full suite
python -m pytest
```

## What This Sprint Does NOT Include

- AI conversational agent on WhatsApp
- WhatsApp Business API template messages
- WhatsApp groups management
- WhatsApp payment integration
- Multi-device session management
- Message queuing/retry for failed sends
- WhatsApp catalog/product listings
- Broadcast lists
- Meta Cloud API adapter (designed for, not implemented)

## Recommended Next Sprint

- **Sprint 4A**: Meta WhatsApp Cloud API adapter (production-grade)
- **Sprint 4B**: WhatsApp AI agent (auto-reply with GoalOS memory context)
- **Sprint 4C**: Template message support for business communications
