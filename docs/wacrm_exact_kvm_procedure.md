# WACRM — Exact KVM Deployment Procedure

## What WACRM Actually Requires (from source code inspection)

### Hard Requirements to Boot

| Variable | Source | Why Required |
|----------|--------|--------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase dashboard | Database + Auth — WACRM cannot start without it |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase dashboard | Client-side auth |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase dashboard | Server-side DB operations (API keys, contacts, messages) |
| `ENCRYPTION_KEY` | Generate yourself | AES-256-GCM encryption for Meta tokens stored in DB |

### Required for WhatsApp Functionality

| Variable | Source | Why Required |
|----------|--------|--------------|
| `META_WHATSAPP_ACCESS_TOKEN` | Meta Developer Dashboard | Send/receive WhatsApp messages |
| `META_WHATSAPP_PHONE_NUMBER_ID` | Meta Developer Dashboard | Identify which phone number to use |
| `META_WHATSAPP_BUSINESS_ACCOUNT_ID` | Meta Developer Dashboard | WhatsApp Business Account |
| `META_APP_SECRET` | Meta Developer Dashboard | Webhook signature verification |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_SITE_URL` | (empty) | Public URL for webhooks |
| `NEXT_PUBLIC_APP_LOCALE` | `en` | Default locale |
| `AUTOMATION_CRON_SECRET` | (empty) | For automation cron endpoint |
| `HOST_PORT` | `3000` | Host port |

## Authentication Mechanism

WACRM uses **Supabase Auth** for dashboard login and **API keys** for programmatic access.

- Dashboard: Email/password via Supabase Auth
- Public API: `Authorization: Bearer wacrm_live_<key>` — keys created in dashboard, stored as SHA-256 hashes in Supabase
- API keys are created AFTER WACRM is running and you've created an account

## Can WACRM Boot Without Meta Credentials?

**YES.** WACRM will boot with just Supabase credentials. The Meta credentials are only needed when you actually try to send/receive WhatsApp messages. The dashboard, API, contacts, conversations etc. will work without Meta configured.

## Step-by-Step KVM Procedure

### Step 1: Create Supabase Project

1. Go to https://supabase.com
2. Create a new project
3. Note the Project URL and keys from Settings → API
4. Apply migrations:

```bash
# Install Supabase CLI if not present
npm install -g supabase

# Login
supabase login

# Link to your project
supabase link --project-ref <your-project-ref>

# Apply all migrations
cd /opt/wacrm
supabase db push
```

Or apply manually: go to Supabase Dashboard → SQL Editor, run each file in `supabase/migrations/` in order.

### Step 2: Create .env.local on KVM

```bash
cd /opt/wacrm
cp .env.local.example .env.local
```

Then edit `.env.local` with real values:

```bash
# Supabase (REQUIRED)
NEXT_PUBLIC_SUPABASE_URL=https://<your-project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-anon-key>
SUPABASE_SERVICE_ROLE_KEY=<your-service-role-key>

# Encryption (REQUIRED — generate with: openssl rand -hex 16)
ENCRYPTION_KEY=<32-char-hex-string>

# Meta WhatsApp (REQUIRED for WhatsApp — can leave empty to boot without WhatsApp)
META_WHATSAPP_ACCESS_TOKEN=
META_WHATSAPP_PHONE_NUMBER_ID=
META_WHATSAPP_BUSINESS_ACCOUNT_ID=
META_APP_SECRET=

# Optional
NEXT_PUBLIC_SITE_URL=
NEXT_PUBLIC_APP_LOCALE=en
```

### Step 3: Build and Start WACRM

```bash
cd /opt/wacrm

# Build and start with Docker
docker compose --env-file .env.local up --build -d

# Verify health
curl -sS http://127.0.0.1:3000

# View logs
docker logs wacrm-app --tail 20
```

### Step 4: Create WACRM Account and API Key

1. Open `http://<KVM-IP>:3000` in browser
2. Create first account (owner)
3. Go to Settings → API keys → New API key
4. Name: `GoalOS`
5. Scopes: `messages:send`, `messages:read`, `contacts:read`, `conversations:read`, `webhooks:manage`
6. Copy the key (shown once only)

### Step 5: Configure GoalOS

```bash
# Add to /etc/goalos/goalos.env
cat >> /etc/goalos/goalos.env << 'EOF'
WHATSAPP_PROVIDER=wacrm
WACRM_API_URL=http://127.0.0.1:3000
WACRM_API_KEY=<paste-the-key-from-step-4>
EOF

# Restart GoalOS
sudo systemctl daemon-reload
sudo systemctl restart goalos
```

### Step 6: Verify

```bash
# Check GoalOS WhatsApp status
curl -sS http://172.16.0.1:8000/api/v1/whatsapp/status | python3 -m json.tool

# Should show:
# configured: true
# active_provider: wacrm
```

## Real Blockers

1. **Supabase project** — must be created at supabase.com (free tier works)
2. **Meta WhatsApp Business App** — must be created at developers.facebook.com
3. **WACRM account** — created after WACRM is running
4. **WACRM API key** — created in WACRM dashboard after account creation

## Provider Switching

```bash
# Switch to WACRM
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=wacrm/' /etc/goalos/goalos.env
sudo systemctl restart goalos

# Switch to OpenWA
sed -i 's/WHATSAPP_PROVIDER=.*/WHATSAPP_PROVIDER=openwa/' /etc/goalos/goalos.env
sudo systemctl restart goalos
```
