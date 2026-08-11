# Agent Trader - Swarm Deployment Script (PowerShell)
# Orchestrates Agent on Ubuntu VM

$ErrorActionPreference = "Stop"

# Configuration
$Env:PROJECT_ID = if ($Env:GCP_PROJECT_ID) { $Env:GCP_PROJECT_ID } else { "gen-lang-client-0441524375" }
$Env:REGION = if ($Env:GCP_REGION) { $Env:GCP_REGION } else { "europe-west1" }
$ZONE = "$($Env:REGION)-b"
$VM_NAME = "agent-trader-swarm-vm"
$REPO_NAME = "agent-trader"
$IMAGE_NAME = "swarm"
$MACHINE_TYPE = "e2-medium"
$FULL_IMAGE_URI = "$($Env:REGION)-docker.pkg.dev/$($Env:PROJECT_ID)/$REPO_NAME/${IMAGE_NAME}:latest"

Write-Host "🚀 Agent Trader Swarm Deployment" -ForegroundColor Blue
Write-Host "================================================"
Write-Host "Project: $($Env:PROJECT_ID)"
Write-Host "VM:      $VM_NAME ($MACHINE_TYPE)"
Write-Host "================================================"

# 1. Validation
if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    Write-Error "❌ gcloud not found."
    exit 1
}
gcloud config set project $Env:PROJECT_ID --quiet

# 1.1 Pre-Flight Checks
Write-Host "🔍 Running Pre-Flight Checks..." -ForegroundColor Yellow
Write-Host "Running Import Check..."
python -m tests.pre_flight.check_imports
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Import Check Failed! Aborting deployment."
    exit 1
}

Write-Host "Running Connection Check..."
python -m tests.pre_flight.check_connections
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Connection Check Failed! Aborting deployment."
    exit 1
}

Write-Host "Running Pipeline Contract Check..."
python -m tests.pre_flight.check_pipeline
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ Pipeline Contract Check Failed! Fix agent signatures before deploying."
    exit 1
}
Write-Host "✅ Pre-Flight Checks Passed." -ForegroundColor Green


# 2. Build & Push Agent Image
Write-Host "🔨 Building Swarm Image..." -ForegroundColor Yellow
gcloud builds submit --tag $FULL_IMAGE_URI . --quiet

# 4. VM Provisioning
Write-Host "☁️ Managing VM Instance..." -ForegroundColor Yellow
$vmExists = gcloud compute instances describe $VM_NAME --zone=$ZONE --format="value(name)"

if (-not $vmExists) {
    Write-Host "Creating new Ubuntu VM..."
    # Ensure startup.sh exists
    if (-not (Test-Path "startup.sh")) {
        Write-Error "startup.sh not found!"
        exit 1
    }
    
    # Quoted arguments to prevent PowerShell parser splitting
    gcloud compute instances create $VM_NAME --project=$Env:PROJECT_ID --zone=$ZONE --machine-type=$MACHINE_TYPE --image-family "ubuntu-2204-lts" --image-project "ubuntu-os-cloud" --tags "http-server,https-server" --boot-disk-size "30GB" --scopes "cloud-platform" --metadata-from-file "startup-script=startup.sh" --quiet
    
    Write-Host "Waiting for VM to initialize (30s)..."
    Start-Sleep -Seconds 30
}

# 5. Remote Docker Compose: the committed docker-compose.prod.yml is the
# source of truth (full state-file volume-mount list, image URI already
# matches $FULL_IMAGE_URI, secrets via GCP Secret Manager not env_file).
# Previously this step REGENERATED the file from a stale 3-mount template
# (env_file: .env.adk, missing ~25 state-file mounts added since) and
# overwrote the real file with it before every deploy — silently wiping
# every volume mount not in that template on the next `docker-compose up`.
# Fixed 2026-07-16: just validate the real file exists; never regenerate it.
if (-not (Test-Path "docker-compose.prod.yml")) {
    Write-Error "docker-compose.prod.yml missing!"
    exit 1
}

# 6. Deploy Code & Config
Write-Host "📤 Deploying configuration to VM..." -ForegroundColor Yellow

# Ensure blank files exist if missing
if (-not (Test-Path "dashboard.json")) { Set-Content "dashboard.json" "{}" }
if (-not (Test-Path "trade_log.json")) { Set-Content "trade_log.json" "[]" }
if (-not (Test-Path "active_assets.json")) { Set-Content "active_assets.json" "[]" }
if (-not (Test-Path ".env.adk")) { Set-Content ".env.adk" "" }
# Check for local script path using Windows conventions
if (-not (Test-Path "scripts\deploy_update.sh")) {
    Write-Error "scripts\deploy_update.sh missing!"
    exit 1
}

# Resolve the remote home dir explicitly — Windows' bundled pscp has a known
# bug where a multi-file `gcloud compute scp` to a bare `~/` destination fails
# with "remote filespec ~/: not a directory" (hit 2026-07-16: silently left
# the VM on a stale deploy_update.sh, which crashed mid-run and took prod
# offline). An explicit absolute path avoids the bug entirely.
$remoteHome = (gcloud compute ssh $VM_NAME --zone=$ZONE --command 'echo $HOME' --quiet | Select-Object -Last 1).Trim()
if (-not $remoteHome) {
    Write-Error "❌ Could not resolve remote home directory via SSH. Aborting deployment."
    exit 1
}

# Normalize deploy_update.sh to LF before upload. Previously CRLF was
# stripped remotely via `sed -i "s/\r$//"` through `gcloud compute ssh
# --command` — that string crosses four quoting layers (PowerShell -> gcloud
# -> Windows' plink.exe -> remote shell) and silently failed to strip the CR
# on 2026-07-18 (deploy_update.sh still had a \r shebang afterwards and
# crashed with "bad interpreter: /bin/bash^M"), even though the same command
# had worked before. Fixing the line endings locally removes that fragile
# chain from the critical path entirely — scp then uploads an already-clean
# file, and the remote sed (kept below) is just cheap defense-in-depth.
$tmpDir = Join-Path $env:TEMP "agent_trader_deploy_$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $tmpDir | Out-Null
$lfScriptPath = Join-Path $tmpDir "deploy_update.sh"
$deployScriptContent = [System.IO.File]::ReadAllText("$PWD\scripts\deploy_update.sh") -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($lfScriptPath, $deployScriptContent)

# Quoted paths
# We copy deploy_update.sh as well (LF-normalized temp copy, see above)
#
# ⚠️ NOOIT state-bestanden meesturen (trade_log.json / dashboard.json /
# active_assets.json / *_state.json). Die zijn volume-mounted op de VM: productie
# IS de bron van waarheid, de dev-machine niet. Tot 2026-07-30 stonden ze wél in
# deze regel, en dat was de oorzaak van een keten incidenten: elke full deploy
# overschreef de live boekhouding met een lokale snapshot van 17 juli waarin 6
# posities op OPEN stonden. De swarm zag daarna 6 "open" posities die Hyperliquid
# niet had, stuurde sluit-orders, en die openden echte shorts ($2.107 notional op
# 24-07, $128 op 28-07) mét fictieve winst in het log. Dit verklaart ook het
# onopgehelderde 436->6 trade_log-verlies van 17-07.
# deploy_update.sh maakt deze bestanden zelf aan als ze op de host ontbreken.
gcloud compute scp --zone=$ZONE docker-compose.prod.yml .env.adk $lfScriptPath "${VM_NAME}:${remoteHome}/" --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ SCP to VM failed (exit $LASTEXITCODE) — deploy_update.sh may be stale on the VM. Aborting rather than risk running an old script against the new image."
    exit 1
}
Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue

# 7. Start Services
Write-Host "🚀 Starting Swarm Containers..." -ForegroundColor Yellow

# Execute the uploaded script. The remote `sed -i 's/\r$//'` is now just a
# defensive no-op (the uploaded file is already LF) — kept in case anything
# other than this script's scp step ever lands a CRLF copy on the VM.
gcloud compute ssh $VM_NAME --zone=$ZONE --command 'sed -i "s/\r$//" deploy_update.sh && chmod +x deploy_update.sh && ./deploy_update.sh' --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "❌ deploy_update.sh failed on the VM (exit $LASTEXITCODE). Container may be down — check manually: gcloud compute ssh $VM_NAME --zone=$ZONE --command 'sudo docker ps -a'"
    exit 1
}

# 8. Access Info
$IP = gcloud compute instances describe $VM_NAME --zone=$ZONE --format="get(networkInterfaces[0].accessConfigs[0].natIP)"
Write-Host ""
Write-Host "✅ DEPLOYMENT COMPLETE!" -ForegroundColor Green
Write-Host "------------------------------------------------"
Write-Host "VM IP Address:  $IP"
Write-Host ""
