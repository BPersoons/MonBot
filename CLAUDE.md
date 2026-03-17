# Agent Trader

Autonomous crypto trading swarm that runs a continuous pipeline: scout for opportunities, analyze with a council of specialist agents, execute trades on Hyperliquid, and audit performance. Deployed as a Docker container on a GCP VM.

## Architecture

```
main.py (Heartbeat Loop, 60s cycles)
  -> ProjectLead (orchestrator)
       -> ResearchAgent (Scout) — scans market for candidates
       -> TechnicalAnalyst — multi-timeframe TA via ccxt OHLCV
       -> FundamentalAnalyst — on-chain / fundamental scoring
       -> SentimentAnalyst — news & social sentiment via LLM
       -> RiskManager — position sizing, circuit breaker
       -> ExecutionAgent — places orders on Hyperliquid via ccxt
  -> PerformanceAuditor — governance & P/L auditing
  -> ProductOwner (CPO) — periodic system improvement analysis (optional)
  -> SwarmLearner — decision pipeline diagnostics (optional, every 20 cycles)
  -> SwarmMonitor — watchdog thread (every 5 min)
  -> DashboardServer — HTTP on port 8080
```

Weighted scoring: `technical * w_t + fundamental * w_f + sentiment * w_s` with weights in `core/agent_weights.json`. ProjectLead uses Gemini LLM for council debate synthesis.

## Key Directories

```
agents/          — all agent classes (project_lead, execution_agent, research_agent, etc.)
core/            — agent_weights.json, circuit_breaker.py, strategy_logic.py
utils/           — shared utilities (llm_client, exchange_client, db_client, gcp_secrets, etc.)
integrations/    — supabase_client.py + SQL schemas
scripts/         — deploy_update.sh, upload helpers, migration scripts
tests/           — test suite + tests/pre_flight/ (check_imports, check_connections)
templates/       — dashboard_template.html
docs/            — SOP.md
```

## Runtime State Files (root dir, JSON)

| File | Purpose |
|---|---|
| `dashboard.json` | Main dashboard state (cycle count, market data, discovery pipeline) |
| `trade_log.json` | All trades (OPEN/CLOSED), read by ExecutionAgent |
| `active_assets.json` | Currently held tickers |
| `decision_history.json` | Rolling 2000-entry decision log for dashboard history |
| `ticker_state.json` | Tiered scanning cooldowns per setup_id |
| `pipeline_events.json` | State transition audit log |
| `cpo_state.json` | ProductOwner analysis state |
| `pl_status.json` / `pl_meta.json` | Pipeline status metadata |
| `data_cache.json` | Cached market data |
| `learning_report.json` | SwarmLearner diagnostics output (funnel, bottlenecks, missed trades) |
| `core/agent_weights.json` | Analyst weights (tech/fund/sent), tunable |

## Development Commands

```bash
# Run locally
python main.py

# Syntax / import check (pre-flight)
python -m tests.pre_flight.check_imports
python -m tests.pre_flight.check_connections

# Run tests
python -m pytest tests/
python tests/run_tests.py

# Validate imports (standalone)
python validate_imports.py
```

## Deployment

**After testing, changes should always be deployed to production** using the most efficient method:

### Hot-patch (default — skip rebuild, seconds)
```powershell
# 1. Copy file to VM
gcloud compute scp <file> agent-trader-swarm-vm:<file> --zone=europe-west1-b

# 2. Inject into container and restart
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker cp <file> agent_trader_swarm:/app/<path> && sudo docker restart agent_trader_swarm'

# 3. MANDATORY: verify the container started and the dashboard is up
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sleep 30 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/'
# Expected output: 200
# If output is 000 → dashboard not yet up, wait another 15s and retry
# If output is 500 → Python error in do_GET; check: sudo docker logs agent_trader_swarm 2>&1 | tail -30
# If no output / timeout → server stuck (request backlog or crash); restart and check logs
```

Use hot-patch for Python file changes (agents, utils, main.py). **Always run step 3** — logs alone do not prove the dashboard is serving correctly. The dashboard server starts ~25s after container restart; runtime errors in the request handler only appear when the first HTTP request is made, not at startup.

### Full deploy (only when Dockerfile/requirements.txt change)
```powershell
.\deploy.ps1   # or ./deploy.sh
```
Pre-flight checks -> `gcloud builds submit` -> SCP config to VM -> `deploy_update.sh` (pull image, recreate container).

## GCP Details

| Key | Value |
|---|---|
| Project ID | `gen-lang-client-0441524375` |
| Region | `europe-west1` |
| Zone | `europe-west1-b` |
| VM Name | `agent-trader-swarm-vm` |
| Machine Type | `e2-medium` (2 vCPU, 4 GB) |
| Image URI | `europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest` |
| Container Name | `agent_trader_swarm` |
| Ports | `8080` (dashboard), `8501` (Streamlit, exposed but optional) |

## Required Secrets

Loaded via GCP Secret Manager on VM, or `.env.adk` locally:

| Secret | Used By |
|---|---|
| `GOOGLE_API_KEY` | LLMClient (Gemini) — **critical** |
| `HL_WALLET_ADDRESS` | HyperliquidExchange — **API/agent wallet address** (the key that signs orders) |
| `HL_PRIVATE_KEY` | HyperliquidExchange — private key of the API wallet — **critical** |
| `HL_VAULT_ADDRESS` | HyperliquidExchange — **main/vault wallet** that authorized the API wallet (used as `walletAddress` in CCXT). If absent, falls back to `HL_WALLET_ADDRESS` |
| `SUPABASE_URL` | DatabaseClient, dashboard sync |
| `SUPABASE_KEY` | DatabaseClient, dashboard sync |
| `TELEGRAM_CHAT_ID` | Alert notifications |

Optional env: `GEMINI_MODEL` (default: `gemini-2.5-flash`), `GCP_PROJECT_ID`, `GCP_REGION`.

## Conventions

- **Imports**: stdlib -> third-party -> local (`from agents.X`, `from utils.X`). Lazy imports inside `try/except` for optional deps.
- **Error handling**: Agents catch exceptions individually; main loop never crashes (fail-open). Optional agents (CPO, SwarmLearner) are `None`-guarded.
- **Critical dependency failures**: When a critical external dependency is missing (unfunded wallet, bad secret, unreachable exchange), the code should **fail loudly once** (clear warning log + Telegram alert), disable only the affected subsystem, and stop retrying. Do not paper over it with silent skips or infinite retries. The fix is always operational (fund the wallet, rotate the secret, etc.) — a restart re-enables the subsystem once the real fix is in place.
- **Logging**: `logging.getLogger("AgentName")` per class. Heartbeat log -> `heartbeat.log`.
- **State files**: Always wrap JSON read/write in try/except. Use `sanitize()` for NaN/Inf before serialization.
- **Health reporting**: Agents report status via `SwarmHealthManager.report_health()` -> Supabase `swarm_health` table.
- **Tiered scanning**: `TickerStateTracker` manages cooldowns — check `should_analyze()` before processing a ticker.
- **Windows compat**: `sys.stdout.reconfigure(encoding='utf-8')` at top of main.py for console output.

## Common Pitfalls

- **NaN in JSON**: Always `sanitize()` floats before `json.dump()`. Math operations on missing data produce NaN.
- **USDT/USDC duplication**: Pipeline deduplicates — skips USDT variant if USDC exists in the same cycle.
- **Secret loading order**: GCP Secret Manager -> `os.getenv()` -> `dotenv(".env.adk")`. If secrets fail, check service account IAM role (`Secret Manager Secret Accessor`).
- **Docker auth on VM**: Must run `sudo gcloud auth configure-docker europe-west1-docker.pkg.dev` before pull.
- **Pre-flight gates deployment**: `check_imports` and `check_connections` must pass or deploy aborts.
- **Hyperliquid wallet "does not exist"**: `{"status":"err","response":"User or API Wallet ... does not exist."}` means `HL_WALLET_ADDRESS` is configured but not yet funded on Hyperliquid. **Fix**: deposit USDC to the wallet address on Hyperliquid (mainnet) or use the testnet faucet. Then restart the container — `signing_client` re-initializes on startup. The code logs this warning once and suspends trading; it will not spam errors while the wallet is unfunded.
