#!/bin/bash
# PostToolUse hook: verify dashboard after docker restart/start
# Only triggers when the Bash command actually restarts the container.

INPUT=$(cat)
CMD=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only act on commands that restart or start the container
if ! echo "$CMD" | grep -qE "docker (restart|start) agent_trader_swarm"; then
    exit 0
fi

echo "⏳ Container restart detected — verifying dashboard in 50s..." >&2
sleep 50

STATUS=$(gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \
    --command='curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/' 2>/dev/null)

if [ "$STATUS" = "200" ]; then
    echo "✅ Dashboard verified: HTTP 200" >&2
    exit 0
elif [ -z "$STATUS" ] || [ "$STATUS" = "000" ]; then
    # Dashboard not yet up — retry once after 15s
    echo "⏳ Dashboard not ready (HTTP ${STATUS:-000}), retrying in 15s..." >&2
    sleep 15
    STATUS=$(gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \
        --command='curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/' 2>/dev/null)
    if [ "$STATUS" = "200" ]; then
        echo "✅ Dashboard verified on retry: HTTP 200" >&2
        exit 0
    fi
fi

# Failed — fetch logs for diagnosis
echo "❌ Dashboard check FAILED: HTTP ${STATUS:-000}" >&2
echo "Fetching last 20 lines of container logs..." >&2
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \
    --command='sudo docker logs agent_trader_swarm 2>&1 | tail -20' 2>/dev/null >&2
exit 2
