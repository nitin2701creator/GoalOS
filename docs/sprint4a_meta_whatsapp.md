# Sprint 4A — Meta WhatsApp Cloud API Provider

## Overview

GoalOS now supports two WhatsApp providers through the same provider-neutral interface:

```
WHATSAPP_PROVIDER=openwa          →  OpenWA (self-hosted WhatsApp Web)
WHATSAPP_PROVIDER=meta            →  Meta WhatsApp Cloud API (cloud-hosted)
```

The Meta adapter implements the same `BaseWhatsAppAdapter` interface as OpenWA. GoalOS business logic never needs to know which provider is active.

## Architecture

```
app/integrations/whatsapp/
├── __init__.py
├── models.py               # Provider-neutral request/response models
├── base.py                 # BaseWhatsAppAdapter ABC
├── factory.py              # Provider selection: WHATSAPP_PROVIDER env var
├── openwa_adapter.py       # OpenWA adapter (Sprint 3)
└── meta_adapter.py         # Meta WhatsApp Cloud API adapter (Sprint 4A)
```

### Meta Cloud API vs OpenWA

| Feature | OpenWA | Meta Cloud API |
|---|---|---|
| Hosting | Self-hosted (separate process) | Cloud-hosted (Meta servers) |
| Runtime requirement | Separate container/service | None — runs inside GoalOS |
| WhatsApp session | QR code scan (periodic) | Business account verified |
| Message cost | Free (WhatsApp Web) | Per-conversation billing |
| Reliability | Depends on WhatsApp Web session | Meta SLA |
| API stability | Unofficial (may break) | Official (versioned API) |
| Business features | Limited | Templates, catalogs, payments |
| Recommended for | Development/testing | Production |

## Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `WHATSAPP_PROVIDER` | Yes | Set to `meta` for Meta Cloud API |
| `META_WHATSAPP_ACCESS_TOKEN` | Yes (outbound) | Meta Business API access token |
| `META_WHATSAPP_PHONE_NUMBER_ID` | Yes (outbound) | Phone number ID from Meta dashboard |
| `META_WHATSAPP_BUSINESS_ACCOUNT_ID` | No | Business account ID (for health checks) |
| `META_WHATSAPP_VERIFY_TOKEN` | Yes (webhook) | Custom token for webhook verification |
| `META_WHATSAPP_APP_SECRET` | Yes (webhook sig) | App secret for HMAC signature validation |

### Variable Requirements by Operation

| Operation | Required Variables |
|---|---|
| Send text message | `ACCESS_TOKEN`, `PHONE_NUMBER_ID` |
| Send media message | `ACCESS_TOKEN`, `PHONE_NUMBER_ID` |
| Webhook verification (GET) | `VERIFY_TOKEN` |
| Webhook signature validation | `APP_SECRET` |
| Provider health check | `ACCESS_TOKEN`, `PHONE_NUMBER_ID` |
| Receive inbound messages | `PHONE_NUMBER_ID` (in webhook URL) |

### Setup Steps

1. **Create Meta Developer Account**: https://developers.facebook.com
2. **Create App**: Select "Business" type
3. **Add WhatsApp product**: In App Dashboard → Products → WhatsApp
4. **Get Phone Number**: WhatsApp → Getting Started → Phone Numbers
5. **Generate Access Token**: WhatsApp → Getting Started → Temporary access token (or System User token for production)
6. **Set Webhook**: WhatsApp → Configuration → Webhook → Callback URL + Verify Token
7. **Set App Secret**: Settings → Basic → App Secret

## Webhook Flow

### Meta Webhook Verification (GET)

When you register a webhook URL in Meta dashboard, Meta sends:

```
GET /api/v1/whatsapp/webhook
  ?hub.mode=subscribe
  &hub.verify_token=YOUR_VERIFY_TOKEN
  &hub.challenge=RANDOM_STRING
```

GoalOS validates `verify_token` against `META_WHATSAPP_VERIFY_TOKEN` and returns the challenge.

### Meta Webhook Events (POST)

Meta sends POST requests with this structure:

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "WABA_ID",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "..."},
        "messages": [...],  // inbound messages
        "statuses": [...]   // delivery status updates
      },
      "field": "messages"
    }]
  }]
}
```

GoalOS normalizes these into `WhatsAppWebhookEvent` objects that are identical to OpenWA events.

## Supported Message Types

| Type | Send | Receive | Notes |
|---|---|---|---|
| Text | ✅ | ✅ | Body text up to 4096 chars |
| Image | ✅ | ✅ | URL or media ID, optional caption |
| Video | ✅ | ✅ | URL or media ID, optional caption |
| Audio | ✅ | ✅ | URL or media ID, no caption |
| Document | ✅ | ✅ | URL or media ID, optional caption |
| Location | ❌ | ✅ | Lat/lng received, not sent |
| Contact | ❌ | ✅ | Contact vCard received |
| Sticker | ❌ | ❌ | Not supported in Cloud API v21 |

## Error Handling

| Meta Error Code | Meaning | GoalOS Status |
|---|---|---|
| 190 | Invalid/expired access token | FAILED |
| 100 | Invalid parameter | FAILED |
| 368 | Rate limit / blocked | FAILED |
| 131026 | Message undeliverable | FAILED |
| 131047 | Rate limit hit | FAILED |
| 131046 | Account flagged | FAILED |

All errors are normalized to `PROVIDER_ERROR [code]: message` format.

## Memory Integration

Identical to OpenWA — every inbound/outbound message creates a `MemoryRecord`:

```python
MemoryRecord(
    entity="whatsapp:ContactName",
    content="[WhatsApp inbound] Hello from customer",
    memory_type=MemoryType.CONVERSATION,
    source="whatsapp:meta",
)
```

## Security

- Tokens never logged, exposed in API responses, or stored in DB
- Webhook signature validated via HMAC-SHA256 (Meta's `X-Hub-Signature-256`)
- All outbound messages require Action Policy approval
- Credential redaction via existing `redact_whatsapp_config()`
- E.164 number normalization prevents injection

## Testing

```bash
# Run Meta adapter tests only
python -m pytest tests/test_whatsapp_meta.py -v

# Run all WhatsApp tests (OpenWA + Meta)
python -m pytest tests/test_whatsapp.py tests/test_whatsapp_meta.py -v

# Run full suite
python -m pytest
```

All tests use mocked HTTP — no real Meta API requests are made.

## Capacity Advisor Integration

Meta WhatsApp workload is tracked via the same lightweight metrics as OpenWA:
- Messages sent/received
- Failures
- Provider health status

## KVM2 Impact

- **No additional runtime process** — Meta Cloud API is cloud-hosted
- **No Redis/Kafka/Celery** — same in-process architecture
- **No additional database** — uses existing GoalOS SQLite
- **Minimal additional storage** — no media caching needed
- **One environment variable change** — `WHATSAPP_PROVIDER=meta`

## Provider Switching

To switch from OpenWA to Meta:

```bash
# In .env:
WHATSAPP_PROVIDER=meta
META_WHATSAPP_ACCESS_TOKEN=your_token
META_WHATSAPP_PHONE_NUMBER_ID=your_phone_id
META_WHATSAPP_VERIFY_TOKEN=your_verify_token
META_WHATSAPP_APP_SECRET=your_app_secret

# Remove or comment out OpenWA vars:
# WHATSAPP_PROVIDER=openwa
# OPENWA_API_URL=...
```

Restart GoalOS. All API endpoints continue working identically.

## Troubleshooting

| Issue | Solution |
|---|---|
| `INTEGRATION_NOT_CONFIGURED` | Check `WHATSAPP_PROVIDER=meta` and all `META_WHATSAPP_*` vars |
| `PROVIDER_ERROR [190]` | Access token expired — regenerate in Meta dashboard |
| `PROVIDER_ERROR [368]` | Rate limited — wait or reduce send frequency |
| Webhook not receiving | Check callback URL, verify token, and app review status |
| Webhook signature invalid | Ensure `META_WHATSAPP_APP_SECRET` matches Meta dashboard |
| Messages not delivered | Check phone number quality rating in Meta dashboard |

## Remaining Manual Setup (KVM)

1. Create Meta Developer account and app
2. Enable WhatsApp Cloud API product
3. Add and verify a phone number
4. Generate a permanent access token (System User token)
5. Configure webhook URL: `http://YOUR_KVM_IP:8000/api/v1/whatsapp/webhook`
6. Set verify token and app secret in GoalOS `.env`
7. Submit app for Meta review (required for production sending)

## Recommended Next Sprint

- **Sprint 4B**: WhatsApp AI auto-reply agent (responds using GoalOS memory context)
- **Sprint 4C**: Template message support (pre-approved Meta message templates)
- **Sprint 5**: Persistent WhatsApp session management + retry queue
