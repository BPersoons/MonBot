#!/bin/bash
set -e

echo "=== Agent Trader Deploy Update ==="

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get update && sudo apt-get install -y docker.io docker-compose
fi

# 2. Configure Docker auth for Artifact Registry (MUST use sudo so Docker daemon can access creds)
echo "Configuring Docker authentication..."
sudo gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet 2>/dev/null || true

# 2b. Preserve container-local state BEFORE stopping the old container.
# Newly volume-mounted state files must start life on the host as a copy of the
# running container's freshest state — otherwise the empty host file shadows it.
# Only copies when the host file is missing; on later deploys the host file IS the
# state (volume mount), so this is a no-op. Non-fatal by design (set -e safety).
STATE_FILES="shadow_book.json shadow_report.json shadow_basis_state.json shadow_basis_log.json shadow_basis_report.json ticker_state.json decision_history.json treasury_harvest.json treasury_proposals.json audited_trades.json portfolio_peak.json cost_log.json polymarket_shadow_log.json config/treasury_allocation.json"
sudo mkdir -p config
if sudo docker ps --format '{{.Names}}' | grep -q '^agent_trader_swarm$'; then
    echo "Preserving container state to host (first-time migration for new mounts)..."
    for f in $STATE_FILES; do
        if [ ! -f "$f" ] && [ ! -d "$f" ]; then
            sudo docker cp "agent_trader_swarm:/app/$f" "$f" 2>/dev/null || true
        fi
    done
fi

# 3. Stop ALL existing containers (including orphans from previous deploys)
echo "Stopping existing containers..."
sudo docker-compose -f docker-compose.prod.yml down --remove-orphans 2>/dev/null || true

# Also stop any standalone containers with our naming convention
for container in agent_trader_swarm agent_trader_dashboard; do
    if sudo docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "  Stopping orphan container: ${container}"
        sudo docker stop "${container}" 2>/dev/null || true
        sudo docker rm "${container}" 2>/dev/null || true
    fi
done

# 4. Pull latest image
echo "Pulling latest image..."
sudo docker pull europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest
if [ $? -ne 0 ]; then
    echo "❌ Docker pull failed! Check authentication."
    exit 1
fi

# 5. Ensure state files exist as files (not directories) before mounting.
# A bind-mount source that doesn't exist makes Docker create a DIRECTORY in its
# place, which breaks every JSON read — hence the dir-guard + touch below.
echo "Initialising state files..."
for f in dashboard.json trade_log.json active_assets.json $STATE_FILES; do
    if [ -d "$f" ]; then
        sudo rm -rf "$f"
    fi
done
# Empty (0-byte) files behave like "missing" for the app's try/except JSON readers,
# so plain touch is the correct seed — no '{}' vs '[]' type guessing.
for f in $STATE_FILES; do
    [ -f "$f" ] || sudo touch "$f" 2>/dev/null || true
done
[ -f "dashboard.json" ]      || echo '{}' > dashboard.json
[ -f "active_assets.json" ]  || echo '[]' > active_assets.json
[ -f "pnl_snapshots.json" ]  || echo '[]' > pnl_snapshots.json
# Recover trade_log.json from Supabase if missing or empty
if [ ! -f "trade_log.json" ] || [ "$(cat trade_log.json)" = "[]" ] || [ "$(cat trade_log.json)" = "{}" ]; then
    echo "Recovering trade_log.json from Supabase..."
    sudo docker run --rm \
        -e GOOGLE_CLOUD_PROJECT=gen-lang-client-0441524375 \
        europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest \
        python3 -c "
import os, sys, json
os.environ['GOOGLE_CLOUD_PROJECT'] = 'gen-lang-client-0441524375'
from utils.gcp_secrets import get_all_trading_secrets
s = get_all_trading_secrets()
for k,v in s.items():
    if v: os.environ[k] = v
from utils.db_client import DatabaseClient
db = DatabaseClient()
if db.client:
    all_trades = []
    offset = 0
    while True:
        r = db.client.table('trades').select('*').order('created_at', desc=False).range(offset, offset+999).execute()
        all_trades.extend(r.data)
        if len(r.data) < 1000: break
        offset += 1000
    print(json.dumps(all_trades, default=str))
else:
    print('[]')
" > trade_log.json 2>/dev/null || echo '[]' > trade_log.json
    echo "Recovered $(python3 -c "import json; print(len(json.load(open('trade_log.json'))))" 2>/dev/null || echo '?') trades"
fi
sudo mkdir -p logs data config
# Initialise auto_params.json if missing (preserve tuned values if it already exists)
if [ ! -f "config/auto_params.json" ]; then
    echo "Initialising config/auto_params.json with defaults..."
    cat > config/auto_params.json << 'EOF'
{
  "score_threshold": 0.40,
  "tech_prefilter_min": 0.15,
  "scan_universe_size": 12,
  "consecutive_loss_offboard": 3,
  "drawdown_offboard_pct": 5.0,
  "_meta": {
    "last_changed_by": "init",
    "last_changed_at": "2026-03-23T00:00:00+00:00",
    "change_reason": "Initial config"
  },
  "_bounds": {
    "score_threshold": [0.30, 0.50],
    "tech_prefilter_min": [0.05, 0.40],
    "scan_universe_size": [6, 20],
    "consecutive_loss_offboard": [2, 5],
    "drawdown_offboard_pct": [2.0, 10.0]
  },
  "_initial": {
    "score_threshold": 0.40,
    "tech_prefilter_min": 0.15,
    "scan_universe_size": 12,
    "consecutive_loss_offboard": 3,
    "drawdown_offboard_pct": 5.0
  }
}
EOF
fi
# Container runs as trader (UID 1000) — ensure it can write to mounted files/dirs.
# Use sudo: config/auto_params.json is written by the container (owned by UID 1000), so a
# non-sudo chmod fails with "Operation not permitted". Under `set -e` that aborted the whole
# deploy AFTER the old container was stopped but BEFORE `up`, leaving the swarm down. Keep
# this non-fatal so a single unchmod-able file can never take production offline.
sudo chmod 666 dashboard.json trade_log.json active_assets.json pnl_snapshots.json config/auto_params.json 2>/dev/null || true
sudo chmod 666 $STATE_FILES 2>/dev/null || true
sudo chmod 777 logs data config

# 6. Start fresh containers
echo "Starting containers..."
sudo docker-compose -f docker-compose.prod.yml up -d --force-recreate --remove-orphans

# 7. Cleanup old images
echo "Cleaning up old images..."
sudo docker image prune -f 2>/dev/null || true

# 8. Verify
echo ""
echo "=== Container Status ==="
sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo ""
echo "=== Port Check ==="
if sudo docker port agent_trader_swarm 8080 2>/dev/null; then
    echo "✅ Port 8080 mapped correctly"
else
    echo "⚠️ Port 8080 not mapped - check docker-compose.prod.yml"
fi

echo ""
echo "=== Dashboard Health ==="
sleep 3
HTTP_CODE=$(curl -sf -o /dev/null -w '%{http_code}' http://localhost:8080 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Dashboard responding (HTTP ${HTTP_CODE})"
else
    echo "⚠️ Dashboard returned HTTP ${HTTP_CODE} (may need more startup time)"
fi

echo ""
echo "=== Deploy Update Complete ==="
