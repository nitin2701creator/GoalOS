# WooCommerce Webhook Ingestion

Real-time event-driven integration between WooCommerce and GoalOS.

GoalOS receives WooCommerce order events and abandoned-cart events via
webhooks — **no polling**. Events are delivered within seconds.

## Architecture

```
WooCommerce
├── Native Order Webhooks (order.created / order.updated / order.deleted)
│       ↓  HMAC-SHA256 signed
│       ↓
│   POST /api/v1/webhooks/woocommerce/order
│       ↓
│   GoalOS Webhook Layer
│       ↓  Signature verification → Idempotency → Validation
│   GoalOS Database (woocommerce_orders + order_items)
│       ↓
│   Recovery Linkage (abandoned cart → order matching)
│
└── Abandoned Cart Lite → WordPress Bridge
        ↓  Bearer token auth
        ↓
    POST /api/v1/webhooks/abandoned-cart
        ↓
    GoalOS Webhook Layer
        ↓  Token verification → Idempotency → Validation
    GoalOS Database (woocommerce_abandoned_carts + cart_items)
```

## Required Environment Variables

### WooCommerce Order Webhooks

| Variable | Purpose | Example |
|---|---|---|
| `GOALOS_WOOCOMMERCE_WEBHOOK_SECRET` | HMAC-SHA256 secret for WooCommerce native order webhooks | `whsec_abc123...` |

Legacy name accepted: `WOOCOMMERCE_WEBHOOK_SECRET`

### Abandoned Cart Bridge

| Variable | Purpose | Example |
|---|---|---|
| `GOALOS_ABANDONED_CART_WEBHOOK_SECRET` | Bearer token for the WordPress abandoned-cart bridge | `cart-secret-xyz789...` |

## WooCommerce Webhook Setup

1. Go to **WooCommerce → Settings → Advanced → Webhooks**
2. Click **Add webhook**
3. Set **Name**: `GoalOS Orders`
4. Set **Status**: `Active`
5. Set **Topic**: `Order created` (create a second webhook for `Order updated`)
6. Set **Delivery URL**: `https://<your-goalos-url>/api/v1/webhooks/woocommerce/order`
7. Set **Secret**: Use the value of `GOALOS_WOOCOMMERCE_WEBHOOK_SECRET`
8. Set **API version**: `WooCommerce REST API v3`
9. Save

**Create two webhooks:**
- Topic: `Order created` → `order.created`
- Topic: `Order updated` → `order.updated`

WooCommerce will send `X-WC-Webhook-Signature` (base64 of HMAC-SHA256 of the
raw body using the secret) and `X-WC-Webhook-Delivery-ID` in the headers.

## Abandoned Cart Bridge Setup

The WordPress bridge (a custom endpoint or plugin hook) sends abandoned-cart
events to GoalOS via a simple HTTPS POST:

```
POST /api/v1/webhooks/abandoned-cart
Authorization: Bearer <GOALOS_ABANDONED_CART_WEBHOOK_SECRET>
Content-Type: application/json

{
  "cart_id": "acl_12345",
  "customer_email": "user@example.com",
  "customer_name": "Jane Doe",
  "currency": "INR",
  "cart_total": 2500.00,
  "abandoned_at": "2026-08-19T10:25:00Z",
  "cart_items": [
    {
      "product_id": 101,
      "sku": "PROD-001",
      "product_name": "Widget Pro",
      "quantity": 2,
      "unit_price": 1250.00,
      "line_total": 2500.00
    }
  ]
}
```

Anonymous visitors may omit `customer_email` and `customer_name`.

## API Endpoints

### POST /api/v1/webhooks/woocommerce/order

Ingests a WooCommerce order webhook event.

**Headers required:**
- `X-WC-Webhook-Signature`: HMAC-SHA256 signature (base64-encoded)
- `X-WC-Webhook-Delivery-ID`: Delivery ID for idempotency
- `X-WC-Webhook-Topic`: e.g., `order.created`, `order.updated`

**Responses:**
| Status | Meaning |
|---|---|
| `202 Accepted` | Event accepted and persisted |
| `200 OK` | Duplicate delivery (idempotent, no data change) |
| `401 Unauthorized` | Invalid HMAC signature |
| `422 Unprocessable Entity` | Malformed payload |
| `503 Service Unavailable` | `GOALOS_WOOCOMMERCE_WEBHOOK_SECRET` not configured |

### POST /api/v1/webhooks/abandoned-cart

Ingests an abandoned-cart event from the WordPress bridge.

**Headers required:**
- `Authorization: Bearer <secret>`

**Responses:**
| Status | Meaning |
|---|---|
| `202 Accepted` | Event accepted and persisted |
| `200 OK` | Duplicate delivery (idempotent, no data change) |
| `401 Unauthorized` | Invalid bearer token |
| `422 Unprocessable Entity` | Malformed payload or missing `cart_id` |
| `503 Service Unavailable` | `GOALOS_ABANDONED_CART_WEBHOOK_SECRET` not configured |

### GET /api/v1/webhooks/woocommerce/orders

Lists ingested WooCommerce orders.

**Query params:** `limit` (default 50), `status_filter` (optional)

### GET /api/v1/webhooks/abandoned-carts

Lists ingested abandoned carts.

**Query params:** `limit` (default 50), `status_filter` (optional)

## Data Captured

### Order Data
- WooCommerce order ID, number, status, currency
- Total, subtotal, discount, shipping, tax
- Customer ID, email, name
- Billing/shipping addresses
- Payment method
- Line items (product ID, SKU, name, quantity, prices)
- Coupons, shipping lines
- WooCommerce timestamps

### Abandoned Cart Data
- Cart ID (from Abandoned Cart Lite)
- Customer ID, email, name, phone
- Currency, cart total, item count
- Cart items (product ID, SKU, name, quantity, prices)
- Abandonment timestamp

## Idempotency

- **Orders**: Deduplicated by `wc:{topic}:{order_id}:{delivery_id}`. The same
  WooCommerce delivery ID never creates duplicate records.
- **Abandoned carts**: Deduplicated by a deterministic hash of
  `cart_id + customer_email + abandoned_at`.
- Both streams persist every event in the `events` table for audit.

## Cart → Order Recovery

When a completed/processing order arrives, GoalOS checks if the customer email
matches an unrecovered abandoned cart. If so:

1. Cart status → `recovered`
2. `recovered_woo_order_id` → WooCommerce order ID
3. `recovery_revenue` → order total
4. `recovered_at` → timestamp

This is **idempotent** — re-delivering the same order does not double-count.

**Limitation:** Recovery matching is by customer email only. Carts without an
email (anonymous visitors) cannot be automatically recovered.

## Security

- WooCommerce webhooks are verified via HMAC-SHA256 signature
- Abandoned-cart events are verified via bearer token
- All secrets are stored in environment variables, never in source code
- Secrets are never logged or exposed through API responses
- HTTPS is strongly recommended for all webhook endpoints

## Testing

### Unit Tests

```bash
python -m pytest tests/test_woocommerce_webhooks.py -v
```

34 tests covering:
- Valid abandoned-cart events
- Invalid authentication (missing, wrong token, no secret)
- Missing cart ID
- Anonymous carts
- Multi-item carts
- WooCommerce order created/updated
- Order status changes (all statuses)
- Invalid/missing HMAC signatures
- Duplicate delivery (idempotency)
- Sequential order updates
- Cart → order recovery linkage
- Recovery revenue calculation
- Recovery idempotency
- Missing customer information
- Malformed payloads
- Database failure handling

### Manual Webhook Test

```bash
# Test abandoned-cart endpoint
curl -X POST https://<goalos-url>/api/v1/webhooks/abandoned-cart \
  -H "Authorization: Bearer <GOALOS_ABANDONED_CART_WEBHOOK_SECRET>" \
  -H "Content-Type: application/json" \
  -d '{"cart_id":"test_001","customer_email":"test@example.com","cart_total":100,"cart_items":[]}'

# Test order endpoint (requires valid HMAC signature)
# Use WooCommerce's built-in webhook test feature:
# WooCommerce → Settings → Advanced → Webhooks → click webhook → "Send test"
```
