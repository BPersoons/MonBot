#!/bin/bash
# ============================================
# Agent Trader - Swarm Deployment Script (v2)
# Orchestrates Agent on Ubuntu VM
# ============================================
set -e

# Configuration
export PROJECT_ID="${GCP_PROJECT_ID:-gen-lang-client-0441524375}"
export REGION="${GCP_REGION:-europe-west1}"
export ZONE="${REGION}-b"
export VM_NAME="agent-trader-swarm-vm" # Renamed to avoid conflict/ensure fresh start
export REPO_NAME="agent-trader"
export IMAGE_NAME="swarm"
export MACHINE_TYPE="e2-medium" # 2 vCPU, 4GB RAM

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

echo -e "${BLUE}🚀 Agent Trader Swarm Deployment${NC}"
echo "================================================"
echo "Project: $PROJECT_ID"
echo "VM:      $VM_NAME ($MACHINE_TYPE)"
echo "================================================"

# 1. Validation
if ! command -v gcloud &> /dev/null; then echo -e "${RED}❌ gcloud not found.${NC}"; exit 1; fi
gcloud config set project $PROJECT_ID --quiet

# 1.1 Pre-Flight Checks
echo -e "${YELLOW}🔍 Running Pre-Flight Checks...${NC}"
echo "Running Import Check..."
python3 -m tests.pre_flight.check_imports
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Import Check Failed! Aborting deployment.${NC}"
    exit 1
fi

echo "Running Connection Check..."
python3 -m tests.pre_flight.check_connections
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Connection Check Failed! Aborting deployment.${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Pre-Flight Checks Passed.${NC}"


# 2. Build & Push Agent Image
echo -e "${YELLOW}🔨 Building Swarm Image...${NC}"
gcloud builds submit --tag ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest . --quiet

# 4. VM Provisioning
echo -e "${YELLOW}☁️ Managing VM Instance...${NC}"

# Check if VM exists
if ! gcloud compute instances describe $VM_NAME --zone=$ZONE &>/dev/null; then
    echo "Creating new Ubuntu VM..."
    gcloud compute instances create $VM_NAME \
        --project=$PROJECT_ID \
        --zone=$ZONE \
        --machine-type=$MACHINE_TYPE \
        --image-family=ubuntu-2204-lts \
        --image-project=ubuntu-os-cloud \
        --tags=http-server,https-server \
        --boot-disk-size=30GB \
        --scopes=cloud-platform \
        --metadata=startup-script='#! /bin/bash
        apt-get update
        apt-get install -y docker.io docker-compose
        usermod -aG docker paramiko # Add default user? We usually ssh as current gcloud user
        systemctl enable docker
        systemctl start docker
        ' --quiet
    
    echo "Waiting for VM to initialize (30s)..."
    sleep 30
else
    echo -e "${GREEN}✓ VM exists.${NC} (Note: Ensure it is Ubuntu with Docker installed if repurposed)"
fi

# 5. Prepare Remote Docker Compose
# We generate a prod-specific compose file that uses the REGISTRY image instead of build: .
echo -e "${YELLOW}📄 Generating Production Config...${NC}"
cat > docker-compose.prod.yml <<EOF
version: '3.8'
services:
  agent-trader:
    image: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:latest
    container_name: agent_trader_swarm
    restart: always
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

# 6. Deploy Code & Config
echo -e "${YELLOW}📤 Deploying configuration to VM...${NC}"

# Ensure files exist locally
touch dashboard.json trade_log.json active_assets.json .env.adk

# SCP files
gcloud compute scp --zone=$ZONE \
    docker-compose.prod.yml \
    .env.adk \
    dashboard.json \
    trade_log.json \
    active_assets.json \
    $VM_NAME:~/ --quiet

# 7. Start Services
echo -e "${YELLOW}🚀 Starting Swarm Containers...${NC}"
gcloud compute ssh $VM_NAME --zone=$ZONE --command="
    # Install docker if not present (fallback for existing VMs)
    if ! command -v docker &> /dev/null; then
        sudo apt-get update && sudo apt-get install -y docker.io docker-compose
    fi
    
    # Authenticate Docker to Artifact Registry
    gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet
    
    # Pull latest images
    sudo docker-compose -f docker-compose.prod.yml pull
    
    # Start (Recreate only if changed)
    sudo docker-compose -f docker-compose.prod.yml up -d --remove-orphans
    
    # Prune old images to save space
    sudo docker image prune -f
" --quiet

# 8. Access Info
IP=$(gcloud compute instances describe $VM_NAME --zone=$ZONE --format='get(networkInterfaces[0].accessConfigs[0].natIP)')
echo ""
echo -e "${GREEN}✅ DEPLOYMENT COMPLETE!${NC}"
echo "------------------------------------------------"
echo "VM IP Address:  ${IP}"
echo "------------------------------------------------"

