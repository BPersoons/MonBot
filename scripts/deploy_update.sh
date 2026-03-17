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

# 5. Ensure state files exist as files (not directories) before mounting
echo "Initialising state files..."
for f in dashboard.json trade_log.json active_assets.json; do
    if [ -d "$f" ]; then
        sudo rm -rf "$f"
    fi
    [ -f "$f" ] || echo '{}' > "$f"
done
# trade_log and active_assets are arrays
[ "$(cat trade_log.json)" = '{}' ] && echo '[]' > trade_log.json
[ "$(cat active_assets.json)" = '{}' ] && echo '[]' > active_assets.json
sudo mkdir -p logs data

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
