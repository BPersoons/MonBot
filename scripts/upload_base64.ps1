$ErrorActionPreference = "Stop"

$PROJECT_ID = "gen-lang-client-0441524375"
$REGION = "europe-west1"
$ZONE = "$REGION-b"
$VM_NAME = "agent-trader-swarm-vm"

Write-Host "Encoding docker-compose.prod.yml..."
# Read file and encode to Base64 (using .NET for speed/safety)
$bytes = [System.IO.File]::ReadAllBytes("docker-compose.prod.yml")
$b64 = [System.Convert]::ToBase64String($bytes)

Write-Host "Uploading docker-compose.prod.yml via Base64..."
# We use single quotes for the command to protect the base64 string from shell expansion
# But we need to be careful if base64 contains special chars? Base64 is alphanumeric + `+` `/` `=`.
# `+` `.` `/` `=` are safe in single quotes.
gcloud compute ssh $VM_NAME --zone=$ZONE --command "echo '$b64' | base64 -d > docker-compose.prod.yml" --quiet

Write-Host "Running Update Commands..."
# We run the commands directly
$updateCmd = "
sudo apt-get update && sudo apt-get install -y docker.io docker-compose
# Explicit login for sudo user using token from current gcloud session
sudo docker login -u oauth2accesstoken -p "`$(gcloud auth print-access-token)" https://$REGION-docker.pkg.dev
sudo docker-compose -f docker-compose.prod.yml pull
sudo docker-compose -f docker-compose.prod.yml up -d --remove-orphans
sudo docker image prune -f
"

# Replace newlines with && or just run as a big script block
# Running as a script block is better for readability if we wrap in bash -c
# But simple concatenation with && is robust.
# Actually, gcloud ssh accepts newlines if quoted properly.
# But let's be safe and use a single line with semicolons.
$updateCmdLine = $updateCmd -replace "`r`n", ";" -replace "`n", ";"

gcloud compute ssh $VM_NAME --zone=$ZONE --command "$updateCmdLine" --quiet

Write-Host "Done!"
