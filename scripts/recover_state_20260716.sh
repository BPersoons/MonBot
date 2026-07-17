#!/bin/bash
# One-off recovery, 2026-07-16 (EXP-008 deploy incident).
# The "lost" state files were never lost: previous deploys ran docker-compose
# from /home/sa_116183673897831795495/ (the CI service-account home — see
# memory note reference_ci_deploy_trigger_and_dirs), while today's manual
# deploy ran from /home/bartpersoons_gmail_com/ and created a parallel set of
# EMPTY host files that the new container mounted. This script restores the
# real data (SA home, timestamps up to 12:56 — minutes before the incident)
# into the currently-mounted bartpersoons files, merging the handful of
# records created since 13:00 (one open trade, two treasury proposals).
set -e

SA=/home/sa_116183673897831795495
CUR=/home/bartpersoons_gmail_com
BK="$CUR/pre_recovery_backup_$(date -u +%H%M%S)"

cd "$CUR"

echo "=== 1. Backup current (post-incident) files to $BK ==="
mkdir -p "$BK/config" "$BK/data"
for f in dashboard.json trade_log.json decision_history.json shadow_book.json \
         shadow_report.json ticker_state.json cost_log.json pnl_snapshots.json \
         portfolio_peak.json audited_trades.json treasury_proposals.json \
         active_assets.json shadow_xyz_gap_state.json shadow_xyz_listings_state.json \
         config/auto_params.json config/treasury_allocation.json data/sleeve_nav.json; do
    [ -f "$f" ] && sudo cp "$f" "$BK/$f" || true
done
echo "backed up: $(sudo find "$BK" -type f | wc -l) files"

echo "=== 2. Stop container (brief downtime) ==="
sudo docker stop agent_trader_swarm

echo "=== 3. Restore wholesale files from SA home ==="
# NOT restored on purpose: config/sleeves.json (current version is newer:
# thematic_dip sleeve + venue cap 60), config/thematic_dip_themes.json (only
# exists in CUR), active_assets.json (pipeline-rebuilt, current reflects now),
# treasury_harvest.json (0 bytes both sides = IDLE).
for f in dashboard.json decision_history.json shadow_book.json shadow_report.json \
         ticker_state.json cost_log.json pnl_snapshots.json portfolio_peak.json \
         audited_trades.json shadow_xyz_gap_state.json shadow_xyz_listings_state.json; do
    if sudo test -s "$SA/$f"; then
        sudo cp "$SA/$f" "$CUR/$f"
        echo "restored $f ($(sudo stat -c%s "$CUR/$f") bytes)"
    else
        echo "skip $f (empty/missing in SA home)"
    fi
done
sudo cp "$SA/data/sleeve_nav.json" "$CUR/data/sleeve_nav.json" && echo "restored data/sleeve_nav.json"
sudo cp "$SA/config/auto_params.json" "$CUR/config/auto_params.json" && echo "restored config/auto_params.json (tuned Jul 2)"
sudo cp "$SA/config/treasury_allocation.json" "$CUR/config/treasury_allocation.json" && echo "restored config/treasury_allocation.json (learned Jul 6)"

echo "=== 4. Merge trade_log (SA history + post-incident records by id) ==="
sudo python3 - <<'PYEOF'
import json
sa = json.load(open("/home/sa_116183673897831795495/trade_log.json"))
cur = json.load(open("/home/bartpersoons_gmail_com/pre-merge-tmp.json")) if False else None
try:
    cur = json.load(open("/home/bartpersoons_gmail_com/trade_log.json"))
except Exception:
    cur = []
sa_ids = {t.get("id") for t in sa}
added = [t for t in cur if t.get("id") not in sa_ids]
merged = sa + added
json.dump(merged, open("/home/bartpersoons_gmail_com/trade_log.json", "w"), indent=1)
print(f"trade_log: {len(sa)} historical + {len(added)} new post-incident = {len(merged)}")
for t in added:
    print("  kept new:", t.get("id"), t.get("ticker"), t.get("status"))
PYEOF

echo "=== 5. Merge treasury_proposals (SA history + today's new by id) ==="
sudo python3 - <<'PYEOF'
import json
sa = json.load(open("/home/sa_116183673897831795495/treasury_proposals.json"))
try:
    cur = json.load(open("/home/bartpersoons_gmail_com/treasury_proposals.json"))
except Exception:
    cur = []
sa_ids = {p.get("id") for p in sa}
added = [p for p in cur if p.get("id") not in sa_ids]
merged = sa + added
json.dump(merged, open("/home/bartpersoons_gmail_com/treasury_proposals.json", "w"), indent=2)
print(f"proposals: {len(sa)} historical + {len(added)} new = {len(merged)}")
PYEOF

echo "=== 6. Permissions (container runs as uid 1000) ==="
sudo chmod 666 "$CUR"/*.json "$CUR"/config/*.json "$CUR"/data/*.json 2>/dev/null || true

echo "=== 7. Start container ==="
sudo docker start agent_trader_swarm
sleep 25
HTTP=$(curl -sf -o /dev/null -w '%{http_code}' http://localhost:8080 2>/dev/null || echo 000)
echo "Dashboard HTTP: $HTTP"
echo "=== Recovery complete ==="
