# OpenWA WhatsApp Deployment — GoalOS

## Architecture

```
WhatsApp ←→ OpenWA (Docker, port 2785) ←→ GoalOS webhook (:8000)
                                            ↓
                                    WhatsApp Agent
                                            ↓
                                    GoalOS Memory
                                            ↓
                                    GoalOS LLM
                                            ↓
                                    Response → OpenWA → WhatsApp
```

## Deployment

### 1. Deploy OpenWA (on the KVM)

```bash
bash /opt/GoalOS/scripts/deploy_openwa.sh
```

This creates:
- Docker Compose deployment at `/opt/openwa/`
- SQLite backend (no Postgres/Redis needed)
- Baileys engine (free WhatsApp Web automation)
- API on `127.0.0.1:2785` (host-only, not public)
- Webhook pointing to `http://127.0.0.1:8000/api/v1/webhooks/openwa`

### 2. Configure GoalOS

Add these to `/etc/goalos/goalos.env`:

```bash
# WhatsApp provider
WHATSAPP_PROVIDER=openwa
WHATSAPP_AUTO_REPLY_ENABLED=true

# OpenWA connection
OPENWA_API_URL=http://127.0.0.1:2785
OPENWA_AUTH_TOKEN=<from deploy output>
OPENWA_WEBHOOK_SECRET=
```

### 3. Restart GoalOS

```bash
sudo systemctl daemon-reload
sudo systemctl restart goalos
```

### 4. Verify

```bash
# OpenWA health
curl -sS http://127.0.0.1:2785/api/health/ready

# GoalOS WhatsApp status
curl -sS http://172.16.0.1:8000/api/v1/whatsapp/status | python3 -m json.tool

# GoalOS health
curl -sS http://172.16.0.1:8000/health
```

## Pairing a WhatsApp Account

1. Open the OpenWA dashboard: `http://<KVM_IP>:2785`
2. Navigate to Sessions → Create Session
3. Scan the QR code with WhatsApp on your phone
4. Wait for connection confirmation
5. Verify: `curl -s http://127.0.0.1:2785/api/sessions`

## API Endpoints

### GoalOS WhatsApp API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/whatsapp/status` | Provider status (no secrets) |
| `GET` | `/api/v1/whatsapp/agent/status` | Auto-reply agent status |
| `POST` | `/api/v1/whatsapp/send` | Send outbound message |
| `POST` | `/api/v1/webhooks/openwa` | Receive OpenWA webhook events |
| `GET` | `/api/v1/whatsapp/contacts` | List WhatsApp contacts |
| `GET` | `/api/v1/whatsapp/conversations` | List conversations |
| `GET` | `/api/v1/whatsapp/handoffs` | List pending handoffs |
| `GET` | `/api/v1/whatsapp/analytics/summary` | Analytics summary |

### OpenWA API (direct)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health/ready` | Health check |
| `GET` | `/api/sessions` | List sessions |
| `POST` | `/api/send` | Send message |

## Sending a Test Message

```bash
# Via GoalOS (requires approval or auto-approved)
curl -sS -X POST http://172.16.0.1:8000/api/v1/whatsapp/send \
  -H "Content-Type: application/json" \
  -d '{
    "destination_number": "+919876543210",
    "message": "Hello from GoalOS!",
    "approved": true
  }' | python3 -m json.tool
```

## Webhook Flow (Inbound Messages)

```
WhatsApp user sends message
  ↓
OpenWA receives via WhatsApp Web
  ↓
OpenWA POSTs to http://127.0.0.1:8000/api/v1/webhooks/openwa
  ↓
GoalOS validates signature (if OPENWA_WEBHOOK_SECRET set)
  ↓
GoalOS parses with OpenWA adapter
  ↓
If auto-reply enabled: handle_inbound_message()
  ↓
  1. Idempotency check (deduplicates webhooks)
  2. Persist inbound message
  3. Retrieve contact memory
  4. Detect language (multilingual support)
  5. Check handoff state
  6. Generate AI response via LLM
  7. Send response via OpenWA
  8. Persist outbound message + memory
  ↓
WhatsApp user receives AI response
```

## Configuration Reference

### Required Environment Variables

| Variable | Value | Description |
|----------|-------|-------------|
| `WHATSAPP_PROVIDER` | `openwa` | Selects OpenWA adapter |
| `OPENWA_API_URL` | `http://127.0.0.1:2785` | OpenWA API endpoint |
| `OPENWA_AUTH_TOKEN` | `<key>` | API authentication |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WHATSAPP_AUTO_REPLY_ENABLED` | `false` | Enable AI auto-reply |
| `OPENWA_WEBHOOK_SECRET` | (empty) | HMAC-SHA256 webhook validation |
| `WHATSAPP_AGENT_SYSTEM_PROMPT` | (built-in) | Custom AI prompt |

## Security

- OpenWA binds to `127.0.0.1:2785` only (not public)
- Webhook signature validation via HMAC-SHA256
- API key authentication via `API_MASTER_KEY`/`OPENWA_AUTH_TOKEN`
- Credentials never appear in logs or API responses
- All WhatsApp data stored in GoalOS SQLite database

## Troubleshooting

### OpenWA won't start
```bash
docker logs openwa-api --tail 50
```

### GoalOS shows "INTEGRATION_NOT_CONFIGURED"
- Verify `WHATSAPP_PROVIDER=openwa` is in `/etc/goalos/goalos.env`
- Verify `OPENWA_API_URL=http://127.0.0.1:2785` is set
- Restart: `sudo systemctl restart goalos`

### Webhook not receiving events
- Verify OpenWA session is connected: `curl http://127.0.0.1:2785/api/sessions`
- Check webhook URL is set in OpenWA session config
- Check GoalOS logs: `journalctl -u goalos -f`

### No AI auto-reply
- Set `WHATSAPP_AUTO_REPLY_ENABLED=true` in `goalos.env`
- Verify LLM is configured: `curl http://172.16.0.1:8000/health | jq .llm`
