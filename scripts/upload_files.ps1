$ErrorActionPreference = "Stop"

$PROJECT_ID = "gen-lang-client-0441524375"
$REGION = "europe-west1"
$ZONE = "$REGION-b"
$VM_NAME = "agent-trader-swarm-vm"

Write-Host "Uploading deploy_update.sh..."
$deployScript = @"
#!/bin/bash
set -e

# Install docker if not present
if ! command -v docker &> /dev/null; then 
    sudo apt-get update && sudo apt-get install -y docker.io docker-compose
fi

# Authenticate
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

# Pull and Update
sudo docker-compose -f docker-compose.prod.yml pull
sudo docker-compose -f docker-compose.prod.yml up -d --remove-orphans
sudo docker image prune -f
"@

# Use line endings that Linux understands (LF) - PowerShell strings are usually CRLF
$deployScript = $deployScript -replace "`r`n", "`n"

# Pipe content to remote cat
$deployScript | gcloud compute ssh $VM_NAME --zone=$ZONE --command "cat > deploy_update.sh && chmod +x deploy_update.sh" --quiet

Write-Host "Uploading docker-compose.prod.yml..."
$dockerCompose = Get-Content -Path "docker-compose.prod.yml" -Raw
$dockerCompose = $dockerCompose -replace "`r`n", "`n"

$dockerCompose | gcloud compute ssh $VM_NAME --zone=$ZONE --command "cat > docker-compose.prod.yml" --quiet

Write-Host "Triggering Update..."
gcloud compute ssh $VM_NAME --zone=$ZONE --command "./deploy_update.sh" --quiet

Write-Host "Done!"
