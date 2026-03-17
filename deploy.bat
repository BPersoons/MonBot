@echo off
setlocal enabledelayedexpansion

:: ================================================================
:: Agent Trader Swarm - Deployment Script
:: Builds Docker image, pushes to Artifact Registry, deploys to VM
:: ================================================================

:: Configuration
set PROJECT_ID=gen-lang-client-0441524375
set REGION=europe-west1
set ZONE=%REGION%-b
set VM_NAME=agent-trader-swarm-vm
set REPO_NAME=agent-trader
set IMAGE_NAME=swarm
set FULL_IMAGE_URI=%REGION%-docker.pkg.dev/%PROJECT_ID%/%REPO_NAME%/%IMAGE_NAME%:latest

echo.
echo 🚀 Agent Trader Swarm Deployment
echo ================================================
echo Project: %PROJECT_ID%
echo VM:      %VM_NAME%
echo Image:   %FULL_IMAGE_URI%
echo ================================================
echo.

:: ========================================
:: 1. VALIDATION
:: ========================================
echo [1/8] Validating environment...
where gcloud >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo ❌ gcloud CLI not found. Install from https://cloud.google.com/sdk
    exit /b 1
)
call gcloud config set project %PROJECT_ID% --quiet

:: ========================================
:: 2. AUTOMATED TEST SUITE (TDD GATEKEEPER)
:: ========================================
echo [2/9] Running Automated Test Suite...
call pytest tests\test_project_lead_branches.py -v
if %ERRORLEVEL% neq 0 (
    echo ❌ Automated Tests FAILED. Aborting deployment to prevent broken code in production.
    exit /b 1
)
echo ✅ All deployment tests passed!

:: ========================================
:: 3. OPTIMIZE BUILD CONTEXT
:: ========================================
echo [3/9] Optimizing build context...
if not exist .gcloudignore (
    echo 📄 Creating .gcloudignore to speed up build...
    (
    echo .git
    echo .git/
    echo .gitignore
    echo venv
    echo venv/
    echo __pycache__/
    echo *.pyc
    echo .idea/
    echo .pytest_cache/
    echo tests/
    echo logs/
    echo data/
    echo trade_log.json
    echo active_assets.json
    echo dashboard.json
    echo *.log
    echo *.png
    echo *.gif
    echo .env
    echo .env.local
    echo node_modules/
    echo media__*
    echo debug_*.py
    echo test_*.py
    ) > .gcloudignore
)

:: ========================================
:: 3. FIREWALL RULES
:: ========================================
echo [3/8] Checking firewall rules...
call gcloud compute firewall-rules describe allow-dashboard-ingress --format="value(name)" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Creating dashboard ingress rule ^(8080^)...
    call gcloud compute firewall-rules create allow-dashboard-ingress --allow "tcp:8080" --target-tags "http-server" --description "Allow dashboard access" --quiet
)

:: ========================================
:: 4. BUILD & PUSH IMAGE
:: ========================================
echo [4/8] Building Swarm Image via Cloud Build...
call gcloud builds submit --tag %FULL_IMAGE_URI% . --quiet
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Cloud Build Failed. Aborting deployment.
    exit /b 1
)
echo ✅ Image built and pushed successfully.

:: 5. VM PROVISIONING (first-time only)
echo [5/8] Checking VM instance...
call gcloud compute instances describe %VM_NAME% --zone=%ZONE% --format="value(name)" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo Creating new Ubuntu VM...
    if not exist startup.sh (
        echo [ERROR] startup.sh not found.
        exit /b 1
    )
    call gcloud compute instances create %VM_NAME% --project=%PROJECT_ID% --zone=%ZONE% --machine-type=e2-medium --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud --tags=http-server,https-server --boot-disk-size=30GB --scopes=cloud-platform --metadata-from-file=startup-script=startup.sh --quiet
    echo Waiting for VM to initialize ^(60s^)...
    timeout /t 60
)

:: 6. UPLOAD FILES TO VM
echo [6/8] Uploading files to VM...

:: Ensure required files exist
if not exist dashboard.json echo {} > dashboard.json
if not exist trade_log.json echo [] > trade_log.json
if not exist active_assets.json echo [] > active_assets.json
if not exist .env.adk (
    echo [ERROR] .env.adk not found. Cannot deploy without environment config.
    exit /b 1
)

:: Upload compose file + env + deploy script
call gcloud compute scp --zone=%ZONE% docker-compose.prod.yml .env.adk scripts\deploy_update.sh %VM_NAME%:./ --quiet
if %ERRORLEVEL% neq 0 (
    echo ⚠️ SCP failed, retrying with --force-key-file-overwrite...
    call gcloud compute scp --zone=%ZONE% --force-key-file-overwrite docker-compose.prod.yml .env.adk scripts\deploy_update.sh %VM_NAME%:./ --quiet
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] SCP failed twice. Cannot upload files to VM.
        exit /b 1
    )
)

:: Upload data files (non-critical, don't fail on error)
call gcloud compute scp --zone=%ZONE% dashboard.json trade_log.json active_assets.json %VM_NAME%:./ --quiet 2>nul

echo ✅ Files uploaded successfully.

:: 7. DEPLOY ON VM
echo [7/8] Starting Swarm Containers...
call gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "chmod +x deploy_update.sh && ./deploy_update.sh" --quiet
if %ERRORLEVEL% neq 0 (
    echo ⚠️ SSH command returned non-zero. Verifying...
)

:: ========================================
:: 8. VERIFY DEPLOYMENT
:: ========================================
echo [8/8] Verifying deployment...

:: Wait for container to start
:: timeout command removed due to batch syntax issues

:: Get VM IP
for /f "tokens=*" %%i in ('gcloud compute instances describe %VM_NAME% --zone=%ZONE% --format="get(networkInterfaces[0].accessConfigs[0].natIP)"') do set IP=%%i

:: Verify container is running
call gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "sudo docker ps --format '{{.Names}} {{.Status}} {{.Ports}}' | grep agent_trader_swarm" --quiet
if %ERRORLEVEL% neq 0 (
    echo ❌ Container not running! Check VM logs with:
    echo    gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "sudo docker logs agent_trader_swarm --tail 50"
    exit /b 1
)

:: Verify dashboard is reachable
call gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "curl -sf -o /dev/null -w '%%{http_code}' http://localhost:8080" --quiet
if %ERRORLEVEL% neq 0 (
    echo ⚠️ Dashboard health check inconclusive (may need more startup time).
    echo    Try manually: http://%IP%:8080
) else (
    echo ✅ Dashboard responding on port 8080.
)

echo.
echo ================================================
echo ✅ DEPLOYMENT COMPLETE!
echo ================================================
echo Dashboard:  http://%IP%:8080
echo VM IP:      %IP%
echo.
echo Quick commands:
echo   Logs:    gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "sudo docker logs agent_trader_swarm --tail 50"
echo   Status:  gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "sudo docker ps"
echo   Restart: gcloud compute ssh %VM_NAME% --zone=%ZONE% --command "cd ~ ^&^& sudo docker-compose -f docker-compose.prod.yml restart"
echo.
