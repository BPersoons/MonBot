# Hot-patch Deploy

Hot-patch one or more Python files to the production container on GCP.

## Arguments
$ARGUMENTS — space-separated file paths relative to project root (e.g. `agents/execution_agent.py utils/exchange_client.py`)

## Steps — execute ALL steps in order, stop on first failure

### 1. Pre-flight contract check
Run `python -m tests.pre_flight.check_pipeline` from the project root. If it fails, STOP and report the error. Do not proceed to deployment.

### 2. SCP files to VM
For each file in $ARGUMENTS, run:
```
gcloud compute scp <project_root>/<file> agent-trader-swarm-vm:/tmp/<basename> --zone=europe-west1-b
```
Use the file's basename for the /tmp destination (e.g. `agents/execution_agent.py` → `/tmp/execution_agent.py`).

### 3. Docker cp + restart
For each file, inject into the container preserving the original path:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker cp /tmp/<basename> agent_trader_swarm:/app/<file>'
```
After ALL files are copied, restart once:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker restart agent_trader_swarm'
```

### 4. Verify dashboard HTTP 200
Wait 30 seconds, then check:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sleep 30 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/'
```
Expected: `200`. If not 200, fetch the last 30 lines of container logs and report the error:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker logs agent_trader_swarm 2>&1 | tail -30'
```

### 5. Report
Summarize: which files were deployed, HTTP status, success/failure.

## Important
- ALWAYS use base64 encoding if a file contains special characters that might be corrupted by plink.exe on Windows. For standard Python files, regular scp is fine.
- If no $ARGUMENTS are provided, list the files that have been modified in the current session (based on git diff or recent edits) and ask the user which to deploy.
- The verify_dashboard hook will also run after the restart — that's expected and OK.
