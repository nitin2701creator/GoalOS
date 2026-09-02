# WACRM KVM Configuration Reference

## Overview

WACRM runs as a Docker service on port 3000. GoalOS communicates with it via HTTP.

## Environment Variables

### Category A: REQUIRED TO BOOT WACRM

| Variable | Source | Description |
|----------|--------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase dashboard | Your Supabase project URL (e.g., `https://xxx.supabase.co`) |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase dashboard | Supabase anonymous/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase dashboard | Supabase service role key (server-side only) |
| `ENCRYPTION_KEY` | Generate yourself | 32-character random string for token encryption |

**How to get Supabase credentials:**
1. Go to https://supabase.com and create a project
2. In Project Settings → API, copy:
   - Project URL → `NEXT_PUBLIC_SUPABASE_URL`
   - `anon` `public` key → `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `service_role` `secret` key → `SUPABASE_SERVICE_ROLE_KEY`

**How to generate ENCRYPTION_KEY:**
```bash
openssl rand -hex 16
```

### Category B: REQUIRED FOR META WHATSAPP CLOUD API

| Variable | Source | Description |
|----------|--------|-------------|
| `META_WHATSAPP_ACCESS_TOKEN` | Meta Developer Dashboard | WhatsApp Business API access token |
| `META_WHATSAPP_PHONE_NUMBER_ID` | Meta Developer Dashboard | Phone number ID from WhatsApp Manager |
| `META_WHATSAPP_BUSINESS_ACCOUNT_ID` | Meta Developer Dashboard | WhatsApp Business Account ID |
| `META_APP_SECRET` | Meta Developer Dashboard | App secret for webhook verification |

**How to get Meta credentials:**
1. Go to https://developers.facebook.com
2. Create an App → Business → WhatsApp
3. Go to WhatsApp → Getting Started
4. Copy the access token (temporary, convert to permanent in System Users)
5. Go to WhatsApp → Phone Numbers → copy Phone Number ID
6. Go to WhatsApp → WhatsApp Business Accounts → copy Business Account ID
7. Go to App Settings → Basic → copy App Secret

### Category C: OPTIONAL

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_SITE_URL` | (empty) | Public URL for webhooks (e.g., `https://wacrm.yourdomain.com`) |
| `NEXT_PUBLIC_APP_LOCALE` | `en` | Default locale |
| `AUTOMATION_CRON_SECRET` | (empty) | Secret for automation cron endpoint |
| `HOST_PORT` | `3000` | Host port to publish |

### Category D: DEVELOPMENT-ONLY

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_DEV_MODE` | Enable dev features |
| `DATABASE_LOGGING` | Log SQL queries |

## Supabase Database Migrations

After creating the Supabase project, apply migrations:

```bash
# Install Supabase CLI
npm install -g supabase

# Login
supabase login

# Link to your project
supabase link --project-ref <your-project-ref>

# Apply all migrations
cd /opt/wacrm
supabase db push
```

Or apply manually via Supabase SQL Editor:
1. Go to Supabase Dashboard → SQL Editor
2. Run each file in `supabase/migrations/` in order

## Docker Deployment

### Build and Start
```bash
cd /opt/wacrm
docker compose --env-file .env.local up --build -d
```

### View Logs
```bash
docker logs wacrm-app -f
```

### Restart
```bash
docker compose --env-file .env.local restart
```

### Stop
```bash
docker compose --env-file .env.local down
```

## GoalOS Integration

After WACRM is running, configure GoalOS:

### Environment Variables

Add to `/etc/goalos/goalos.env`:

```bash
# WhatsApp provider selection
WHATSAPP_PROVIDER=wacrm

# WACRM connection
WACRM_API_URL=http://127.0.0.1:3000
WACRM_API_KEY=<create in WACRM dashboard>

# Optional: webhook validation
WACRM_WEBHOOK_SECRET=<from WACRM webhook setup>
```

### Create WACRM API Key

1. Open `http://127.0.0.1:3000` in browser
2. Create first account (owner)
3. Go to Settings → API keys → New API key
4. Name: `GoalOS`
5. Scopes: `messages:send`, `messages:read`, `contacts:read`, `conversations:read`, `webhooks:manage`
6. Copy the key (shown once only)

### Register Webhook (Optional)

For inbound message processing:

1. In WACRM dashboard → Settings → Webhooks
2. Add endpoint: `https://<your-domain>/api/v1/webhooks/wacrm`
3. Events: `message.received`, `message.status_updated`
4. Save the webhook secret → add to `WACRM_WEBHOOK_SECRET`

### Restart GoalOS

```bash
sudo systemctl daemon-reload
sudo systemctl restart goalos
```

### Verify

```bash
# Check GoalOS WhatsApp status
curl -sS http://172.16.0.1:8000/api/v1/whatsapp/status | python3 -m json.tool

# Should show:
# configured: true
# active_provider: wacrm
```

## Provider Switching

Switch between providers without code changes:

```bash
# Switch to WACRM (Meta Business API)
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=wacrm/' /etc/goalos/goalos.env
sudo systemctl restart goalos

# Switch to OpenWA (WhatsApp Web)
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=openwa/' /etc/goalos/goalos.env
sudo systemctl restart goalos

# Auto mode (WACRM preferred, OpenWA fallback)
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=auto/' /etc/goalos/goalos.env
sudo systemctl restart goalos
```

## Troubleshooting

### WACRM won't start
```bash
docker logs wacrm-app --tail 50
```

### GoalOS shows "INTEGRATION_NOT_CONFIGURED"
- Verify `WHATSAPP_PROVIDER=wacrm` in `/etc/goalos/goalos.env`
- Verify `WACRM_API_URL=http://127.0.0.1:3000`
- Verify `WACRM_API_KEY` is set
- Restart: `sudo systemctl restart goalos`

### Webhook not receiving events
- Verify WACRM is running: `curl http://127.0.0.1:3000/api/v1/me`
- Check webhook URL in WACRM dashboard
- Check GoalOS logs: `journalctl -u goalos -f`

### Meta API errors
- Verify access token is valid and not expired
- Verify phone number ID matches your WhatsApp number
- Verify business account ID is correct
- Check Meta Developer Dashboard for errors
