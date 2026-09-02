# Sprint 2 — Communications Live-Ready

## Overview

GoalOS now has a production-ready provider-neutral communications layer supporting domestic + international voice calling and SMS through Twilio and Plivo. The system features primary/fallback provider selection, E.164 number normalization, retry logic, webhook status callbacks, structured error normalization, and communication metrics for capacity planning.

This is the **transport foundation only** — it provides the plumbing for sending calls/SMS, without implementing an AI voice agent or conversation flow.

## Architecture

```
app/integrations/communications/
├── __init__.py
├── models.py               # Request/Response models, E.164 normalization, StatusEvent, redact_credentials
├── base.py                 # BaseCommunicationAdapter ABC (with parse_webhook)
├── factory.py              # get_active_provider(), get_provider_chain(), primary/fallback
├── twilio_adapter.py       # Twilio REST API (retry, error normalization, webhook parsing)
└── plivo_adapter.py        # Plivo REST API (retry, error normalization, webhook parsing)

app/services/
└── communication_service.py  # Orchestration: policy → provider chain → fallback → metrics

app/api/v1/
└── communications.py       # POST /voice-call, /sms, /webhook, GET /status, /metrics
```

## Supported Capabilities

| Capability | Action | Risk Level | Approval Required |
|---|---|---|---|
| `phone_voice_call` | Make an outbound voice call | MEDIUM | Yes |
| `sms_send` | Send an outbound SMS | MEDIUM | Yes |

Both capabilities route through the Action Policy engine before reaching the communication adapter.

## Provider Selection (Primary/Fallback)

```bash
# Sprint 2 primary/fallback (recommended)
COMMUNICATION_PRIMARY_PROVIDER=plivo
COMMUNICATION_FALLBACK_PROVIDER=twilio

# Legacy single-provider (still supported, takes precedence)
COMMUNICATION_PROVIDER=twilio
```

**Resolution order:**
1. If `COMMUNICATION_PROVIDER` is set → use that provider only (no fallback)
2. If `COMMUNICATION_PRIMARY_PROVIDER` is set → use primary, then fallback if configured
3. If neither is set → `INTEGRATION_NOT_CONFIGURED`

If the primary provider returns `NOT_CONFIGURED` (missing credentials), the system automatically tries the fallback provider. If the primary returns a real error (e.g., API failure), the fallback is still attempted for network/5xx errors.

## E.164 Number Normalization

All destination and source numbers are normalized to E.164 format before API calls:

| Input | Output | Notes |
|---|---|---|
| `+15551234567` | `+15551234567` | Already E.164 |
| `15551234567` | `+15551234567` | US without `+` |
| `5551234567` | `+15551234567` | US local (10 digits) |
| `+919876543210` | `+919876543210` | India, already E.164 |
| `+447911123456` | `+447911123456` | UK, already E.164 |
| `+1-555-123-4567` | `+15551234567` | Strips dashes/spaces |

If normalization fails, the adapter returns `INVALID_DESTINATION` without making an API call.

## Required Environment Variables

### Twilio

| Variable | Required | Description |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Yes | Twilio Account SID |
| `TWILIO_AUTH_TOKEN` | Yes | Twilio Auth Token |
| `TWILIO_FROM_NUMBER` | Yes | Twilio phone number (E.164) |

### Plivo

| Variable | Required | Description |
|---|---|---|
| `PLIVO_AUTH_ID` | Yes | Plivo Auth ID |
| `PLIVO_AUTH_TOKEN` | Yes | Plivo Auth Token |
| `PLIVO_FROM_NUMBER` | Yes | Plivo phone number (E.164) |

### Provider Selection

| Variable | Required | Description |
|---|---|---|
| `COMMUNICATION_PRIMARY_PROVIDER` | No | Primary: `plivo` or `twilio` |
| `COMMUNICATION_FALLBACK_PROVIDER` | No | Fallback: `twilio` or `plivo` |
| `COMMUNICATION_PROVIDER` | No | Legacy single-provider (overrides primary/fallback) |

**Security:** Secrets are never exposed through API responses, logs, exceptions, or status endpoints.

## API Endpoints

### POST /api/v1/communications/voice-call

```json
{
  "destination_number": "+919876543210",
  "caller_number": "+15559876543",
  "message": "Hello from GoalOS",
  "approved": true,
  "max_duration_seconds": 60,
  "callback_url": "https://example.com/webhook/call-status"
}
```

### POST /api/v1/communications/sms

```json
{
  "destination_number": "+15551234567",
  "sender_number": "+15559876543",
  "message": "Your order is ready",
  "approved": true,
  "callback_url": "https://example.com/webhook/sms-status"
}
```

### POST /api/v1/communications/webhook

Receives provider status callbacks (Twilio StatusCallback, Plivo URL).

### GET /api/v1/communications/status

Returns provider configuration status (secrets redacted), including fallback chain info.

### GET /api/v1/communications/metrics

Returns communication workload metrics (calls attempted/succeeded/failed, SMS sent/delivered/failed, fallback usage).

## Webhook Status Events

Adapters parse provider-specific webhook payloads into normalized `StatusEvent` objects:

| Event Type | Provider Status |
|---|---|
| `call.initiated` | initiated |
| `call.ringing` | ringing |
| `call.answered` | answered |
| `call.completed` | completed |
| `call.failed` | failed |
| `call.busy` | busy |
| `call.no_answer` | no-answer |
| `sms.queued` | queued |
| `sms.sent` | sent |
| `sms.delivered` | delivered |
| `sms.failed` | failed/undelivered |

## Retry Logic

Both adapters implement automatic retry with exponential backoff:
- **Max retries:** 2 (3 total attempts)
- **Retry on:** HTTP 5xx transient errors, network timeouts
- **Backoff:** 0.5s × attempt number (0.5s, 1.0s)
- **No retry on:** 4xx client errors, authentication failures

## Error Normalization

Provider-specific errors are normalized to a consistent format:

| Error Pattern | Status |
|---|---|
| `PROVIDER_ERROR [21218]: The number is busy` | `busy` |
| `PROVIDER_ERROR [21614]: Bad destination` | `failed` |
| `PROVIDER_EXCEPTION: Connection timeout` | `failed` |
| `INTEGRATION_NOT_CONFIGURED: credentials not set` | `no_provider` |
| `INVALID_DESTINATION: Cannot normalize to E.164` | `failed` |

## Communication Metrics

The system tracks lightweight in-memory metrics for the capacity advisor:

- `voice_calls_attempted` / `succeeded` / `failed`
- `sms_sent` / `succeeded` / `failed`
- `fallback_used` count
- `total_call_duration_seconds`
- `last_call_time` / `last_sms_time`
- `last_error`

The Capacity Advisor uses these to detect:
- High communication failure rates (>50%)
- Excessive fallback usage (>30% of calls)

## Capacity Advisor Integration

Communication metrics are included in the CapacityAdvisor assessment:

- **WARNING:** Failure rate >50% with ≥5 attempts, OR fallback used >30% of calls
- These indicate provider configuration issues or API problems

## Adding a New Provider

1. Create `app/integrations/communications/my_adapter.py`
2. Subclass `BaseCommunicationAdapter`
3. Implement `make_voice_call()`, `send_sms()`, and `parse_webhook()`
4. Register in `_PROVIDER_CLASSES` in `factory.py`

## Testing

All tests use mocks — no real API calls are made.

```bash
# Run communication tests only
python -m pytest tests/test_communications.py -v

# Run full suite
python -m pytest
```

## What This Sprint Does NOT Include

- AI voice agent / conversation flow
- WhatsApp messaging (separate sprint)
- Inbound call handling
- SMS receive/webhook processing (foundation only)
- Call recording/transcription
- Twilio Media Streams
- Plivo Real-time API
- Conversation memory during calls
- Billing/cost tracking
- Persistent event storage
- Call queuing/routing

## Activating Real Calls

1. Choose a provider (Plivo recommended for lower cost)
2. Create an account and get credentials
3. Set environment variables:
   ```bash
   COMMUNICATION_PRIMARY_PROVIDER=plivo
   PLIVO_AUTH_ID=your_auth_id
   PLIVO_AUTH_TOKEN=your_auth_token
   PLIVO_FROM_NUMBER=+15551234567
   ```
4. Test with the `/api/v1/communications/status` endpoint
5. Make a test call with `approved: true`

**Important:** Plivo and Twilio charge per call/SMS. Always test with mocked tests first.
