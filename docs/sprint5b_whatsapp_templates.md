# Sprint 5B — WhatsApp Business Template Messaging

## Architecture

```
GoalOS Business Logic
    ↓
send_template_message() [whatsapp_templates.py]
    ↓
1. Validate request
2. Check idempotency (correlation_id)
3. Evaluate Action Policy (MEDIUM risk, requires approval)
4. Check handoff state (if DB provided)
5. Dispatch to provider adapter
    ↓
MetaWhatsAppAdapter.send_template()
    ↓
Meta Graph API POST /v21.0/{phone_number_id}/messages
    {
      "messaging_product": "whatsapp",
      "to": "+15551234567",
      "type": "template",
      "template": {
        "name": "order_confirmation",
        "language": {"code": "en"},
        "components": [...]
      }
    }
```

## Provider-Neutral Interface

All template business logic uses provider-neutral models:
- `SendTemplateRequest` — template name, language, recipient, components
- `SendTemplateResponse` — provider, status, message ID, error
- `TemplateComponent` — header/body/button with parameters
- `TemplateParameter` — text/image/video/document/currency/payload

Meta-specific implementation is isolated inside `MetaWhatsAppAdapter`.

## Template Validation

Before sending, every request is validated for:
- Template name (non-empty, alphanumeric + underscore, max 512 chars)
- Language code (2-10 chars)
- Recipient (valid E.164)
- Component uniqueness (no duplicate headers)
- Parameter completeness (text params non-empty, media params have URLs)

## Default Template Definitions

| Template | Category | Variables |
|---|---|---|
| `order_confirmation` | transactional | order_number, total_amount |
| `payment_confirmation` | transactional | amount, order_number |
| `shipping_update` | utility | order_number, status, tracking_url |
| `appointment_reminder` | utility | date, time |
| `lead_followup` | marketing | name, topic |
| `customer_reengagement` | marketing | name, offer |
| `human_handoff_notification` | utility | topic |

Templates are configurable — not hard-coded into business logic.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/whatsapp/templates` | List all configured templates |
| `GET` | `/api/v1/whatsapp/templates/{name}` | Get template by name |
| `POST` | `/api/v1/whatsapp/templates/validate` | Validate without sending |
| `POST` | `/api/v1/whatsapp/templates/preview` | Preview Meta payload |
| `POST` | `/api/v1/whatsapp/templates/send` | Send template message |

## Action Policy

Template messages are outbound external communications:
- Risk level: MEDIUM
- Approval required: Yes
- External side effect: Yes
- Capability: `whatsapp_send_template`

## Handoff Integration

When a conversation is in `HUMAN_ACTIVE` or `HUMAN_REQUESTED`:
- Template sending is blocked for that recipient
- Returns `handoff_active` status
- Human-triggered sending via API with `approved=true` still works

## Idempotency

- Correlation ID-based dedup
- In-memory bounded cache (5000 entries, 1-hour TTL)
- Same correlation_id = duplicate blocked

## Configuration

No additional environment variables needed beyond existing Meta WhatsApp config:
- `META_WHATSAPP_ACCESS_TOKEN`
- `META_WHATSAPP_PHONE_NUMBER_ID`
- `META_WHATSAPP_BUSINESS_ACCOUNT_ID`
- `META_WHATSAPP_VERIFY_TOKEN`
- `META_WHATSAPP_APP_SECRET`

## Meta Approval Requirement

Templates must be pre-approved by Meta before sending. GoalOS does not bypass this requirement. The `status` field in template definitions reflects the Meta approval state.

## KVM2 Resource Impact

- **No new processes** — runs inside GoalOS FastAPI
- **No new databases** — uses existing SQLite
- **No Redis/Kafka/Celery** — in-memory idempotency only
- **No new dependencies** — stdlib HTTP only

## Testing

```bash
# Run template-specific tests
python -m pytest tests/test_whatsapp_templates.py -v

# Run full suite
python -m pytest
```

All tests use mocks — no real WhatsApp template sends.

## Next Sprint

- Sprint 5C: Conversation analytics and response quality tracking
- Sprint 5D: Multi-language template support with dynamic language detection
