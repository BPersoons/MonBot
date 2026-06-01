# Agent Trader

Autonomous crypto trading swarm that runs a continuous pipeline: scout for opportunities, analyze with a council of specialist agents, execute trades on Hyperliquid, and audit performance. Deployed as a Docker container on a GCP VM.

## Architecture

```
main.py (Heartbeat Loop, 60s cycles)
  -> ProjectLead (orchestrator)
       -> ResearchAgent (Scout) — scans market for candidates
       -> TechnicalAnalyst — multi-timeframe TA via ccxt OHLCV
       -> XyzTechnicalAnalyst — TA for XYZ synthetic tokens (stocks/commodities)
       -> FundamentalAnalyst — on-chain / fundamental scoring
       -> SentimentAnalyst — news & social sentiment via LLM
       -> PolymarketAnalyst — prediction-market shadow signals (inline, per ticker)
       -> RiskManager — position sizing, circuit breaker
       -> ExecutionAgent — places orders on Hyperliquid via ccxt
            -> StrategyManager — trailing SL/TP position lifecycle
  -> PerformanceAuditor — governance & P/L auditing
  -> TreasuryAgent — autonomous capital allocator (full run every 60 cycles + startup, fast run every 5)
  -> ProductOwner (CPO) — periodic system improvement analysis (optional)
  -> SwarmLearner — decision pipeline diagnostics (optional, every 20 cycles)
  -> SwarmMonitor — watchdog thread (every 5 min, 17 checks)
  -> DashboardServer — HTTP on port 8080
```

Weighted scoring: `technical * w_t + fundamental * w_f + sentiment * w_s` with weights in `core/agent_weights.json`. ProjectLead uses Gemini LLM for council debate synthesis.

## Key Directories

```
agents/          — all agent classes (project_lead, execution_agent, research_agent, etc.)
core/            — agent_weights.json, circuit_breaker.py, strategy_logic.py
config/          — auto_params.json (auto-tunable runtime params, volume-mounted)
utils/           — shared utilities (llm_client, exchange_client, db_client, gcp_secrets, treasury_executor, treasury_risk, treasury_yield_oracle, treasury_allocation, etc.)
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
| `config/auto_params.json` | Auto-tunable numeric params (score_threshold, tech_prefilter_min, scan_universe_size, etc.) — **volume-mounted**, written by PerformanceAuditor |
| `cost_log.json` | Daily cost/ROI snapshot (LLM cost, infra, fees, trading P&L) — written by CostTracker |
| `portfolio_peak.json` | Peak equity tracker for drawdown calculation — written by RiskManager |
| `supabase_health.json` | Supabase connectivity health check result — written by SwarmMonitor |
| `treasury_state.json` | TreasuryAgent snapshot: hl_snapshot, aave_balance, yield_balances, treasury_wallet_usdc, total_portfolio, allocation, opportunities, funding_harvest, timestamp — refreshed every 60 cycles and on startup (cycle 1) |
| `treasury_harvest.json` | Funding Harvest state: `{"status": "IDLE"}` or `{"status": "ACTIVE", "asset", "size", "trade_id", "entry_price", "opened_at", "max_close_at", "rate_at_open", "last_rate", "last_check"}` — separate from treasury_state.json (rewritten each cycle) |
| `treasury_proposals.json` | All treasury proposals (PENDING / in-flight / DEPLOYED / FAILED / REJECTED) — state machine driven by TreasuryExecutor |
| `config/treasury_allocation.json` | Portfolio allocation targets (target_trade_pct=30%, performance-adaptive ±10pp) — volume-mounted, editable without rebuild |
| `config/treasury_protocols.json` | Yield protocol registry: Aave v3 Arbitrum (automated), Morpho BBQUSDC/GTUSDCC (vault_address TBD), Compound v3 (not yet automated) |
| `market_regime.json` | Last detected BTC market regime — written by ResearchAgent every scan cycle, read by TreasuryAgent (`_compute_target_allocation`) and ProjectLead (SA/FA gates). Format: `{"regime": "RANGING", "adx": 13.1, "direction": "BEARISH", "atr_rank": 0.30}` |
| `polymarket_shadow_log.json` | PolymarketAnalyst shadow signal log — Phase 1 paper trades vs actual outcomes for calibration. No scoring impact yet. |
| `pnl_snapshots.json` | Rolling P&L snapshots for drawdown tracking — **volume-mounted**, written by main.py |
| `stocks_watchlist.json` | XYZ stocks watchlist state — managed by `stocks/agents/stocks_project_lead.py` |
| `stocks_pending_approval.json` | XYZ stocks trades pending Telegram approval — Telegram approval flow |
| `stocks_active_positions.json` | Currently open XYZ stock positions |
| `stocks_trade_log.json` | XYZ stocks trade history (separate from main trade_log.json) |
| `stocks_decision_history.json` | Rolling decision log for XYZ stocks pipeline |
| `config/stocks_auto_params.json` | Auto-tunable params for stocks pipeline |

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
# 0. Before SCP: validate API contracts locally
python -m tests.pre_flight.check_pipeline
# If this fails, hot-patch the callee (e.g. technical_analyst.py) too before proceeding

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
| `TELEGRAM_BOT_TOKEN` | Stocks Telegram approval flow; swarm alert notifications |
| `HL_VAULT_PRIVATE_KEY` | TreasuryExecutor — private key of the treasury wallet (`0x4144e0b5…`) for signing Arbitrum transactions (Aave deposits, ERC-4626 vaults). Falls back to `HL_PRIVATE_KEY` if absent. |

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

## Trading Strategy (ijkpunt 2026-05-29)

### Strategie-overzicht
Regime-aware, asset-klasse-specifieke signaalfuncties. Gebaseerd op backtestonderzoek over 60 dagen, 18 HL-tickers. Resultaat: gemiddeld **+44%** vs **-9%** voor de oude RSI+EMA baseline.

### Signaalfuncties per asset-klasse (`core/strategy_logic.py`)

**Crypto — `get_crypto_signal(df, i)`**
- LONG: MACD zero-cross omhoog + ADX>20 + +DI>-DI + boven EMA200; OF stoch-RSI < 0.20 dip-buy boven EMA50
- SHORT: BB upper rejection (prev candle raakte upper, sluit < midlijn, MACD draait); OF trend-cont short onder EMA200 + MACD-hist flip negatief

**Tech Stocks — `get_tech_signal(df, i)`**
- LONG: Supertrend flip bullish + ADX>18; OF MACD-hist flip positief boven EMA200
- SHORT: ALLEEN onder EMA200 + bearish divergentie (hogere prijs, lagere RSI over 10 bars)
- Geen shorts in bull-regime — tech shorts zijn structureel slecht in uptrend markten

**Commodities — `get_commodity_signal(df, i)`**
- LONG: volledige EMA ribbon (prijs>ema8>ema20>ema50) + RSI 52-72 + ADX>15
- SHORT: Supertrend flip bearish + ADX>18; OF MACD zero-cross omlaag onder EMA200 + ADX>20

**Routing**: `detect_asset_class(ticker)` → `get_signal_for_asset(asset_class, df, i)` in `strategy_logic.py`.

### EMA200 regime gate (`agents/technical_analyst.py`)
Toegepast in `analyze_signal()`, TRENDING regime only:
- Score ×1.10 wanneer richting aligned met EMA200 (bull boven, bear onder)
- Score ×0.85 wanneer richting tegen EMA200 ingaat
- Doel: versterk signalen in trend, dempt counter-trend signalen licht
- Niet van toepassing in RANGING regime (mean-reversion werkt anders)

### Commodity indicator weights (`COMMODITY_WEIGHTS`)
EMA (0.28) en ADX (0.22) zwaarder dan standaard. Commodity trends zijn EMA-ribbon gedreven; ADX bepaalt of er voldoende trend is voor een entry.

### Asset-class routing in pipeline
- `ProjectLead` bepaalt `_asset_class` per ticker vóór TA-call
- Commodity tickers: `XYZ-CL`, `XYZ-BRENTOIL`, `XYZ-GOLD`, `XYZ-SILVER`, `XYZ-NATGAS`, `XYZ-COPPER`, `XYZ-PLATINUM`, `XYZ-PALLADIUM`
- `TechnicalAnalyst` (crypto) en `StockTechnicalAnalyst` (XYZ) ontvangen beide `asset_class` parameter

### Actuele drempelwaarden (na strategie-upgrade)
| Parameter | Waarde | Reden |
|---|---|---|
| `score_threshold` | 0.20 | Verlaagd van 0.25 — kwaliteitsfiltering nu op TA-niveau via EMA200+ADX |
| `tech_prefilter_min` | 0.10 | Hersteld na noodstop mei 2026 |
| EMA200 gate aligned | ×1.10 | Bescheiden boost om stapeling met ADX-damping te vermijden |
| EMA200 gate against | ×0.85 | Lichte straf, niet ×0.75 (zou double-dampen met ADX<20) |

### Backtestresultaten ijkpunt (60 dagen, 18 tickers, 2026-03 t/m 2026-05)
| Asset-klasse | Finale strategie | Oude agent | Verbetering |
|---|---|---|---|
| Crypto | +13.7% gem. | -14.9% | +28.6pp |
| Tech Stocks | +119.9% gem. | +2.3% | +117.6pp |
| Commodities | -8.2% gem. | -14.3% | +6.1pp |
| **Totaal** | **+44.2%** | **-9.1%** | **+53pp** |

### Backtest-scripts (ter referentie)
- `scripts/strategy_research.py` — 7 strategieën, 8 crypto-tickers, 60d
- `scripts/strategy_windows.py` — 60d/30d/7d vergelijking
- `scripts/strategy_windows_xyz.py` — XYZ stocks + commodities
- `scripts/strategy_final.py` — finale hybride strategie, alle asset-klassen
- `scripts/strategy_long_short_split.py` — long vs short analyse per klasse

### Strategie-pitfalls
- **Dubbele damping**: ADX-damping (×0.7 bij ADX<20) EN EMA200-gate (×0.85 tegen trend) stapelen zich. Bij choppy + counter-trend kan een score van 0.50 → 0.50×0.70×0.85 = 0.30. Houd `score_threshold` ≤ 0.20.
- **Tech shorts werken niet in bull-regime**: Alle 7 short-strategieën op MU/SNDK/AMD hadden 0% WR op 30d. Nooit activeren boven EMA200.
- **Commodities longs zijn zwak**: EMA-ribbon + RSI-zone is selectief. Commodities zijn primair voor shorts (Supertrend flip). Verwacht weinig commodity longs.
- **XYZ markturen**: `StockTechnicalAnalyst` filtert al op 14:30-21:00 UTC. Buiten die uren geen XYZ-analyses.
- **`get_agent_signal()` is verouderd**: De oude methode in `strategy_logic.py` staat er nog voor backward compat maar wordt niet meer gebruikt in de pipeline of backtester.

## Common Pitfalls

- **NaN in JSON**: Always `sanitize()` floats before `json.dump()`. Math operations on missing data produce NaN.
- **USDT/USDC duplication**: Pipeline deduplicates — skips USDT variant if USDC exists in the same cycle.
- **Secret loading order**: GCP Secret Manager -> `os.getenv()` -> `dotenv(".env.adk")`. If secrets fail, check service account IAM role (`Secret Manager Secret Accessor`).
- **Docker auth on VM**: Must run `sudo gcloud auth configure-docker europe-west1-docker.pkg.dev` before pull.
- **Pre-flight gates deployment**: `check_imports` and `check_connections` must pass or deploy aborts.
- **Hyperliquid wallet "does not exist"**: `{"status":"err","response":"User or API Wallet ... does not exist."}` means `HL_WALLET_ADDRESS` is configured but not yet funded on Hyperliquid. **Fix**: deposit USDC to the wallet address on Hyperliquid (mainnet) or use the testnet faucet. Then restart the container — `signing_client` re-initializes on startup. The code logs this warning once and suspends trading; it will not spam errors while the wallet is unfunded.
- **Unified mode balance double-count**: In HL Unified Account mode, spot USDC doesn't decrease when pledged to perps. `get_balance()` uses `spot_usdc + marginSummary.accountValue` (where accountValue = totalRawUsd + unrealizedPnL; totalRawUsd is negative = borrowed from spot, which cancels the overlap). **NEVER** sum CCXT's `balance['USDC']['total']` + spot — that double-counts the pledged portion. Bug discovered April 2026: fake peak of $724 from real $565 equity.
- **Partial TP min notional**: HL rejects orders < $10. When `close_qty * price < $10` during partial take-profit, `execution_agent` moves SL to breakeven instead (entry + 0.1% fee buffer). Logged in `trade['skipped_partials']`, **not** in `partial_exits` (to avoid PnL pollution). The SL-ladder (`sl_stage`) advances to 1 so trailing continues normally.
- **History import ghosts**: Recovery/import scripts (e.g. `import_hl_history.py`) can create records with `null` pnl or `pnl=0.0` if source fills lack required fields. These silently inflate trade count, corrupt win-rate stats, and block PerformanceAuditor weight updates every cycle. Always validate imported records have non-null `pnl` before writing to `trade_log.json`. Cleanup: remove records where `id.startswith("RECOVERED_")`. **Trade log field name is `quantity` (not `size` or `qty`)** — any script reading `t.get("size")` silently returns None.
- **PerformanceAuditor self-tightening loop**: After a losing streak, the auditor raises `tech_prefilter_min` and `score_threshold` in `auto_params.json`. If tightened too aggressively, signal volume drops to near-zero, starving the auditor of feedback — a paralysis loop. Check `auto_params._meta` when diagnosing zero trading activity. Manual fix: lower `tech_prefilter_min` back to 0.10 while keeping `score_threshold` at 0.25.
- **`drawdown_offboard_pct` is per-ticker, not portfolio**: This param (default 5.0) governs per-asset offboarding in `PerformanceAuditor.check_asset_performance()` — it does NOT block new trades at the portfolio level. The global trade gate is `CircuitBreaker.can_trade()`.
- **MONITOR deadlock**: When a ticker's score sits persistently in the MONITOR zone (0.28–0.38 for crypto, 0.15–0.25 for XYZ), the LLM keeps returning MONITOR and the ticker never executes — it can loop for 1000+ cycles. Detection: `consecutive_monitor_count` field in `ticker_state.json`. Fix in `main.py`: after 50 consecutive MONITOR cycles with score ≥ 0.20, `next_step` is automatically promoted to BUILD_CASE with a WARNING log. SwarmMonitor Check 15 alerts when this threshold is reached. Also affects XYZ stocks — fixed separately by lowering BUILD_CASE threshold to 0.25 (vs 0.38 for crypto).
- **`agent_weights.json` must be applied as signal multipliers**: `ProjectLead.load_weights()` loads the file into `self.weights`, but the weights must be explicitly multiplied into each analyst signal before the composite score. Pattern: `tech_signal = tech_view['signal'] * aw.get('technical', 1.0)`. If you refactor scoring, verify `self.weights` is still applied — it's a silent disconnect (auditor writes, scoring ignores) that has no error output. Fixed 2026-05-23. Also: call `self.load_weights()` at the start of each scoring cycle so auditor updates take effect without restart.
- **SHORT TA sign convention**: In `technical_analyst.py`, all SHORT indicators must use the same convention — positive = confirms SHORT, negative = hurts SHORT. MACD/EMA/ADX/Stoch/Volume invert internally. RSI and BB do NOT — they return negative for bearish. `ProjectLead` then negates the composite (`base_score = -ta_only_score`), which flips the sign back. If you add a new indicator for SHORT, decide: invert internally (like MACD) or keep natural sign (like RSI). Mixing breaks the signal strength and causes SHORT composite to be near-zero even in strong bear markets. Fixed 2026-05-23.
- **`cost_log.json` is a rolling 30-day history**: Since 2026-05-23, the file has structure `{"history": {"2026-05-23": {...}, ...}}`. Code that reads it must access `.get("history", {})`. The old flat-snapshot format is gone. Use `CostTracker().get_history()` to read programmatically.

## Treasury System

### Vision: Autonomous Wealth Manager
The treasury's goal is to act as a fully autonomous, emotionless capital allocator — dynamically distributing USDC across yield instruments based on risk/reward, market regime, and liquidity needs. It should rebalance without prompting when better opportunities arise, and report transparently on every allocation decision.

### Capital Locations
- **Hyperliquid (HL)** — perps trading margin. Target: 30% of total portfolio (performance-adaptive: WR ≥ 45% → +10pp, WR < 30% → -10pp).
- **Yield protocols** — deployed on Arbitrum, target ~70%. Allocated across protocols by `_pick_best_protocol()`.
- **Treasury wallet** (`0x4144e0b5…`) — staging area; USDC deposited here triggers an automatic DEPLOY_YIELD proposal.

### Tranche Model (target architecture)
| Tranche | Target | Instruments | Liquidity |
|---|---|---|---|
| Liquidity reserve | ~15% | Aave v3 | Instant |
| Yield core | ~65% | Morpho, GMX GM | 1–3 days |
| Opportunistic | ~20% | HL Funding Harvest, Pendle PT | Position-dependent |

### Planned Protocol Executors (Roadmap)
```
TreasuryAgent (orchestrator)
  ├── YieldOracle         — on-chain Aave APY via Pool.getReserveData (live)
  ├── RiskModel           — per-protocol risk score (SC / liquidity / counterparty) (live)
  ├── AllocationOptimizer — Gemini LLM tranche split (live, fallback to rule-based)
  └── Protocol executors:
       ├── AaveExecutor        — live (pool 0x794a61358D…)
       ├── MorphoExecutor      — live (BBQUSDC 0x7e97… + GTUSDCC 0x7c57…)
       ├── GainsExecutor       — live (gUSDC 0xd3443ee…, ERC-4626)
       ├── FundingHarvestor    — live (BTC/ETH HL short, treasury_harvest.json)
       └── PendleExecutor      — Fase 3 (custom AMM, not ERC-4626)
```

### Phase Roadmap
- **Fase 1** *(voltooid 2026-05-24)*: ~~Morpho vault-adres activeren~~ ✓ · ~~Autonomous yield-switch (YIELD_SWITCH)~~ ✓ · ~~Gains Network gUSDC vault (ERC-4626, ~6.7% APY)~~ ✓ · ~~HL Funding Harvest executor~~ ✓
- **Fase 2** *(voltooid 2026-05-24)*: ~~RiskModel~~ ✓ · ~~YieldOracle (on-chain Aave APY)~~ ✓ · ~~LLM AllocationOptimizer (multi-tranche Gemini split)~~ ✓
- **Fase 3** *(next)*: Pendle PT executor (custom AMM) · Volledig geautomatiseerde multi-protocol rebalancing

### Proposal State Machine
```
PENDING → APPROVED → WITHDRAWING → BRIDGED → DEPLOYED
                   → NEEDS_MANUAL_WITHDRAWAL
                   → MONITORING (FUND_TRADING only) → COMPLETED
REBALANCE: APPROVED → REBALANCING → BRIDGE_BACK_NEEDED → (manual HL deposit)
YIELD_SWITCH: APPROVED (auto) → SWITCHING → DEPLOYED
MANUAL_ACTION_REQUIRED: terminal/informational — no executor acts on it
```
- **`MANUAL_ACTION_REQUIRED`** is an inert informational status (no active set in `execute_approved_proposals()` or `run_fast()` lists it). Emitted by `_check_yield_diversification()` when the overweight protocol is epoch-based (`immediate_withdraw=false`, e.g. Gains gUSDC) and so can't be auto-moved: instead of silently returning, it raises a Telegram alert and appends a `MANUAL_ACTION_REQUIRED` proposal (`id` prefix `TRDM_`, `diversification=True`). The proposal doubles as the diversification cooldown record so the alert fires at most once per `_DIVERSIFY_COOLDOWN_H` window. Resolve by manually withdrawing from the epoch-based protocol.
- `run()` every 60 cycles (hourly): full DeFiLlama fetch, generate proposals, advance state.
- `run_fast()` every 5 cycles (~5 min): execution-only pass using cached yield data.
- **YIELD_SWITCH** is fully automatic (no human approval). Triggered by `_check_yield_switch()` when best automated Arbitrum APY exceeds currently deployed protocol by ≥ `_YIELD_SWITCH_MIN_SPREAD` (1.5%) and balance ≥ `_YIELD_SWITCH_MIN_USD` ($100). One switch at a time. APPROVED step withdraws from source; SWITCHING step polls for USDC arrival, then deposits into destination.
- **YIELD diversification** is also fully automatic. Triggered by `_check_yield_diversification()` when a single protocol holds > `_MAX_SINGLE_CONCENTRATION` (80%) of total yield and total yield > `_DIVERSIFY_MIN_TOTAL_USD` ($150). Moves enough capital to bring the source protocol down to `_DIVERSIFY_TARGET_PCT` (65%). Uses `switch_amount_usd` for a **partial** ERC-4626 withdrawal (`withdraw(assets)` selector `0xb460af94`) — only the specified amount is moved, not the full balance. Cooldown: `_DIVERSIFY_COOLDOWN_H` (12h). Identified by `"diversification": True` in the proposal. Shares the same YIELD_SWITCH in-flight guard — no diversification while an APY-driven switch is running. If the overweight protocol is epoch-based (`immediate_withdraw=false`), it cannot be auto-moved → emits a `MANUAL_ACTION_REQUIRED` alert instead (see state machine above).

### Protocol routing
Proposals carry a `protocol_type` field (`aave_v3` / `erc4626` / `compound_v3`). The executor routes to the correct on-chain function in the BRIDGED step. **Do not rely on the `protocol` label** — it can mismatch if the proposal was created before the routing bug was fixed (e.g. TRP_20260521_0736 says "Curve" but deployed to Aave because the executor always called `_deposit_aave()` regardless of protocol_type before this was fixed).

### Pre-flight tests
`tests/pre_flight/check_treasury.py` — 15 checks (124 assertions), wired into `check_pipeline.py`. Must pass before deploy. Validates: imports, signatures, proposal logic, protocol routing, JSON config, drawdown fix, main.py wiring, yield-switch trigger/routing, SWITCHING→DEPLOYED routing (incl. partial `switch_amount_usd`), Funding Harvest methods/guards/wiring, RiskModel profiles/weights, YieldOracle ABI decode/enrichment/order, AllocationOptimizer parse/validate/fallback/multi-proposal, yield-diversification trigger/cooldown/partial-amount.

### Common Treasury Pitfalls

- **False drawdown halt**: Capital moved to any yield protocol disappears from `get_balance()`. `RiskManager.check_portfolio_drawdown()` calls `get_total_yield_balance(_TREASURY_WALLET)` (not just `get_aave_balance`) to sum all automated protocols. If you refactor this, capital in Morpho/Compound will look like a drawdown and block all trading.
- **Curve was never a good choice**: Curve's best Arbitrum pool is ~3.86% APY with $1.8M TVL. Ethereum Curve pools are at 0% and require a separate bridge. `_pick_best_protocol()` is now hardcoded to never recommend non-Arbitrum non-automated protocols. Do not revert this.
- **PENDING proposals expire**: TTL is 6 hours (`_PROPOSAL_TTL_H = 6`). Stale PENDING proposals are replaced each cycle. APPROVED/DEPLOYED/FAILED proposals are kept forever in history.
- **`source_treasury` proposals skip bridge**: If `source='treasury_wallet'`, the executor goes directly to BRIDGED (no HL withdrawal step). This is by design — USDC is already on Arbitrum.
- **Morpho vault addresses**: Both Morpho vaults are now `automated=true` in `config/treasury_protocols.json`: BBQUSDC (`0x7e97…`) and GTUSDCC (`0x7c57…`). Do not set `vault_address=null` — that causes FAILED proposals.
- **TVL thresholds are tier-based**: `_MIN_TVL_BY_TIER = {stable: $5M, medium: $10M, exposure: $50M}`. All protocols in `_TRACKED` derive their threshold from their `risk_tier`. Do not add per-entry thresholds — the tier drives the filter uniformly. GTUSDCC has $3.2M DeFiLlama TVL (< stable $5M threshold) so it may not appear in opportunities even though it's `automated=true` in config.
- **YIELD_SWITCH SWITCHING status**: Must be in BOTH the `active` set in `execute_approved_proposals()` AND the local `active` set at the top of `run_fast()`. Forgetting either silently stalls all switches mid-flight.
- **ERC-4626 selector**: `0x6e553f65` = `deposit(uint256 assets, address receiver)`. Requires approve + deposit. Compound v3 uses `0xf2b9fdb8` = `supply(address asset, uint amount)`.
- **FUND_TRADING proposals**: These are informational top-up reminders (bridge treasury → HL). They auto-complete when HL balance rises by ≥ 90% of the proposal amount. They don't execute automatically — the user bridges manually via HL web app.
- **RPC for Arbitrum**: `https://arbitrum.gateway.tenderly.co` is the primary working public RPC from GCP (eth_call, eth_sendRawTransaction, eth_getCode, eth_getBalance all work). drpc.org, meowrpc.com, arb1.arbitrum.io return HTTP 403 from GCP datacenter IPs. ankr requires API key. 1rpc.io has usage limits. zan.top works for most methods but rate-limits eth_call (429) and eth_sendRawTransaction (429) after a few calls. Tenderly is in `_ARB_RPCS` first in both `treasury_executor.py` and `treasury_yield_oracle.py`. Added retry-with-backoff for 429 in `_rpc()` (2s, 4s) and a 3s sleep between approve + supply in `_deposit_aave()` to stay under Tenderly rate limits.
- **HL bridge deposit function**: Bridge2 contract (`0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7`) uses `batchedDepositWithPermit((address,uint64,uint64,(uint256,uint256,uint8))[])` — selector `0xb30b5bce`. No separate approve TX needed (EIP-2612 permit). The inner Signature tuple field order is `(uint256 r, uint256 s, uint8 v)` — NOT `(uint8 v, bytes32 r, bytes32 s)`. Do NOT use guessed selectors like `sendDeposit(uint64)` = `0x28edb7a5` — it doesn't exist in the deployed contract.
- **EIP-2612 permit for USDC on Arbitrum**: `name = "USD Coin"`, `version = "2"`, `chainId = 42161`, `verifyingContract = 0xaf88d065...`. nonces(address) selector = `0x7ecebe00`. Sign with `Account.sign_typed_data(private_key, full_message={...})` — first arg positional, `full_message` as keyword. The returned `r` and `s` are `int`, not `bytes` — use `_u256(signed.r)` for ABI encoding.
- **Bridge step 1 is skippable**: `_bridge_usdc_to_hl()` checks if treasury already has USDC before transferring. If USDC is already on vault Arb (from a failed prior bridge attempt), step 1 is skipped and the full vault Arb balance is bridged — this auto-recovers stuck funds without manual intervention.
- **`run_fast()` local active set**: `run_fast()` has its OWN local `active` set that gates whether `execute_approved_proposals()` is called. If you add a new proposal status, update BOTH the `active` set in `execute_approved_proposals()` AND the one at the top of `run_fast()` — otherwise proposals in the new state are silently ignored every cycle.
- **cycle_count resets on restart**: `treasury_agent.run()` fires at `cycle_count % 60 == 0 or cycle_count == 1`. Since 2026-05-28, `cycle_count == 1` is included so the full treasury run always fires on startup/after deploy. Prior to this fix, frequent deploys could prevent `run()` from ever firing (cycle 1 is not divisible by 60).
- **`_check_yield_switch()` notification fires before proposal is saved**: Prior to 2026-05-27, `_send_telegram()` was called inside `_check_yield_switch()` before `_save_proposals()` in `run_fast()`. A container restart between those two calls produced a phantom notification with no persisted proposal. Fixed: function now returns `(proposals, notif_texts)` tuple; callers send notifications after `_save_proposals()`. Also: pre-flight test Case A previously instantiated a real `TreasuryAgent()` and triggered a live Telegram notification every CI/pre-flight run — test now unpacks the tuple and checks `notifs_a` without sending.
- **Spurious YIELD_SWITCH on missing APY**: `_check_yield_switch()` looks up `current_apy = apy_by_id.get(pid, 0.0)`. If the deployed protocol (e.g. aave-v3-arbitrum-usdc) is absent from the cached opportunities list (DeFiLlama fetch failure or key mismatch), current_apy defaults to 0.0 — triggering a switch even if the protocol has competitive APY. Fix: skip the switch when `pid not in apy_by_id` (treat unknown APY as "don't move" rather than "move"). Also: allowance check and post-deposit balance check in `_deposit_aave/_deposit_erc4626` now return `None` (not 0) on eth_call failure so they don't abort the deposit when reads are blocked.
- **Morpho BBQUSDC vault (0x7e97…) deposit cap**: Large deposits ($1,670) revert on-chain with unknown reason while small deposits ($432) succeed. Possibly a per-depositor cap or vault supply cap. Route large amounts to Aave v3 instead. Morpho is still listed as automated but may require investigation before large allocations.
- **SWITCHING `needed` uses `switch_amount_usd`, not `amount_usd`**: For partial diversification switches, `amount_usd` holds the full source balance (e.g. $2102) while only `switch_amount_usd` (e.g. $735) was actually withdrawn. If the SWITCHING handler used `amount_usd * _BRIDGE_TOL` as the threshold, it would wait forever since only $735 ever arrives. The handler now reads `switch_amt = float(proposal.get("switch_amount_usd") or proposal.get("amount_usd", 0))`. The deposit is also capped at `switch_amt * 1.05` to avoid sweeping unrelated wallet USDC. If you add new proposal types that do partial withdrawals, always set `switch_amount_usd` and verify the SWITCHING handler uses it.

### Updating CLAUDE.md
When making changes to the treasury system (new protocol, new state, new config key, new pitfall), **update this section** before deploying. Treasury architecture evolves and future sessions need this context.

### Treasury Pitfalls (added 2026-05-23, updated 2026-05-24)
- **GMX GM pool**: single-sided USDC counterparty risk — if GMX traders have a large winning streak, GM holders absorb losses. Statistically favourable long-term but expect short drawdown periods.
- **Gains Network gUSDC**: same counterparty risk profile as GMX GM — vault absorbs losses when Gains perp traders are net profitable. ERC-4626 verified. TVL ~$5.9M on-chain; DeFiLlama may show lower.
- **Funding Harvest**: only beneficial when funding rate > break-even threshold (`_HARVEST_MIN_RATE_8H = 0.01%/8h` ≈ 10.95% APR). In bear markets funding is often near zero or negative — `_check_funding_harvest()` guards this. Only BTC and ETH (`_HARVEST_ALLOWED_ASSETS`) — do not add illiquid assets. Position monitored every 5 cycles via `run_fast()`. State persisted in `treasury_harvest.json` (survives restarts). Max notional `_HARVEST_MAX_NOTIONAL = $150`. Auto-closes after `_HARVEST_MAX_HOLD_H = 48h` or when rate drops below `_HARVEST_CLOSE_RATE_8H = 0.003%/8h`.
- **Harvest guard in execution_agent + strategy_manager**: trades with `"harvest": True` in trade_log must be skipped in the backfill pass (TP/SL assignment), Pass 3 (EXTERNAL_CLOSURE sync), and `evaluate_position()`. Removing these guards causes the swarm to close harvest positions or corrupt their TP/SL. Pre-flight check 11 verifies all three guards are present.
- **Pendle PT**: not ERC-4626 — uses custom AMM router. Requires approve + `swapExactTokenForPt()` call, not the standard deposit selector. PT tokens must be held to maturity to redeem at par; selling early on AMM may incur slippage loss.

### Fase 2 Components (added 2026-05-24)

**`utils/treasury_risk.py` — RiskModel**
- Scores each protocol on 5 dimensions: `sc` (audit quality), `liquidity` (exit speed), `counterparty` (trading vault risk), `maturity` (track record), `tvl` (log-scaled, dynamic).
- Weights: sc=0.25, liquidity=0.25, counterparty=0.30, maturity=0.10, tvl=0.10 (must sum to 1.0).
- `enrich_opportunities(opps)` adds `risk_score` dict + `risk_adjusted_apy` float, re-sorts by risk-adjusted APY.
- `_pick_best_protocol()` now ranks by `risk_adjusted_apy` (not raw APY) — Gains Network's 6.7% is discounted ~41% for counterparty risk.
- **Pitfall**: risk profiles are static metadata in `_PROFILES`. If you add a new protocol without adding a profile, it gets `_UNKNOWN_PROFILE` (conservative 0.50 across the board) and will rank below well-profiled protocols.

**`utils/treasury_yield_oracle.py` — YieldOracle**
- Queries `Aave v3 Pool.getReserveData(USDC)` on-chain for exact supply APY. Selector `0x35ea6a75`. `currentLiquidityRate` (uint128 in Ray) is at ABI slot 2 (bytes 64–95 of the return data).
- APY formula: `((1 + rate_ray/RAY/SPY)^SPY - 1) * 100`. RAY=1e27, SPY=31536000.
- Sanity filter: APY must be in [0%, 50%]; implausible values fall back to DeFiLlama.
- **Integration order**: YieldOracle must run BEFORE RiskModel enrichment (risk model uses the `apy` field; on-chain correction must happen first). Pre-flight check 13 verifies the order.
- **Pitfall**: `getReserveData` returns a struct where each field is ABI-padded to 32 bytes. `currentLiquidityRate` is the THIRD field (slot 2), NOT second — `liquidityIndex` occupies slot 1. Getting the slot offset wrong produces a nonsensical APY that the sanity filter catches.

**`utils/treasury_allocation.py` — AllocationOptimizer**
- Gemini LLM call (thinking=False for speed) that returns JSON array of `{protocol_id, allocation_pct, rationale}`.
- Tranche targets: liquidity_reserve 15% → Aave, yield_core 65% → Morpho, opportunistic 20% → Gains.
- `_SPLIT_THRESHOLD = $150`: below this, skips LLM and puts all capital in best risk-adjusted APY protocol (gas efficiency).
- `_MIN_ALLOC_USD = $50`: entries below this are dropped from the allocation.
- Validates: protocol IDs against available opps, pct sum ±5pp tolerance (before filtering invalid IDs), normalizes after filtering.
- Falls back to rule-based (single protocol) on any LLM failure, parse error, or invalid output — never crashes.
- **Pitfall**: `generate_proposals()` now produces multiple DEPLOY_YIELD proposals (one per tranche). Proposal IDs are `TRP_{now_str}_{idx}`. Code that assumes a single DEPLOY_YIELD proposal per cycle may need updating. The `in_flight` check in `run()` uses `type == DEPLOY_YIELD and status in in_flight` — this blocks new proposals if ANY tranche proposal is still executing, which is correct (prevents double-deployment).
- **Pitfall**: `yield_balances` must be passed from `run()` into `generate_proposals()` so the optimizer knows current deployment state. The fast path (`run_fast()`) still uses `_pick_best_protocol()` for treasury-wallet USDC detection — this is intentional (no LLM call in the fast path).

## Proactive Behaviors

These actions should be performed automatically without the user needing to ask. Skills in `.claude/commands/` define the detailed steps.

### After editing production code
When files in `agents/`, `utils/`, `core/`, or `main.py` are modified:
1. **Proactively offer to deploy** — ask "Wil je dat ik dit deploy?" or proceed if the user already indicated deployment intent. Follow the `/deploy` skill steps (pre-flight → scp → docker cp → restart → HTTP 200).

### After every deployment
2. **Automatically run key diagnostics** — after a successful deploy + HTTP 200, run at minimum: `get_balance()`, `get_free_margin()`, and a quick drawdown check. Follow the `/diag balance` steps. Report the results without being asked.

### At the end of sessions with significant changes
3. **Proactively run the `/review` audit** when the session involved:
   - Bug fixes with non-obvious root cause
   - New files or state files added
   - Changes to exchange_client, risk_manager, or execution_agent
   - Multiple deployments
   
   Present the review report and any suggested updates to CLAUDE.md, memory, or skills/hooks. Do NOT auto-save — present for approval.

### When discovering non-obvious behavior
4. **Proactively suggest a memory entry** when encountering:
   - Exchange/API quirks that aren't documented
   - User corrections or preferences
   - Bugs whose root cause would surprise a future developer
   
   Draft the memory and ask for confirmation before saving.
