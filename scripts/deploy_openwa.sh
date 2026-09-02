#!/usr/bin/env bash
# deploy_openwa.sh — Deploy OpenWA WhatsApp gateway on the KVM VPS
#
# Creates a minimal Docker Compose deployment with SQLite backend (no Postgres/Redis/MinIO).
# OpenWA runs on 127.0.0.1:2785, accessible only from the host and GoalOS.
#
# Usage:
#   bash scripts/deploy_openwa.sh          # first-time deploy
#   bash scripts/deploy_openwa.sh update   # pull latest and recreate
#
# Prerequisites:
#   - Docker and Docker Compose v2 installed
#   - GoalOS running on port 8000
set -euo pipefail

OPENWA_DIR="/opt/openwa"
GOALOS_OPENWA_ENV="/etc/goalos/goalos.env"
GOALOS_OPENWA_WEBHOOK="http://127.0.0.1:8000/api/v1/webhooks/openwa"
GOALOS_OPENWA_API_KEY="${OPENWA_API_KEY:-$(openssl rand -hex 32)}"
ACTION="${1:-deploy}"

mkdir -p "$OPENWA_DIR"

# ---- Generate .env for OpenWA ----
cat > "$OPENWA_DIR/.env" <<OENV
# OpenWA Minimal Deployment for GoalOS
NODE_ENV=production
LOG_LEVEL=info
PORT=2785
ENGINE_TYPE=baileys

# SQLite (no external DB needed)
DATABASE_TYPE=

# Webhook — where OpenWA sends inbound events
WEBHOOK_URL=${GOALOS_OPENWA_WEBHOOK}
WEBHOOK_TIMEOUT=10000
WEBHOOK_RETRY_DELAY=5000

# Security — only GoalOS can reach the API
API_MASTER_KEY=${GOALOS_OPENWA_API_KEY}
ALLOW_UNSIGNED_INGRESS=false

# Session data persistence
SESSION_DATA_PATH=./data/sessions

# Memory limits for KVM VPS
OPENWA_MEM_LIMIT=1g
OPENWA_PIDS_LIMIT=1024
OENV

# ---- Minimal docker-compose for GoalOS integration ----
cat > "$OPENWA_DIR/docker-compose.yml" <<'DCOMPOSE'
# Minimal OpenWA deployment for GoalOS — SQLite, Baileys, single port
services:
  openwa-api:
    image: ghcr.io/open-wa/wa-automate-nodejs:latest
    container_name: openwa-api
    restart: unless-stopped
    stop_grace_period: 30s
    networks:
      - openwa-network
    ports:
      - '127.0.0.1:2785:2785'
    environment:
      - NODE_ENV=${NODE_ENV:-production}
      - PORT=2785
      - LOG_LEVEL=${LOG_LEVEL:-info}
      - ENGINE_TYPE=${ENGINE_TYPE:-baileys}
      - DATABASE_TYPE=${DATABASE_TYPE:-}
      - SESSION_DATA_PATH=${SESSION_DATA_PATH:-./data/sessions}
      - WEBHOOK_URL=${WEBHOOK_URL:-}
      - WEBHOOK_TIMEOUT=${WEBHOOK_TIMEOUT:-10000}
      - WEBHOOK_RETRY_DELAY=${WEBHOOK_RETRY_DELAY:-5000}
      - API_MASTER_KEY=${API_MASTER_KEY:-}
      - ALLOW_UNSIGNED_INGRESS=${ALLOW_UNSIGNED_INGRESS:-false}
      - PUPPETEER_HEADLESS=true
      - PUPPETEER_ARGS=--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage
      - MAX_CONCURRENT_SESSIONS=5
      - CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
      - SERVE_DASHBOARD=true
    volumes:
      - openwa-data:/app/data
    mem_limit: ${OPENWA_MEM_LIMIT:-1g}
    pids_limit: ${OPENWA_PIDS_LIMIT:-1024}
    security_opt:
      - 'no-new-privileges:true'
    healthcheck:
      test: ['CMD', 'curl', '-f', 'http://localhost:2785/api/health/ready']
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 45s
    labels:
      - 'com.goalos.service=whatsapp'
      - 'com.goalos.component=openwa'

volumes:
  openwa-data:
    name: goalos_openwa-data
    driver: local

networks:
  openwa-network:
    name: goalos-openwa-network
DCOMPOSE

# ---- Deploy or update ----
cd "$OPENWA_DIR"

if [ "$ACTION" = "update" ]; then
    echo "[openwa] Pulling latest image and recreating..."
    docker compose pull
    docker compose up -d --force-recreate --remove-orphans
else
    echo "[openwa] Starting OpenWA for the first time..."
    docker compose up -d
fi

# ---- Wait for health ----
echo "[openwa] Waiting for health check..."
for i in $(seq 1 20); do
    if curl -sf http://127.0.0.1:2785/api/health/ready > /dev/null 2>&1; then
        echo "[openwa] ✅ OpenWA is healthy on http://127.0.0.1:2785"
        break
    fi
    sleep 3
    if [ "$i" -eq 20 ]; then
        echo "[openwa] ⚠️  OpenWA health check timed out — check logs:"
        echo "  docker logs openwa-api --tail 50"
    fi
done

# ---- Update GoalOS environment if the env file exists ----
if [ -f "$GOALOS_OPENWA_ENV" ]; then
    echo "[openwa] Updating GoalOS environment..."
    # Add OpenWA vars if not already present
    grep -q 'GOALOS_OPENWA_BASE_URL' "$GOALOS_OPENWA_ENV" 2>/dev/null || \
        cat >> "$GOALOS_OPENWA_ENV" <<EOF

# OpenWA WhatsApp Gateway
GOALOS_OPENWA_BASE_URL=http://127.0.0.1:2785
GOALOS_OPENWA_API_KEY=${GOALOS_OPENWA_API_KEY}
WHATSAPP_PROVIDER=openwa
OPENWA_API_URL=http://127.0.0.1:2785
OPENWA_AUTH_TOKEN=${GOALOS_OPENWA_API_KEY}
OPENWA_WEBHOOK_SECRET=
EOF
    echo "[openwa] ✅ GoalOS environment updated"
    echo "[openwa] Restart GoalOS: sudo systemctl restart goalos"
fi

echo ""
echo "============================================"
echo " OpenWA Deployment Complete"
echo "============================================"
echo ""
echo " Dashboard:  http://127.0.0.1:2785"
echo " API:        http://127.0.0.1:2785/api"
echo " Health:     http://127.0.0.1:2785/api/health/ready"
echo " Sessions:   http://127.0.0.1:2785/api/sessions"
echo ""
echo " Next steps:"
echo " 1. Open the dashboard to pair your WhatsApp account"
echo " 2. Scan the QR code with WhatsApp on your phone"
echo " 3. Test: curl http://127.0.0.1:2785/api/sessions"
echo " 4. Restart GoalOS: sudo systemctl restart goalos"
echo ""
echo " Webhook URL configured:"
echo "  ${GOALOS_OPENWA_WEBHOOK}"
echo ""
echo " API key (save this):"
echo "  ${GOALOS_OPENWA_API_KEY}"
echo ""
