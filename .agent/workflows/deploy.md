---
description: Hot-patch a file to the GCP VM and restart the container
---

// turbo-all

## Steps

1. Run syntax check on the modified file:
```
venv\Scripts\python.exe -c "import py_compile; py_compile.compile('<FILE_PATH>'); print('Syntax OK')"
```

2. Upload the file to the VM:
```
gcloud compute scp --zone=europe-west1-b --force-key-file-overwrite <FILE_PATH> agent-trader-swarm-vm:/tmp/<FILENAME>
```

3. Copy into the Docker container and restart:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command="sudo docker cp /tmp/<FILENAME> agent_trader_swarm:/app/<FILE_PATH> && sudo docker restart agent_trader_swarm && echo DONE"
```

4. Wait 30 seconds for the container to start, then verify:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command="sleep 30 && curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://localhost:8080/"
```
