# Dual-Provider WhatsApp — GoalOS

## Architecture

```
LibreChat
    ↓
GoalOS Capability Registry
    ↓
WhatsApp Provider Router
    ├── WACRM adapter → Meta WhatsApp Business API (primary)
    └── OpenWA adapter → WhatsApp Web (secondary)
```

## Providers

| Provider | Type | API | Status |
|----------|------|-----|--------|
| **WACRM** | Primary | Meta WhatsApp Business API | Production |
| **OpenWA** | Secondary | WhatsApp Web | Fallback |

## Provider Selection

Set `WHATSAPP_PROVIDER` in `/etc/goalos/goalos.env`:

```bash
# Primary (recommended for production)
WHATSAPP_PROVIDER=wacrm

# Secondary (WhatsApp Web, no Meta Business API needed)
WHATSAPP_PROVIDER=openwa

# Auto (WACRM preferred, OpenWA fallback)
WHATSAPP_PROVIDER=auto
```

Default: `wacrm`

## Deployment

### WACRM (Primary)

```bash
# 1. Deploy WACRM
cd /opt/GoalOS/external/whatsapp/wacrm
npm install
cp .env.local.example .env.local
# Configure Supabase + Meta credentials in .env.local
npm run build
npm start  # or use Docker
```

### OpenWA (Secondary)

```bash
# 1. Deploy OpenWA
bash /opt/GoalOS/scripts/deploy_openwa.sh
```

## Environment Variables

### Required

| Variable | Provider | Description |
|----------|----------|-------------|
| `WHATSAPP_PROVIDER` | All | `wacrm`, `openwa`, or `auto` |
| `WACRM_API_URL` | WACRM | WACRM base URL (e.g., `http://127.0.0.1:3000`) |
| `WACRM_API_KEY` | WACRM | WACRM API key |
| `OPENWA_API_URL` | OpenWA | OpenWA base URL (e.g., `http://127.0.0.1:2785`) |

### Optional

| Variable | Description |
|----------|-------------|
| `WACRM_WEBHOOK_SECRET` | HMAC-SHA256 webhook validation |
| `OPENWA_AUTH_TOKEN` | OpenWA API authentication |
| `OPENWA_WEBHOOK_SECRET` | OpenWA webhook validation |
| `WHATSAPP_AUTO_REPLY_ENABLED` | Enable AI auto-reply |
| `WHATSAPP_AGENT_SYSTEM_PROMPT` | Custom AI prompt |

## API Endpoints

### GoalOS WhatsApp API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/whatsapp/status` | Provider status (all providers) |
| `GET` | `/api/v1/whatsapp/agent/status` | Auto-reply agent status |
| `POST` | `/api/v1/whatsapp/send` | Send outbound message |
| `POST` | `/api/v1/webhooks/wacrm` | Receive WACRM webhook events |
| `POST` | `/api/v1/webhooks/openwa` | Receive OpenWA webhook events |
| `GET` | `/api/v1/whatsapp/contacts` | List contacts |
| `GET` | `/api/v1/whatsapp/conversations` | List conversations |

### Status Response

```json
{
  "configured": true,
  "available_providers": ["openwa", "wacrm"],
  "active_provider": "wacrm",
  "config": { ... }
}
```

## Webhook Flow

### WACRM (Meta Business API)

```
WhatsApp user sends message
  ↓
Meta WhatsApp Cloud API
  ↓
WACRM receives and stores
  ↓
WACRM POSTs to GoalOS: POST /api/v1/webhooks/wacrm
  ↓
GoalOS validates signature (X-Wacrm-Signature)
  ↓
GoalOS parses with WACRM adapter
  ↓
GoalOS agent processes and responds via WACRM API
```

### OpenWA (WhatsApp Web)

```
WhatsApp user sends message
  ↓
OpenWA receives via WhatsApp Web
  ↓
OpenWA POSTs to GoalOS: POST /api/v1/webhooks/openwa
  ↓
GoalOS validates signature (X-Webhook-Signature)
  ↓
GoalOS parses with OpenWA adapter
  ↓
GoalOS agent processes and responds via OpenWA API
```

## Sending a Test Message

```bash
# Via WACRM (primary)
curl -sS -X POST http://172.16.0.1:8000/api/v1/whatsapp/send \
  -H "Content-Type: application/json" \
  -d '{
    "destination_number": "+919876543210",
    "message": "Hello from GoalOS via WACRM!",
    "approved": true
  }' | python3 -m json.tool

# Via OpenWA (secondary)
# First switch: WHATSAPP_PROVIDER=openwa in goalos.env, then restart
curl -sS -X POST http://172.16.0.1:8000/api/v1/whatsapp/send \
  -H "Content-Type: application/json" \
  -d '{
    "destination_number": "+919876543210",
    "message": "Hello from GoalOS via OpenWA!",
    "approved": true
  }' | python3 -m json.tool
```

## Provider Switching

```bash
# Switch to WACRM
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=wacrm/' /etc/goalos/goalos.env
sudo systemctl restart goalos

# Switch to OpenWA
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=openwa/' /etc/goalos/goalos.env
sudo systemctl restart goalos

# Auto mode (WACRM preferred)
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=auto/' /etc/goalos/goalos.env
sudo systemctl restart goalos
```

## Security

- Credentials never appear in logs or API responses
- Webhook signature validation via HMAC-SHA256
- API key authentication via Bearer tokens
- WACRM and OpenWA credentials kept separate
- HTTPS required for public webhooks
- All WhatsApp data stored in GoalOS SQLite database

## Troubleshooting

### WACRM not reachable
```bash
curl -sS http://127.0.0.1:3000/api/v1/me \
  -H "Authorization: Bearer <WACRM_API_KEY>"
```

### OpenWA not reachable
```bash
curl -sS http://127.0.0.1:2785/api/health/ready
```

### GoalOS shows "INTEGRATION_NOT_CONFIGURED"
- Verify `WHATSAPP_PROVIDER` is set correctly
- Verify provider-specific URL and key are set
- Restart: `sudo systemctl restart goalos`

### Webhook not receiving events
- Verify provider is running and healthy
- Check webhook URL configuration in provider
- Check GoalOS logs: `journalctl -u goalos -f`
