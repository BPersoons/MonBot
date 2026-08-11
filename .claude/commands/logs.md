# Container Logs

Fetch recent logs from the production container.

## Arguments
$ARGUMENTS — optional: number of lines (default: 50), or a grep filter keyword.

Parse $ARGUMENTS:
- If it's a number (e.g. `100`): use as tail count
- If it's a word (e.g. `risk`, `error`, `veto`): use as grep filter with default 50 lines
- If it's `number keyword` (e.g. `100 risk`): use both
- If empty: default to last 50 lines

## Execution

### Tail only (no grep):
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker logs agent_trader_swarm 2>&1 | tail -<N>'
```

### With grep filter:
```
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker logs agent_trader_swarm 2>&1 | tail -<N> | grep -i "<keyword>"'
```

## Output

Show the raw log output. If the output is very long (>100 lines), summarize key events (errors, trades, vetos, restarts) and show the full output in a code block.

Highlight any:
- `ERROR` or `CRITICAL` lines
- `Risk Manager Veto` entries
- `Position Closed` / `Order Sent` entries
- `CIRCUIT BREAKER` mentions
