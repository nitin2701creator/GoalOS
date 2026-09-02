#!/usr/bin/env bash
# deploy_wacrm.sh — Deploy WACRM WhatsApp Business CRM on the KVM VPS
#
# WACRM is a separate Next.js service that provides the official Meta
# WhatsApp Business API integration. GoalOS communicates with it via HTTP.
#
# Prerequisites:
#   - Docker and Docker Compose v2 installed
#   - Supabase project created (or local Supabase)
#   - Meta WhatsApp Business App configured
#
# Usage:
#   bash scripts/deploy_wacrm.sh          # first-time deploy
#   bash scripts/deploy_wacrm.sh update   # pull latest and recreate
set -euo pipefail

WACRM_DIR="/opt/wacrm"
WACRM_SOURCE="/home/daytona/codebase/external/whatsapp/wacrm"
ACTION="${1:-deploy}"

# ---- Copy WACRM to /opt if not already there ----
if [ ! -d "$WACRM_DIR" ] || [ "$ACTION" = "update" ]; then
    echo "[wacrm] Copying WACRM to $WACRM_DIR..."
    mkdir -p /opt
    rsync -a --delete "$WACRM_SOURCE/" "$WACRM_DIR/"
fi

cd "$WACRM_DIR"

# ---- Create .env.local if it doesn't exist ----
if [ ! -f .env.local ]; then
    echo "[wacrm] Creating .env.local from template..."
    cp .env.local.example .env.local
    echo ""
    echo "================================================"
    echo " WACRM requires configuration before starting."
    echo " Edit: $WACRM_DIR/.env.local"
    echo ""
    echo " Required variables:"
    echo "   NEXT_PUBLIC_SUPABASE_URL=..."
    echo "   NEXT_PUBLIC_SUPABASE_ANON_KEY=..."
    echo "   SUPABASE_SERVICE_ROLE_KEY=..."
    echo "   META_WHATSAPP_ACCESS_TOKEN=..."
    echo "   META_WHATSAPP_PHONE_NUMBER_ID=..."
    echo "   META_WHATSAPP_BUSINESS_ACCOUNT_ID=..."
    echo "   META_APP_SECRET=..."
    echo ""
    echo " After editing, run: bash scripts/deploy_wacrm.sh"
    echo "================================================"
    exit 0
fi

# ---- Deploy or update ----
if [ "$ACTION" = "update" ]; then
    echo "[wacrm] Pulling latest and recreating..."
    docker compose down
    docker compose build --no-cache
    docker compose up -d
else
    echo "[wacrm] Starting WACRM..."
    docker compose up -d --build
fi

# ---- Wait for health ----
echo "[wacrm] Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:3000 > /dev/null 2>&1; then
        echo "[wacrm] ✅ WACRM is healthy on http://127.0.0.1:3000"
        break
    fi
    sleep 3
    if [ "$i" -eq 30 ]; then
        echo "[wacrm] ⚠️  WACRM health check timed out — check logs:"
        echo "  docker logs wacrm-app --tail 50"
    fi
done

# ---- Update GoalOS environment if available ----
GOALOS_ENV="/etc/goalos/goalos.env"
if [ -f "$GOALOS_ENV" ]; then
    echo "[wacrm] Updating GoalOS environment..."
    grep -q 'WACRM_API_URL' "$GOALOS_ENV" 2>/dev/null || \
        cat >> "$GOALOS_ENV" <<EOF

# WACRM WhatsApp Business API (primary provider)
WACRM_API_URL=http://127.0.0.1:3000
WACRM_API_KEY=<create in WACRM dashboard: Settings → API keys>
EOF
    echo "[wacrm] ✅ GoalOS environment updated"
    echo "[wacrm] Remember to set WACRM_API_KEY and restart GoalOS"
fi

echo ""
echo "============================================"
echo " WACRM Deployment Complete"
echo "============================================"
echo ""
echo " Dashboard:  http://127.0.0.1:3000"
echo " API:        http://127.0.0.1:3000/api/v1"
echo " Health:     http://127.0.0.1:3000/api/v1/me"
echo ""
echo " Next steps:"
echo " 1. Open WACRM dashboard and create an API key"
echo " 2. Set WACRM_API_KEY in /etc/goalos/goalos.env"
echo " 3. Set WHATSAPP_PROVIDER=wacrm in /etc/goalos/goalos.env"
echo " 4. Restart GoalOS: sudo systemctl restart goalos"
echo " 5. Test: curl -H 'Authorization: Bearer <key>' http://127.0.0.1:3000/api/v1/me"
echo ""
echo " Configure Meta webhook in WACRM dashboard:"
echo "  Webhook URL: https://<your-domain>/api/v1/webhooks/wacrm"
echo "  Events: message.received, message.status_updated"
echo ""
