#!/bin/bash
set -e

echo "=== Agent Trader Deploy Update ==="

# 0. Canonical working directory — the ONLY place docker-compose may ever run
# from. Bind-mount sources in docker-compose.prod.yml are relative paths, so
# the compose working dir determines WHICH host files the container gets. CI
# runs this script as the service account (lands in /home/sa_.../), manual
# deploys as bartpersoons_gmail_com — before this block, each created its own
# parallel state universe. On 2026-07-16 that turned a botched deploy into
# apparent total state loss (data sat untouched in the other home dir).
# Fix: the script relocates itself; the caller's cwd no longer matters.
CANONICAL_DIR="/home/bartpersoons_gmail_com"
if [ "$(pwd)" != "$CANONICAL_DIR" ]; then
    echo "Relocating deploy from $(pwd) to canonical dir $CANONICAL_DIR ..."
    sudo mkdir -p "$CANONICAL_DIR"
    sudo chmod 755 "$CANONICAL_DIR" 2>/dev/null || true
    # Bring freshly-uploaded artifacts along (CI scps compose+script to its
    # own home; those are the newest versions and must win in canonical).
    for f in docker-compose.prod.yml deploy_update.sh .env.adk; do
        if [ -f "$f" ]; then
            sudo cp "$f" "$CANONICAL_DIR/$f"
        fi
    done
    cd "$CANONICAL_DIR"
    echo "Now in $(pwd)"
fi

# 1. Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    sudo apt-get update && sudo apt-get install -y docker.io docker-compose
fi

# 2. Configure Docker auth for Artifact Registry (MUST use sudo so Docker daemon can access creds)
echo "Configuring Docker authentication..."
sudo gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet 2>/dev/null || true

# 2a. Backup every current state file to a timestamped folder BEFORE anything
# destructive happens. Host-filesystem-only — does NOT require the old
# container to be running. This is the safety net that was missing on
# 2026-07-16: a botched deploy stopped the old container without a live
# replacement ready, so the (container-only) preserve step below had nothing
# to recover from and ~15 state files got silently touch-emptied. With this
# backup in place, the touch-loop in step 5 restores from here instead.
STATE_FILES="shadow_book.json shadow_report.json shadow_basis_state.json shadow_basis_log.json shadow_basis_report.json shadow_xyz_funding_state.json shadow_xyz_funding_log.json shadow_xyz_funding_report.json shadow_xyz_gap_state.json shadow_xyz_gap_log.json shadow_xyz_gap_report.json shadow_xyz_listings_state.json shadow_xyz_listings_log.json shadow_xyz_listings_report.json ticker_state.json decision_history.json treasury_harvest.json treasury_proposals.json audited_trades.json portfolio_peak.json cost_log.json polymarket_shadow_log.json config/treasury_allocation.json config/sleeves.json thematic_exposure_state.json thematic_exposure_positions.json thematic_exposure_report.json thematic_wallet_peak.json positions_status.json conviction_core_state.json"
sudo mkdir -p config
BACKUP_DIR="state_backups/$(date -u +%Y%m%d_%H%M%S)"
backed_up=0
for f in $STATE_FILES config/auto_params.json config/thematic_exposure_themes.json config/conviction_core.json config/barbell_targets.json dashboard.json trade_log.json active_assets.json pnl_snapshots.json; do
    if [ -s "$f" ]; then  # -s: exists AND non-empty — never back up an already-empty file
        sudo mkdir -p "$BACKUP_DIR/$(dirname "$f")" 2>/dev/null || true
        if sudo cp "$f" "$BACKUP_DIR/$f" 2>/dev/null; then
            backed_up=$((backed_up + 1))
        fi
    fi
done
echo "State backup: $BACKUP_DIR ($backed_up files)"
# Keep only the 10 most recent backups so this doesn't grow unbounded.
ls -1dt state_backups/*/ 2>/dev/null | tail -n +11 | xargs -r sudo rm -rf

# 2b. Preserve container-local state BEFORE stopping the old container.
# Newly volume-mounted state files must start life on the host as a copy of the
# running container's freshest state — otherwise the empty host file shadows it.
# Only copies when the host file is missing; on later deploys the host file IS the
# state (volume mount), so this is a no-op. Non-fatal by design (set -e safety).
# Secondary to the backup above: this only helps when the OLD container is still
# running (e.g. a genuinely new mount on an otherwise-healthy deploy); the
# 2026-07-16 incident happened precisely because it wasn't.
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
# so plain touch is the correct seed — no '{}' vs '[]' type guessing. If a file
# is missing here, first try restoring it from the backup taken in step 2a
# (covers exactly the 2026-07-16 failure mode: old container gone, nothing to
# docker cp from) before falling back to an empty touch. Either way, log it —
# a silent touch-empty is how ~15 files vanished unnoticed that day.
# Sinds 2026-07-30 stuurt deploy.ps1 dashboard.json/trade_log.json/active_assets.json
# NIET meer mee (die overschreven de live boekhouding met een dev-snapshot — zie de
# waarschuwing in deploy.ps1). Ze horen dus in dezelfde restore-uit-backup-behandeling
# als de andere state: op de host aanwezig = leidend, ontbrekend = uit backup terug.
LATEST_BACKUP=$(ls -1dt state_backups/*/ 2>/dev/null | head -1)
for f in $STATE_FILES dashboard.json trade_log.json active_assets.json pnl_snapshots.json; do
    if [ ! -f "$f" ]; then
        if [ -n "$LATEST_BACKUP" ] && [ -s "${LATEST_BACKUP}${f}" ]; then
            echo "⚠️  $f missing on host — restoring from backup $LATEST_BACKUP"
            sudo mkdir -p "$(dirname "$f")" 2>/dev/null
            sudo cp "${LATEST_BACKUP}${f}" "$f" 2>/dev/null || sudo touch "$f" 2>/dev/null || true
        else
            echo "⚠️  $f missing on host and no backup available — initialising EMPTY (any prior data is lost)"
            sudo touch "$f" 2>/dev/null || true
        fi
    fi
done
# Vangnet: een 0-byte touch uit de lus hierboven is voor deze vier geen geldige JSON-vorm.
# trade_log.json stond hier tot 2026-07-30 NIET bij — die kwam altijd via scp mee, en
# zonder dat vangnet zou een ontbrekend bestand een Docker-DIRECTORY worden.
[ -s "dashboard.json" ]      || echo '{}' > dashboard.json
[ -s "trade_log.json" ]      || echo '[]' > trade_log.json
[ -s "active_assets.json" ]  || echo '[]' > active_assets.json
[ -s "pnl_snapshots.json" ]  || echo '[]' > pnl_snapshots.json
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
# Initialise config/thematic_exposure_themes.json from the freshly-pulled image if
# missing on host (EXP-008). Unlike the plain STATE_FILES above, this file
# ships pre-seeded (5 themes + 19 CONFIRMED tickers) — touching it empty like
# a runtime state file would silently wipe that seed on the very first deploy
# after this mount was added, so it's extracted from the image instead.
if [ ! -f "config/thematic_exposure_themes.json" ]; then
    echo "Seeding config/thematic_exposure_themes.json from image..."
    sudo docker run --rm europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest \
        cat /app/config/thematic_exposure_themes.json > config/thematic_exposure_themes.json 2>/dev/null \
        || echo '{"themes":{},"tickers":{},"pending":{}}' > config/thematic_exposure_themes.json
fi
# Conviction Barbell configs (2026-07-28): same reasoning as the themes file above —
# these carry real settings (target_usd, enabled, band-parameters), NOT runtime state,
# so they must never be touch-emptied. Seed from the image when the host copy is
# missing; once present, the host copy wins (that's where target_usd/enabled get
# flipped without a rebuild).
for cfg in conviction_core barbell_targets; do
    if [ ! -f "config/${cfg}.json" ]; then
        echo "Seeding config/${cfg}.json from image..."
        sudo docker run --rm europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest \
            cat "/app/config/${cfg}.json" > "config/${cfg}.json" 2>/dev/null \
            || echo '{}' > "config/${cfg}.json"
    fi
done
# Container runs as trader (UID 1000) — ensure it can write to mounted files/dirs.
# Use sudo: config/auto_params.json is written by the container (owned by UID 1000), so a
# non-sudo chmod fails with "Operation not permitted". Under `set -e` that aborted the whole
# deploy AFTER the old container was stopped but BEFORE `up`, leaving the swarm down. Keep
# this non-fatal so a single unchmod-able file can never take production offline.
sudo chmod 666 dashboard.json trade_log.json active_assets.json pnl_snapshots.json config/auto_params.json config/thematic_exposure_themes.json config/conviction_core.json config/barbell_targets.json 2>/dev/null || true
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
