#!/usr/bin/env bash
# kvm_deploy_wacrm.sh — Deploy WACRM on the KVM VPS
#
# This script is to be run ON THE KVM, not in Freebuff.
# It deploys WACRM as a Docker service on port 3000.
#
# Prerequisites:
#   - Docker and Docker Compose v2 installed on KVM
#   - Supabase project created (https://supabase.com)
#   - Meta WhatsApp Business App configured
#   - GoalOS running at /opt/GoalOS on port 8000
#
# Usage:
#   bash kvm_deploy_wacrm.sh          # first-time deploy
#   bash kvm_deploy_wacrm.sh update   # pull latest and recreate
set -euo pipefail

WACRM_DIR="/opt/wacrm"
ACTION="${1:-deploy}"

# ---- Check Docker ----
if ! command -v docker &> /dev/null; then
    echo "[wacrm] ERROR: Docker not installed. Install Docker first."
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "[wacrm] ERROR: Docker Compose v2 not installed."
    exit 1
fi

# ---- Clone/update WACRM ----
if [ ! -d "$WACRM_DIR" ]; then
    echo "[wacrm] Cloning WACRM to $WACRM_DIR..."
    git clone https://github.com/ArnasDon/wacrm.git "$WACRM_DIR"
fi

cd "$WACRM_DIR"

if [ "$ACTION" = "update" ]; then
    echo "[wacrm] Pulling latest..."
    git pull origin main
fi

# ---- Create .env.local if missing ----
if [ ! -f .env.local ]; then
    echo "[wacrm] Creating .env.local from template..."
    cp .env.local.example .env.local
    echo ""
    echo "================================================"
    echo " WACRM requires configuration before starting."
    echo ""
    echo " Edit: $WACRM_DIR/.env.local"
    echo ""
    echo " REQUIRED VARIABLES (see below for categories):"
    echo ""
    echo " A. REQUIRED TO BOOT:"
    echo "    NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co"
    echo "    NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ..."
    echo "    SUPABASE_SERVICE_ROLE_KEY=eyJ..."
    echo "    ENCRYPTION_KEY=<32-char-random-string>"
    echo ""
    echo " B. REQUIRED FOR META WHATSAPP:"
    echo "    META_WHATSAPP_ACCESS_TOKEN=EAA..."
    echo "    META_WHATSAPP_PHONE_NUMBER_ID=1234567890"
    echo "    META_WHATSAPP_BUSINESS_ACCOUNT_ID=1234567890"
    echo "    META_APP_SECRET=<your-app-secret>"
    echo ""
    echo " C. OPTIONAL:"
    echo "    NEXT_PUBLIC_SITE_URL=https://your-domain.com"
    echo "    NEXT_PUBLIC_APP_LOCALE=en"
    echo "    AUTOMATION_CRON_SECRET=<for automations>"
    echo ""
    echo " After editing, run: bash kvm_deploy_wacrm.sh"
    echo "================================================"
    exit 0
fi

# ---- Build and start ----
echo "[wacrm] Building and starting WACRM..."
docker compose --env-file .env.local up --build -d

# ---- Wait for health ----
echo "[wacrm] Waiting for health check (up to 90s)..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
        echo "[wacrm] ✅ WACRM is healthy on http://127.0.0.1:3000"
        break
    fi
    sleep 3
    if [ "$i" -eq 30 ]; then
        echo "[wacrm] ⚠️  Health check timed out. Check logs:"
        echo "  docker logs wacrm-app --tail 50"
        exit 1
    fi
done

# ---- Show status ----
echo ""
echo "============================================"
echo " WACRM Deployment Complete"
echo "============================================"
echo ""
echo " Service:   http://127.0.0.1:3000"
echo " Dashboard: http://127.0.0.1:3000/dashboard"
echo " API:       http://127.0.0.1:3000/api/v1"
echo " Health:    http://127.0.0.1:3000/api/v1/me"
echo ""
echo " NEXT STEPS:"
echo ""
echo " 1. Open WACRM dashboard in browser"
echo " 2. Create first account (owner)"
echo " 3. Go to Settings → API keys → New key"
echo "    - Name: GoalOS"
echo "    - Scopes: messages:send, messages:read, contacts:read,"
echo "              conversations:read, webhooks:manage"
echo " 4. Copy the API key (shown once)"
echo " 5. Add to /etc/goalos/goalos.env:"
echo "    WHATSAPP_PROVIDER=wacrm"
echo "    WACRM_API_URL=http://127.0.0.1:3000"
echo "    WACRM_API_KEY=<your-api-key>"
echo " 6. Restart GoalOS:"
echo "    sudo systemctl restart goalos"
echo ""
echo " 7. Register webhook in WACRM dashboard:"
echo "    URL: https://<your-domain>/api/v1/webhooks/wacrm"
echo "    Events: message.received, message.status_updated"
echo ""
echo " To switch back to OpenWA:"
echo "    sed -i 's/WHATSAPP_PROVIDER=wacrm/WHATSAPP_PROVIDER=openwa/' /etc/goalos/goalos.env"
echo "    sudo systemctl restart goalos"
echo ""
