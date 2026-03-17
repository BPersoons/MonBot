#!/bin/bash
set -e

echo "=== Writing clean docker-compose.prod.yml ==="

cat > docker-compose.prod.yml << 'EOF'
version: '3.8'
services:
  agent-trader:
    image: europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest
    container_name: agent_trader_swarm
    restart: always
    ports:
      - "8080:8080"
    env_file: .env.adk
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./dashboard.json:/app/dashboard.json
      - ./trade_log.json:/app/trade_log.json
      - ./active_assets.json:/app/active_assets.json
    networks: [trader_net]

networks:
  trader_net:
    driver: bridge
EOF

echo "=== Config written. Verifying ==="
cat docker-compose.prod.yml

echo "=== Stopping containers ==="
sudo docker-compose -f docker-compose.prod.yml down || true

echo "=== Starting containers ==="
sudo docker-compose -f docker-compose.prod.yml up -d

echo "=== Container status ==="
sudo docker ps

echo "=== Port mappings ==="
sudo docker port agent_trader_swarm

echo "=== Testing dashboard ==="
sleep 5
curl -s -o /dev/null -w "HTTP_CODE: %{http_code}\n" http://localhost:8080 || echo "Dashboard not ready yet"

echo "=== DONE ==="
