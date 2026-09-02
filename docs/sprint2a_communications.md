# Sprint 2A — Communication Capability Foundation

## Overview

GoalOS now has a provider-neutral communications layer supporting outbound voice calls and SMS. This is the **transport foundation only** — it provides the plumbing for sending calls/SMS through Twilio or Plivo, without implementing an AI voice agent or conversation flow.

## Architecture

```
app/integrations/communications/
├── __init__.py           # Package init
├── models.py             # ProviderNeutralRequest, VoiceResponse, SMSResponse, etc.
├── base.py               # BaseCommunicationAdapter ABC
├── factory.py            # get_active_provider(), is_configured(), get_config_summary()
├── twilio_adapter.py     # Twilio implementation
└── plivo_adapter.py      # Plivo implementation

app/services/
└── communication_service.py  # Orchestrates policy → adapter → response

app/api/v1/
└── communications.py     # POST /voice-call, POST /sms, GET /status
```

## Supported Capabilities

| Capability | Action | Risk Level | Approval Required |
|---|---|---|---|
| `phone_voice_call` | Make an outbound voice call | MEDIUM | Yes |
| `sms_send` | Send an outbound SMS | MEDIUM | Yes |

Both capabilities route through the Action Policy engine (Sprint 1) before reaching the communication adapter.

## Provider Selection

Set the `COMMUNICATION_PROVIDER` environment variable:

```bash
# Use Twilio
export COMMUNICATION_PROVIDER=twilio

# Use Plivo
export COMMUNICATION_PROVIDER=plivo
```

If unset or empty, the system returns `INTEGRATION_NOT_CONFIGURED` — no crash, no error.

## Required Environment Variables

### Twilio

| Variable | Required | Description |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Yes | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio Auth Token |
| `TWILIO_FROM_NUMBER` | Yes | Twilio phone number (E.164 format) |

### Plivo

| Variable | Required | Description |
|---|---|---|
| `PLIVO_AUTH_ID` | Yes | Plivo Auth ID |
| `PLIVO_AUTH_TOKEN` | Yes | Plivo Auth Token |
| `PLIVO_FROM_NUMBER` | Yes | Plivo phone number (E.164 format) |

**Security:** Secrets are never exposed through API responses, logs, exceptions, or capability metadata. The `get_config_summary()` endpoint returns redacted values.

## API Endpoints

### POST /api/v1/communications/voice-call

Initiate an outbound voice call.

```json
{
  "to_number": "+15551234567",
  "message": "Hello from GoalOS",
  "caller_number": "+15559876543"
}
```

**Response:**
```json
{
  "status": "queued",
  "provider": "twilio",
  "provider_message_id": "CA...",
  "destination": "+15551234567",
  "caller": "+15559876543",
  "message_preview": "Hello from GoalOS",
  "error": null
}
```

### POST /api/v1/communications/sms

Send an outbound SMS.

```json
{
  "to_number": "+15551234567",
  "message": "Your order is ready",
  "sender_number": "+15559876543"
}
```

### GET /api/v1/communications/status

Returns provider configuration summary (secrets redacted).

```json
{
  "provider": "twilio",
  "is_configured": true,
  "account_id": "AC...****",
  "auth_token": "****",
  "from_number": "+1...****"
}
```

## Adding a New Provider

1. Create `app/integrations/communications/my_adapter.py`
2. Subclass `BaseCommunicationAdapter`
3. Implement `make_voice_call()` and `send_sms()`
4. Register in `_PROVIDER_CLASSES` in `factory.py`
5. Set `COMMUNICATION_PROVIDER=my_provider`

```python
from app.integrations.communications.base import BaseCommunicationAdapter

class MyAdapter(BaseCommunicationAdapter):
    def _get_credentials(self) -> dict[str, str]:
        return {
            "auth_id": os.getenv("MY_AUTH_ID", ""),
            "auth_token": os.getenv("MY_AUTH_TOKEN", ""),
            "from_number": os.getenv("MY_FROM_NUMBER", ""),
        }

    def make_voice_call(self, request):
        # Implement API call
        ...

    def send_sms(self, request):
        # Implement API call
        ...
```

## Testing

All tests use mocks — no real API calls.

```bash
# Run communication-specific tests
python -m pytest tests/test_communications.py -v

# Run full suite
python -m pytest
```

## What This Sprint Does NOT Include

- AI voice agent / conversation flow
- WhatsApp messaging (separate sprint)
- Inbound call handling
- SMS receive/webhook
- Call recording/transcription
- Twilio Media Streams
- Plivo Real-time API
- Conversation memory during calls
- Billing/cost tracking

These are planned for Sprint 2B and later.
