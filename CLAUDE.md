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
  -> ShadowBook — virtual-outcome feedback engine (records every scored decision, resolves vs real candles)
  -> TreasuryAgent — autonomous capital allocator (full run every 60 cycles + startup, fast run every 5)
  -> SwarmLearner — decision pipeline diagnostics (optional, every 20 cycles)
  -> SwarmMonitor — watchdog thread (every 5 min, 18 checks)
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
docs/            — SOP.md, PLAN_2026-08.md (de strategische koers)
research/        — papieren aandelenanalyse; staat LOS van de swarm (zie hieronder)
```

## Research-lijn (`research/`) — losstaand van de swarm

Sinds 2026-08-11. Papieren analyse van aandelen tegen de wereld-ETF; raakt de swarm niet aan en draait **niet** op de VM. `docs/PLAN_2026-08.md` §2 automatiseert deze cadans pas vanaf ~€100k.

| Bestand | Rol |
|---|---|
| `README.md` | **De bron voor het raamwerk** — poorten, 6 dimensies, verdict-regels, 5 rekencontroles, divergentie-screen |
| `ledger.json` | 20 gescoorde namen met prijs én benchmarkprijs (URTH). De enige dataset die telt |
| `cards/<TICKER>.md` | De analyse per naam |
| `track.py` | `meet` · `due` · `dashboard` · `check` (CI) · `fundamentals` |
| `screen.py` | Laag-1 screen over ~299 ETF-holdings; vult de trechter |
| `fundamentals.py` | Toetst wacht-/terugkeervoorwaarden aan kwartaalcijfers |
| `test_ledger.py` | 485 schema- en logicacontroles; draait bij elke CI-run |
| `metrics_history.json` | Eigen kwartaalreeks (yfinance geeft er maar ~5) |

**Draait in GitHub Actions** (`.github/workflows/scorekaart.yml`), niet op de VM — `ledger.json` staat in git, dus de repo is de bron. Een kopie op de VM zou de state-duplicatie herhalen die dit project al drie keer heeft geraakt. Dagelijks 22:30 UTC prijs-triggers; maandags fundamentals + zoekronde + agenda; Telegram alléén als er actie nodig is.

**Regels die niet vanzelf spreken:**
- **Onmeetbaar ≠ gehaald.** Een metriek die niet te berekenen is geeft `onbekend`, nooit `vervuld`. Een `partial`-voorwaarde (maar één helft codeerbaar) meldt `DEELS` met "geen koopsignaal" — anders rapporteert het systeem een koopsignaal op de helft van het bewijs.
- **Screen op de 200d-MA, niet op de 52-weeksverandering.** BLKB stond −28% over 52 weken maar +42% bóven zijn 50d-MA: de kans was al voorbij. Het 52-weekscijfer vindt, de MA bepaalt of de daling er nog ís.
- **Tel altijd de kwartaalregels op.** Samengevatte `freeCashflow`-velden weken 45-67% af van de som van de kwartalen (LDOS, TTD, ALNY). Bij CHRW gaf `revenueGrowth` +19,3% terwijl de brutowinst 14% daalde — dáár zat de fout in de screen, niet in de kaart.
- **Een screen-treffer is een kandidaat, geen bevinding.** AMSC kwam als treffer boven en werd op de kaart alsnog AFVALLER.

## Runtime State Files (root dir, JSON)

Sinds 2026-07-06 zijn álle leer- en positie-statebestanden volume-mounted in `docker-compose.prod.yml` (shadow_book/report, shadow_basis_*, ticker_state, decision_history, treasury_harvest/proposals, audited_trades, portfolio_peak, cost_log, polymarket_shadow_log, config/treasury_allocation) — ze overleven een full redeploy. `deploy_update.sh` stap 2b migreert container-state eenmalig naar de host vóór de stop; de `STATE_FILES`-lijst daar moet synchroon blijven met de compose-mounts. Nieuwe statebestanden die een redeploy moeten overleven: voeg toe aan BEIDE.

> **Drift hersteld 2026-08-11.** Die regel was 13 keer níét gevolgd: `monitor_telegram_offset`, `monitor_alert_state`, `monitoring_watchlist`, `rsi_digest_state`, `llm_usage`, `pipeline_events`, `treasury_state`, `sleeve_revalidation`, `directional_revalidation`, `learning_report`, `market_regime`, `equity_regime` en `data_cache` stonden alleen in de writable layer. Nu 45 van 45 gedekt in beide lijsten. **Audit vóór elke full deploy:** `sudo docker diff agent_trader_swarm | grep -E "^A /app/[^/]+\.json$"`.

| File | Purpose |
|---|---|
| `dashboard.json` | Main dashboard state (cycle count, market data, discovery pipeline) |
| `trade_log.json` | All trades (OPEN/CLOSED). Field: **`quantity`** (not size/qty) |
| `active_assets.json` | Currently held tickers |
| `decision_history.json` | Rolling 2000-entry decision log. Field: `score` (not weighted_score) |
| `ticker_state.json` | Tiered scanning cooldowns per setup_id; `consecutive_monitor_count` per ticker |
| `pipeline_events.json` | State transition audit log |
| `cpo_state.json` | Legacy ProductOwner state (agent verwijderd 2026-07-06; main.py rapporteert CPO als IDLE) |
| `pl_status.json` / `pl_meta.json` | Pipeline status metadata |
| `data_cache.json` | Cached market data |
| `learning_report.json` | SwarmLearner diagnostics (funnel, bottlenecks, missed trades) |
| `core/agent_weights.json` | Analyst weights (tech/fund/sent), tunable |
| `config/auto_params.json` | Auto-tunable params (score_threshold, tech_prefilter_min, etc.) — **volume-mounted**, written by PerformanceAuditor |
| `cost_log.json` | Rolling 30-day history `{"history": {"YYYY-MM-DD": {...}}}` — written by CostTracker |
| `portfolio_peak.json` | Peak equity tracker for drawdown — written by RiskManager |
| `supabase_health.json` | Supabase health check — written by SwarmMonitor |
| `audited_trades.json` | PerformanceAuditor ID ledger (bounded 5000) — prevents re-auditing same trades |
| `treasury_state.json` | TreasuryAgent snapshot (hl_snapshot, aave_balance, yield_balances, treasury_wallet_usdc, total_portfolio, allocation, opportunities, funding_harvest) — every 60 cycles + startup |
| `treasury_harvest.json` | Funding Harvest state: IDLE or ACTIVE (asset, size, trade_id, entry_price, opened_at, max_close_at, rate_at_open, last_rate) |
| `treasury_proposals.json` | All proposals (PENDING/APPROVED/DEPLOYED/FAILED/REJECTED) — state machine |
| `config/treasury_allocation.json` | Allocation targets (target_trade_pct=30%, ±10pp adaptive) — volume-mounted |
| `config/treasury_protocols.json` | Yield protocol registry (Aave v3, Morpho, Gains, Compound) |
| `market_regime.json` | BTC regime `{"regime","adx","direction","atr_rank"}` — ResearchAgent writes, TreasuryAgent + ProjectLead read |
| `polymarket_shadow_log.json` | PolymarketAnalyst shadow log — Phase 1 calibration, no scoring impact |
| `shadow_book.json` | Virtual trades per scored decision (|score|≥0.10), SL 3%/TP 4.5%/24h exits, resolved vs 15m candles every 5 cycles |
| `shadow_report.json` | ShadowBook 14d aggregate by score band/direction/asset/regime — rendered in Telegram P&L digest |
| `pnl_snapshots.json` | Rolling P&L snapshots for drawdown — **volume-mounted** |
| `stocks_watchlist.json` | XYZ stocks watchlist state |
| `stocks_pending_approval.json` | XYZ stocks trades pending Telegram approval |
| `stocks_active_positions.json` | Open XYZ stock positions |
| `stocks_trade_log.json` | XYZ stocks trade history |
| `stocks_decision_history.json` | Rolling decision log for XYZ stocks pipeline |
| `config/stocks_auto_params.json` | Auto-tunable params for stocks pipeline |
| `equity_regime.json` | F1 equity-gate: XYZ100 1h > EMA200 (`equity_bull`). Written by `core/equity_regime.py` each cycle |
| `directional_revalidation.json` | F1 daily trailing-90d edge check. Written by `utils/directional_revalidation.py` |
| `thematic_exposure_positions.json` | Thematic Exposure Sleeve (EXP-008) positions + cash/budget (own wallet `0xBd6c…`) |
| `thematic_wallet_peak.json` | Thematic sleeve peak-equity tracker (SwarmMonitor Check 20) |
| `monitor_telegram_offset.json` | Laatst verwerkte Telegram-update-id. **Verlies = oude berichten opnieuw verwerken**, inclusief `/approve` |
| `monitor_alert_state.json` | Alarm-ontdubbeling van SwarmMonitor; verlies geeft dubbele meldingen |
| `monitoring_watchlist.json` | Actieve watchlist van SwarmMonitor |
| `rsi_digest_state.json` | Ontdubbeling van de RSI-digest |
| `llm_usage.json` | Token-/aanroepteller per agent per dag (bron voor CostTracker) |
| `sleeve_revalidation.json` | Sleeve-edge hertoetsing |

## Development Commands

```bash
python main.py                                    # run locally
python -m tests.pre_flight.check_imports          # syntax/import check
python -m tests.pre_flight.check_connections
python -m tests.pre_flight.check_pipeline         # full pre-flight — run before deploy
python -m pytest tests/
```

## Deployment

**After testing, always deploy to production** using the most efficient method:

### Hot-patch (default — skip rebuild, seconds)
```powershell
# 0. Validate API contracts
python -m tests.pre_flight.check_pipeline

# 1. Copy file to VM
gcloud compute scp <file> agent-trader-swarm-vm:<file> --zone=europe-west1-b

# 2. Inject into container and restart
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker cp <file> agent_trader_swarm:/app/<path> && sudo docker restart agent_trader_swarm'

# 3. MANDATORY: verify dashboard (~25s after restart)
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sleep 30 && curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/'
# 200=OK | 000=not yet up (wait 15s more) | 500=Python error (check docker logs | tail -30)
```

### Full deploy (only when Dockerfile/requirements.txt change)
```powershell
.\deploy.ps1
```
Pre-flight checks → `gcloud builds submit` → SCP config → `deploy_update.sh`.

## GCP Details

| Key | Value |
|---|---|
| Project ID | `gen-lang-client-0441524375` |
| Region / Zone | `europe-west1` / `europe-west1-b` |
| VM | `agent-trader-swarm-vm` (`e2-medium`, 2 vCPU 4 GB) |
| Image URI | `europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest` |
| Container | `agent_trader_swarm` |
| Ports | `8080` (dashboard) |

## Required Secrets

Via GCP Secret Manager on VM, or `.env.adk` locally. Optional env: `GEMINI_MODEL` (default: `gemini-2.5-flash`), `GCP_PROJECT_ID`, `GCP_REGION`.

| Secret | Used By |
|---|---|
| `GOOGLE_API_KEY` | LLMClient (Gemini) — **critical** |
| `HL_WALLET_ADDRESS` | HyperliquidExchange — API/agent wallet (signs orders) |
| `HL_PRIVATE_KEY` | HyperliquidExchange — API wallet private key — **critical** |
| `HL_VAULT_ADDRESS` | HyperliquidExchange — main/vault wallet (`walletAddress` in CCXT). Falls back to HL_WALLET_ADDRESS |
| `SUPABASE_URL` / `SUPABASE_KEY` | DatabaseClient, dashboard sync |
| `TELEGRAM_CHAT_ID` / `TELEGRAM_BOT_TOKEN` | Alert notifications, stocks approval flow |
| `HL_VAULT_PRIVATE_KEY` | TreasuryExecutor — treasury wallet (`0x4144e0b5…`) for Arbitrum txs. Falls back to HL_PRIVATE_KEY |

## Conventions

- **Imports**: stdlib → third-party → local. Lazy imports in `try/except` for optional deps.
- **Error handling**: Agents catch individually; main loop never crashes (fail-open). Optional agents (CPO, SwarmLearner) are `None`-guarded.
- **Critical dependency failures**: Fail loudly once (log + Telegram alert), disable subsystem, stop retrying. Never paper over with silent skips.
- **Logging**: `logging.getLogger("AgentName")` per class. Heartbeat log → `heartbeat.log`.
- **State files**: Always `try/except` JSON read/write. Use `sanitize()` for NaN/Inf before serialization.
- **Health reporting**: `SwarmHealthManager.report_health()` → Supabase `swarm_health` table. Only ACTIVE/IDLE/ERROR/STARTING accepted — custom values silently fail.
- **Tiered scanning**: `TickerStateTracker` manages cooldowns — check `should_analyze()` before processing a ticker.
- **Windows compat**: `sys.stdout.reconfigure(encoding='utf-8')` at top of main.py.

## Trading Strategy (ijkpunt 2026-05-29)

Regime-aware, asset-klasse-specifieke signaalfuncties. Backtest 60d, 18 HL-tickers: **+44%** vs **-9%** baseline.

### ⚠️ GROTE WIJZIGING — Directional Core Redesign (2026-07-21)

**Context voor toekomstige analyses**: op 2026-07-21 verhandelde de swarm 26/26 gesloten trades als SHORT in een bevestigde TRENDING_BULL (−$33, WR 34.6%) — een structurele counter-trend short-bias. Diagnose: de richting werd bepaald door (1) een mini-backtest recency-picker in `research_agent` die op de OUDE verliezende baseline-strategie draaide, en (2) een stapel compenserende drempel-knoppen (×0.60 SHORT-korting 2×, regime×richting shadow-multiplier-tabel, force-SHORT override). Die stapel kon zichzelf niet corrigeren en dreef shorts erdoor.

**De fix (gefaseerd G0–G4, volledig gedocumenteerd in `docs/DIRECTIONAL_CORE_REDESIGN.md`):**
- **Laag 1 — richting uit bewezen regels**: de discrete regime-bewuste signaalfuncties (`signal_crypto/tech/commodities`) zijn verbatim geport naar **`core/directional_signals.py`** en zijn nu de autoritatieve richtingsbron voor momentum-catalysts (TA_BACKTEST/SWING_4H). `ProjectLead._rule_direction()` berekent ze op een dedicated gecachte 600-candle OHLCV-fetch (`technical_analyst.get_ohlcv_df()`). Rule=0 → NO_GO (`RULE_NO_SETUP`); ±1 → richting; data onbeschikbaar → veilige fallback. News-sentiment & mean-reversion catalysts houden hun eigen richting.
- **Stapel VERWIJDERD**: ×0.60 SHORT-korting (gate 1 + conviction-gate), `_regime_dir_multipliers`/`_load_regime_dir_multipliers`/`_DEFAULT_REGIME_DIR_MULTIPLIERS`, `research_agent` force-SHORT override, en de interim `BULL_SHORT_STOP`. Drempel is nu **symmetrisch** (alleen `_REGIME_THRESHOLD_MULT`, direction-agnostisch, blijft).
- **Laag 2 — supervisor**: `SwarmMonitor` Check 21 `_check_directional_pathology` (flag-only): eenzijdigheid (laatste 8 trades zelfde richting) + richting-vs-regime mismatch (>70% counter-trend in 48u).

**Onderbouwing (historisch, geen live-wachttijd)**: `scripts/validate_rule_direction.py` toonde dat de regels alle 26 verliesshorts als NONE (geen setup) zouden hebben geweigerd (+$32.83 netto beter). De regels vuren ~8% van candles, LONG ~2× SHORT in bull. Reconciliatie (`scripts/reconcile_shadow_vs_realized.py`): shadow_book overwaardeert shorts systematisch (vaste 4.5%TP/24u exit) — NIET vertrouwen voor richting; realized + 60d-backtest zijn de betrouwbare bronnen.

**Gevolg voor gedrag**: de funnel is nu véél selectiever — de meeste momentum-kandidaten worden `RULE_NO_SETUP`. Dat is by-design (alleen echte setups); ~30-40 setups/dag universe-breed, dus geen echte drought. Trade-frequentie ligt merkbaar lager dan vóór 2026-07-21 — dat is de bedoeling, geen bug. **Bij analyse van performance vóór vs na 2026-07-21: dit is de breuklijn.**

**Nevenbevinding + fix (2026-07-21)**: Supabase closed-trade sync stopte ~half maart 2026 — realized ground-truth staat sindsdien alleen in `trade_log.json`. De PerformanceAuditor (`utils/auditor.py`) las closed trades uit Supabase zolang die "available" was (regime: `is_available()` True ook al is de data stale) → las de 27 bevroren maart-trades, vond ze allemaal ge-audit → **weight-learning lag ~4 maanden stil**. De fallback naar `trade_log.json` triggerde nooit (alleen bij DB *onbeschikbaar*). **Fix**: `auditor.run()` leest nu altijd uit `trade_log.json` (de operationele waarheid), dedup via de `audited_trades.json`-ledger (id als string). Guardrail: de ledger is eenmalig geseed met de 26 pre-redesign backlog-trades zodat de verliesgevende counter-trend shorts van de OUDE richtingslogica NIET geleerd worden — alleen verse post-redesign trades sturen de gewichten. `_tune_all_params`/deadlock-recovery blijven gated achter `AUDITOR_ENABLED` (default false), dus de self-tightening-valkuil blijft uit; alleen `update_weights` (tech/fund/sent) reactiveert.

### ⚠️ F1 — armed-gate directional trader (2026-07-23)

Na een diepe F0-diagnose (health-review op een getrouwe backtest-harness die de echte `StrategyManager` replayt) bleek: **crypto heeft geen edge, shorts zijn dood, en het +44% ijkpunt was NIET het live-systeem** (het was TechStocks-gedreven op een specifiek snapshot; de live rules+management reproduceren het niet). De enige gevalideerde edge is **equity-gated tech-stock LONGs** — bescheiden + lumpy (~+8% realistisch portfolio / ~20% geann., geconcentreerd in tech-rally's). Volledig gedocumenteerd in memory `feedback_retune_f0_findings` + `project_f1_directional_techlong`.

De directional trader verhandelt daarom alléén die slice, config-gedreven in `config/auto_params.json`:
- `armed_mode_enabled` (aan/uit), `armed_allowed_directions=["LONG"]`, `armed_allowed_asset_classes=["tech_stock"]`, `armed_use_equity_gate=True`.
- **Armed-gate** in `project_lead` (vóór GATE_1): blokkeert alles buiten de slice → `[FUNNEL] …: ARMED_GATE — <reden>`. Crypto/commodity, SHORT, en tech-LONG-bij-equity-bear worden allemaal geweigerd ("armed & waiting").
- **Equity-gate** uit `core/equity_regime.py`: tech-stocks volgen de equity-markt (XYZ100 1h > EMA200), **NIET BTC** — dat was de sleutelfout in de oude logica. Fail-closed.
- **Kapitaal-cap** `directional_exposure_cap_usd` (=$300) in `execution_agent._execute_order_inner`: begrenst open directional-notional (excl. sleeve/harvest).
- **Dagelijkse re-validatie** `utils/directional_revalidation.py` (main.py `cycle%60==30`, 24u-throttle): trailing-90d backtest van de deployed config; DE-RISKT autonoom (pauzeert) alleen als `revalidation_autopause_enabled=True` (default False = observeren+alarmeren). Adding-risk (shorts/crypto aanzetten) vereist menselijke review — les uit het oude reactieve systeem dat faalde.

**Pauzeren = veilige stand**: `armed_mode_enabled=False` + `score_threshold` hoog (bv. 0.40). Live-config: `armed_mode_enabled=True`, `score_threshold=0.12`.

### Signaalfuncties per asset-klasse (`core/strategy_logic.py`)

**Crypto — `get_crypto_signal(df, i)`**
- LONG: MACD zero-cross omhoog + ADX>20 + +DI>-DI + boven EMA200; OF stoch-RSI < 0.20 dip-buy boven EMA50
- SHORT: BB upper rejection (prev raakte upper, sluit < midlijn, MACD draait); OF trend-cont short onder EMA200 + MACD-hist flip negatief

**Tech Stocks — `get_tech_signal(df, i)`**
- LONG: Supertrend flip bullish + ADX>18; OF MACD-hist flip positief boven EMA200
- SHORT: ALLEEN onder EMA200 + bearish divergentie (hogere prijs, lagere RSI over 10 bars). Nooit in bull-regime.

**Commodities — `get_commodity_signal(df, i)`**
- LONG: EMA ribbon (prijs>ema8>ema20>ema50) + RSI 52-72 + ADX>15
- SHORT: Supertrend flip bearish + ADX>18; OF MACD zero-cross omlaag onder EMA200 + ADX>20

Routing: `detect_asset_class(ticker)` → `get_signal_for_asset(asset_class, df, i)`.

### EMA200 gate + Commodity weights
- TRENDING regime only: aligned ×1.10, against ×0.85. Niet ×0.75 — stapelt met ADX-damping (×0.70) → dubbele straf.
- `COMMODITY_WEIGHTS`: EMA (0.28), ADX (0.22) zwaarder. Commodity tickers: `XYZ-CL/BRENTOIL/GOLD/SILVER/NATGAS/COPPER/PLATINUM/PALLADIUM`

### Drempelwaarden
| Parameter | Waarde | Reden |
|---|---|---|
| `score_threshold` | 0.20 | Kwaliteitsfiltering op TA-niveau via EMA200+ADX |
| `tech_prefilter_min` | 0.10 | Hersteld na noodstop mei 2026 |

### Backtestresultaten (60d, 18 tickers, 2026-03/05)
| Asset-klasse | Finale | Oud | Delta |
|---|---|---|---|
| Crypto | +13.7% | -14.9% | +28.6pp |
| Tech Stocks | +119.9% | +2.3% | +117.6pp |
| Commodities | -8.2% | -14.3% | +6.1pp |
| **Totaal** | **+44.2%** | **-9.1%** | **+53pp** |

Backtest scripts: `scripts/strategy_research.py`, `strategy_windows.py`, `strategy_windows_xyz.py`, `strategy_final.py`, `strategy_long_short_split.py`

### Strategie-pitfalls
- **Dubbele damping**: ADX (×0.7 bij ADX<20) + EMA200 (×0.85 tegen trend) stapelen: 0.50 → 0.30. Houd `score_threshold` ≤ 0.20.
- **Tech shorts**: 0% WR in bull-regime (MU/SNDK/AMD). Nooit activeren boven EMA200.
- **Commodity longs**: EMA-ribbon + RSI-zone is selectief. Commodities primair voor shorts.
- **`get_agent_signal()`**: Verouderd, backward-compat only, niet gebruikt in pipeline of backtester.

## Common Pitfalls

- **NaN in JSON**: Always `sanitize()` before `json.dump()`. Math on missing data produces NaN.
- **USDT/USDC duplication**: Pipeline deduplicates — skips USDT variant if USDC exists same cycle.
- **Secret loading order**: GCP Secret Manager → `os.getenv()` → `.env.adk`. Check IAM role (`Secret Manager Secret Accessor`).
- **Docker auth on VM**: `sudo gcloud auth configure-docker europe-west1-docker.pkg.dev` before pull.
- **`docker cp` lands files as root**: the app runs as `trader` (uid 1000). Hot-patching a writable **state-file** (e.g. `ticker_state.json`) via `docker cp` makes it `root:root` mode 644 → trader can't write → endless `Permission denied` save loop, mtime frozen. ONLY `docker cp` code (`agents/`/`utils/`/`core/`/`main.py`), never root/`config/` `*.json`. If it happens: `sudo docker exec -u root agent_trader_swarm sh -c "chown trader:trader /app/<file>"`. Diagnose: `ls -la /app/*.json /app/config/*.json | grep root`. `config/auto_params.json` is immune (mode 666 + volume-mounted). Full rebuild self-heals.
- **Any `docker-compose` recreate wipes ALL `docker cp` hot-patches**: hot-patched files (code via `docker cp`, or any `config/*.json` not in the `volumes:` list) live only in the container's writable layer. `docker-compose down`/`up` (e.g. to pick up a new `docker-compose.prod.yml` volume mount) recreates the container **from the pushed image**, silently discarding every hot-patch since the last real `deploy.ps1` build — caused a ~4min prod outage 2026-07-14 (main.py, auditor.py, shadow_xyz_lab.py, config/sleeves.json all reverted). Before ANY compose-level recreate: list what's been hot-patched this session and re-`docker cp` it all back in afterward, or do a full `deploy.ps1` rebuild first so the image itself is current. Also: `docker-compose up -d --force-recreate` can fail with `KeyError: 'ContainerConfig'` on Buildx-built images (docker-compose v1.29 bug) — use `down` then plain `up -d` instead.
- **VM had TWO compose home-dirs — now structurally fixed (2026-07-17): canonical dir is PINNED in `deploy_update.sh`**: CI deploys land in `/home/sa_116183673897831795495/` (service-account home), manual ssh in `/home/bartpersoons_gmail_com/`. Bind-mount sources resolve relative to the compose working dir, so each caller used to create its own parallel state universe — which turned the 2026-07-16 deploy incident from "outage" into "apparent total state loss" (recovered same day via `scripts/recover_state_20260716.sh` — if state ever seems lost, check the other home dir first). Fix: `deploy_update.sh` step 0 relocates itself to `CANONICAL_DIR=/home/bartpersoons_gmail_com` (copying freshly-uploaded compose/script/.env along) regardless of caller — e2e-verified 2026-07-17 by running it from the SA home. The stale SA-home state is archived in `stale_state_archive_20260716/` with the compose file removed as a tripwire (any hand-run compose there fails loudly) + README. Do NOT restore from that archive; live data is in the canonical dir.
- **`deploy.ps1`/`deploy_update.sh` full-deploy failure chain (2026-07-16)**: three independent bugs compounded into a ~10min outage + apparent loss of ~15 state files (later recovered from the other compose home-dir — see pitfall above). (1) `deploy.ps1` used to **regenerate** `docker-compose.prod.yml` from a stale 3-mount template before every deploy, silently stripping ~25 real volume mounts — removed; the committed file is now the sole source of truth, script only validates it exists. (2) Windows' bundled pscp fails on multi-file `gcloud compute scp` to a bare `~/` destination (`remote filespec ~/: not a directory`) — `deploy.ps1` didn't check the exit code, so it silently continued running the **old** `deploy_update.sh` against the **new** image; that old script then crashed under `set -e` on an unguarded `chmod`, leaving zero containers running. Fixed: resolve `$HOME` via SSH first and use an explicit path, plus `$LASTEXITCODE` checks after scp/ssh that abort loudly. (3) `deploy_update.sh`'s state-preserve step only `docker cp`s from the OLD container if it's still running — when it isn't (exactly the scenario in (2)), every "missing" state file gets silently touch-emptied with no warning. Fixed: step 2a now backs up all state files to `state_backups/<timestamp>/` unconditionally (host-filesystem-only, no live container needed) before anything destructive; the touch-loop restores from the latest backup instead of touch-emptying, and either path now logs loudly. Also hit: SCP transfers a script with CRLF line endings from Windows → `bad interpreter: /bin/bash^M` on the VM; `deploy.ps1` now runs `sed -i 's/\r$//'` on it before executing.
- **Single-file bind mounts break on rename-based writes**: `docker-compose.prod.yml` bind-mounts individual state files (e.g. `./trade_log.json:/app/trade_log.json`), which Linux binds to a specific **inode**, not a path. An atomic write via `os.replace()`/`tempfile`+rename (the normal "safe write" pattern) unlinks that inode from the host path and points the path at a *new* one — the running container keeps writing to the now-orphaned old inode, invisible from the host, while the host file silently diverges. Long suspected as the cause of the 436→6 trade loss in `trade_log.json` on 2026-07-17 — **that turned out to be a different bug entirely, see the `deploy.ps1` state-overwrite pitfall below** (2026-07-30). This inode failure mode is still real (reproduced identically doing manual recovery with `os.replace`), just not what happened on 07-17. All in-app Python writers already use safe in-place `open(path, "w")` (confirmed repo-wide, no `os.replace`/`shutil.move`/`NamedTemporaryFile` on state files) — the risk is host-side one-off scripts (manual recovery, hotfixes) using rename-based "atomic" writes out of habit. Rule: any manual edit to a volume-mounted state file, on the VM, MUST be in-place (`open(path,'w')` / `> file`), never rename-over. Diagnose a broken mount: compare `docker exec agent_trader_swarm md5sum /app/<file>` vs host `md5sum <file>` — mismatch means orphaned inode; fix by writing in-place into the container path directly (`docker exec -i ... python3 -c "...open('/app/<file>','w')..."`) merged with the host's latest content, then mirror the same content in-place on the host. A full `docker-compose` recreate also re-resolves the mount to the current host path (see recreate pitfall above) — but wipes hot-patches, so prefer the in-place fix for one-off recovery.
- **`deploy.ps1` shipped LOCAL state files over production (root cause of the 07-17 trade loss + two orphan shorts)** — fixed 2026-07-30. The scp line included `dashboard.json trade_log.json active_assets.json`, landing them in the VM home dir — exactly where the bind mounts point. So **every full deploy overwrote the live trading book with the dev machine's stale snapshot** (a 17 July copy holding 6 positions all marked `OPEN`). On restart the swarm saw 6 "open" positions Hyperliquid didn't have, issued close orders, and — because `close_position()` sent plain market orders — each "close" **opened a real position**: $2.107 notional short on 24-07, $128 on 28-07, both with fictional profit booked into `trade_log.json` that then fed the PerformanceAuditor's weight learning. Two independent fixes now guard this: (1) deploy.ps1 no longer sends state files (production is the source of truth; `deploy_update.sh` seeds them from backup or an empty JSON shape if missing), and (2) all closing/partial-exit orders pass `reduce_only=True`, so a close can never open anything, plus phantom trades are booked `PHANTOM_NO_POSITION` with PnL 0 (excluded from weight learning via `_NON_STRATEGY_CLOSE_REASONS` in `utils/auditor.py`). Verified live: 5 stale phantoms booked flat, zero positions opened. **Never add a state file to that scp list.**
- **HL wallet "does not exist"**: Wallet not yet funded on Hyperliquid. Fix: deposit USDC, then restart. Code logs once and suspends trading; won't spam errors.
- **Unified mode balance double-count**: `get_balance()` = `spot_usdc + marginSummary.accountValue`. NEVER sum CCXT `balance['USDC']['total']` + spot — double-counts pledged USDC.
- **Partial TP min notional**: HL rejects orders < $10. Move SL to breakeven (entry + 0.1% fee) instead. Log in `skipped_partials` (not `partial_exits`). `sl_stage` advances to 1.
- **Auditor re-audits without ledger**: Supabase has no `audited` column — returns latest 100 CLOSED every cycle. Fixed with `audited_trades.json` ID ledger (bounded 5000). Reset weight learning → also delete this ledger.
- **`pnl` is gross; `pnl_net` is real**: On close, `execution_agent` writes `fees`, `funding_received`, `pnl_net` via `get_trade_costs()`. Use `pnl_net` for profitability analysis. Records before 2026-06-12 have `fees≈0`.
- **History import ghosts**: Import scripts create records with `null`/`0.0` pnl → corrupt win-rate, block weight updates. Validate non-null pnl before writing. Cleanup: remove `id.startswith("RECOVERED_")`. Trade log field is **`quantity`** (not `size`/`qty`).
- **`exit_time`/`entry_time` mixed types crash sort/comparison**: `entry_time` is written as a raw epoch float at open (`time.time()`/`.timestamp()`); `exit_time` as an ISO string by every close path (`.isoformat()`). A trade missing `exit_time` falls back to the float `entry_time` in the same list as siblings with a string `exit_time` → `'<'/'>=' not supported between instances of 'float' and 'str'`. Hit in `PerformanceAuditor.check_asset_performance()` 2026-07-07 (root cause: one legacy `GHOST_POSITION_SYNC` record from 2026-05-18 written by an older code path with `closed_at` instead of `exit_time`). Fix: `PerformanceAuditor._last_activity_epoch()` normalizes both fields to a float epoch before any sort/comparison — use it (or the same pattern) anywhere trade timestamps get sorted/compared.
- **PerformanceAuditor self-tightening loop**: Losses → raises `tech_prefilter_min`/`score_threshold` → zero signals → starvation. Check `auto_params._meta`. Fix: lower `tech_prefilter_min` to 0.10.
- **`drawdown_offboard_pct` scope**: Per-ticker offboarding only — does NOT block portfolio-level trading. Real gate: `CircuitBreaker.can_trade()`.
- **MONITOR deadlock**: Ticker can loop in MONITOR zone 1000+ cycles. After 50 consecutive MONITOR cycles above promote floor, `main.py` auto-promotes to BUILD_CASE (WARNING log). Tracked via `consecutive_monitor_count` in `ticker_state.json`. SwarmMonitor Check 15 alerts.
- **Decision bands must be threshold-derived**: Four stacked gates must align — (1) `abs(score)>=threshold` (SHORT ×0.60), (2) LLM bands in `project_lead.py` derived from `_effective_threshold` NOT hardcoded, (3) `SETUP_MIN_CONVICTION` (SHORT ×0.60), (4) MONITOR auto-promote floor. Hardcoded constants anywhere recreate a dead zone (zero trades Jun 7–12 from hardcoded 0.38/0.28 vs threshold 0.20).
- **Regime-direction multipliers** (`_DEFAULT_REGIME_DIR_MULTIPLIERS` + `_load_regime_dir_multipliers()` in `project_lead.py`): threshold multipliers per (regime, direction) cell. Auto-reloaded from `shadow_report.json` every 30 min. Since 2026-07-02 (EXP-003): cells with n≥15 fresh samples ALWAYS override the bootstrap defaults — **including neutral 1.0** — and penalties are capped at ×2.0. Multiplier applied BEFORE the SHORT ×0.60 discount. Logged as `[ShadowMult] Active multipliers: ...` (INFO, whole table).
- **Adaptive gates must decay symmetrically** (EXP-002 postmortem, 2026-07-02): the original loader only overrode defaults when `_mult != 1.0`, so cells that turned neutral kept their stale bootstrap penalty (RANGING+SHORT stuck at ×2.0 despite n=132/WR 47%/+avg), and `_mult` had 3 penalty tiers vs 1 very strict reward tier → self-tightening loop, same failure mode as the PerformanceAuditor pitfall. Funnel sealed: LONG bar effectively 0.60 in 3 of 4 regimes vs mean crypto |score| 0.11; -$37.48 in 10 days. Rules: fresh data always wins incl. "back to neutral"; reward tiers must mirror penalty tiers; cap any multiplier so `threshold × cap` stays reachable (×2.0 at threshold 0.20 = 0.40 bar).
- **One gate system per dimension**: RiskManager's MACRO_GATE hard-blocked shorts in TRENDING_BULL *on top of* the shadow-fed multipliers — while live shadow data showed TRENDING_BULL_SHORT as the best cell (66.7% WR). Stacked gates on the same dimension (regime×direction) can't self-correct and contradict each other. MACRO_GATE is observability-only since 2026-07-02; counter-trend filtering lives solely in the multipliers.
- **`XYZ_EQUITY_TICKERS` registry is incomplete** (7 entries) while the pipeline trades ~20 XYZ equities (AAPL, META, SP500, EWY, …). For any XYZ-equity membership check use `detect_asset_class(ticker) == 'tech_stock'` (`core/strategy_logic.py`, prefix-based), never the registry. The registry is only for yfinance symbol mapping.
- **sl_stage is destiny — cut stage-0 early**: production data since 06-12: stage 0 (SL never moved) = 3.4% WR / -$236; stage 1 = -$6; stage 2 (profit-lock) = 100% WR / +$246. All P&L comes from post-entry management. `NO_PROGRESS_TIMEOUT` (StrategyManager rule 5c): stage-0 trades at/below entry after `no_progress_exit_hours` (auto-param, 5h; swing ×2) are cut, 6h re-entry cooldown, XYZ closed-market guard applies. Don't "fix" losing streaks by tightening entry thresholds before checking the stage-0 share of losses.
- **`agent_weights.json` must be explicitly applied**: `load_weights()` loads into `self.weights`, but must multiply into each signal. Pattern: `tech_signal = tech_view['signal'] * aw.get('technical', 1.0)`. Call `load_weights()` at start of each scoring cycle. Current values: `technical=1.0, fundamental=0.20, sentiment=0.5` (FA reduced from 0.5 on 2026-06-22: consistent contra-indicator across 125+ trades — higher FA correlated with losses). No restart needed to apply — `load_weights()` runs each cycle.
- **FA is a consistent contra-indicator**: across every analysis window (May, Jun 12–18, Jun 12–22), losers have higher FA than winners. FA appears to measure post-move momentum, not future edge. Keep FA weight low (≤0.25). Do not raise it without fresh shadow data showing the pattern reversed.
- **SHORT TA sign convention**: MACD/EMA/ADX/Stoch/Volume invert internally (positive=confirms SHORT). RSI/BB keep natural sign (negative=bearish). Mixing → near-zero composite. `ProjectLead` negates composite to flip back.
- **`cost_log.json` rolling history**: Structure `{"history": {"YYYY-MM-DD": {...}}}`. Access with `.get("history", {})`. Use `CostTracker().get_history()` programmatically.
- **SwarmMonitor check isolation**: Each check wrapped in `_safe_check()` — one crash no longer aborts the round. Use `agent.get("last_error") or "No details"` (`.get(key, default)` returns None on null values, not the default).
- **CYCLE_FROZEN threshold**: Cumulative `_cycle_last_advance` timer, 25min threshold (`MONITOR_CYCLE_FROZEN_MINUTES`), Heartbeat-only. Heavy cycles (cycle%60==0) legitimately run 6–19min.
- **Signal health false alerts**: Use `score is None` — `score or fallback` discards valid 0.0 scores. `decision_history` field is `score` (not `weighted_score`).
- **TA shared exchange**: Use module-level `_get_shared_exchange()` (markets loaded once, `enableRateLimit`, `_FETCH_LOCK`). Fresh ccxt per call = ~11.6s per fetch + 429 errors. OHLCV cache TTL: 1d=30m, 1h=5m.
- **XYZ TA data starvation**: `calculate_indicators` returns None below 50 candles. XYZ `fetch_limits` must be `{'1d':365,'1h':500}`. Diagnose: "[Stock TA] only 0 rows after filter" warnings.
- **XYZ commodities market hours**: Commodities (XYZ-GOLD/CL/SILVER/COPPER/NATGAS/PLATINUM/PALLADIUM) trade ~23h/day — NOT equity hours (Mon-Fri 14:30-21:00 UTC). Gate exists in TWO places: `ProjectLead` pre-TA check AND `StockTechnicalAnalyst._market_is_open()`. Both must be asset-class-aware.
- **XYZ tickers live on a separate Hyperliquid perp-dex**: raw `{"type": "metaAndAssetCtxs"}` (no `dex` param) only returns the main dex (BTC/ETH/alts, ~232 assets) — zero XYZ-* entries. XYZ synthetics need `{"type": "metaAndAssetCtxs", "dex": "xyz"}`; raw names come back as `xyz:TICKER`, normalize to `XYZ-TICKER`. `ccxt.hyperliquid().load_markets()` already handles this (enumerates `perpDexs` internally), but any raw/direct API call (like the shadow-engines) must pass `dex` explicitly. Discovered building `utils/shadow_xyz_lab.py` (2026-07-13) — first version silently returned 0 tickers.
- **XYZ perp-dex collateral differs per wallet type (scoped 2026-08-03)**: on the **self-custody thematic wallet `0xBd6c`** the xyz builder-dex has its OWN margin pool that must be pre-funded — everything in the bullet below applies there. On the **main UNIFIED account `0x92D4` it does NOT**: opening an XYZ position draws collateral straight from the shared spot pool on demand. Verified by buying 0.186 XYZ-SMH with xyz-dex at $0.00 — the order filled, spot `total` stayed $715.27 and spot `hold` went $24.18 → $124.04. Corollary: `sendAsset` spot→xyz on the unified account is accepted by HL and even logged in `userNonFundingLedgerUpdates` (type `send`, fee 0) but is a **silent no-op** — no balance moves on either side. Don't debug that; just place the order. Also: `HyperliquidExchange._normalize_symbol()` did not resolve `XYZ-SMH` (stale market cache misses recently-listed xyz tickers) while ccxt itself knows `XYZ-SMH/USDC:USDC` — pass the explicit ccxt symbol to `signing_client` when the wrapper says "not listed on Hyperliquid".
- **XYZ perp-dex separate collateral (self-custody wallets)**: the "xyz" builder perp-dex has its OWN margin pool; main-dex USDC does NOT count as margin there. Drain it to ~$0 and every XYZ order fails with HL `Insufficient margin — account fully allocated` while the wallet looks healthy — `create_order()` returns `None`, sleeve stalls silently (happened 2026-07-18→22, thematic opened nothing for 4 days). Per-dex balance: `client.fetch_balance(params={"dex":"xyz"})` → `info.marginSummary.accountValue`. Funding is a `sendAsset` HIP-3 transfer (user-signed EIP-712, mainnet domain chainId 42161 / signatureChainId 0xa4b1, `sourceDex`/`destinationDex`, destination = account itself). **Who can sign depends on wallet type**: the **thematic sleeve runs on a SELF-CUSTODY wallet `0xBd6c…`** (HL_THEMATIC_WALLET_ADDRESS/KEY, key derives to the account itself) — the swarm/script CAN fund it (confirmed 2026-07-23: `sendAsset` spot→xyz one hop, `status: ok`). Deposits via HL "Send Tokens" land in **spot**, not the xyz-dex — move them with sendAsset spot→xyz. The **main wallet `0x92D4…`**: its HL *order-signing* client uses an AGENT key (`HL_PRIVATE_KEY` → 0xe18f… ≠ account) which HL forbids from user-signed actions. BUT the swarm ALSO holds 0x92D4's **master key** via `HL_VAULT_PRIVATE_KEY` (derives to 0x92D4 itself; treasury uses it for Arbitrum) — so the swarm CAN sign user-signed actions for 0x92D4 (e.g. `sendAsset 0x92D4 → 0xBd6c` for autonomous sleeve-funding), just not through the default order client. Fix (thematic): `scripts/fund_xyz_dex.py` targeting the thematic wallet (`--from-dex spot`). SwarmMonitor Check 22 (`_check_thematic_xyz_collateral`, flag-only) alerts when xyz-dex < $65 while the sleeve is live.

- **`requirements.txt` moet gepind blijven — ongepind brak CI én deploy (2026-08-11)**: 21 van de 22 pakketten stonden zonder versie. pip 26 gaf het op met `error: resolution-too-deep` na 6min24 — en dat brak niet alleen `ci.yml` maar ook `deploy.yml` regel 29, dus **er kon niet meer gedeployd worden**. PR's faalden er weken op zonder dat het opviel (PR #2 werd gemerged met een rode check). Fix: versies **gemeten** aan de draaiende container (`docker exec agent_trader_swarm pip freeze`), niet gekozen, en exact (`==`) vastgelegd. Resultaat: `import-check` van 6min24-fail naar 51s-pass. Bij het bijwerken van een pakket: hier verhogen, deployen, dan `check_pipeline` draaien. Voeg **nooit** een ongepind pakket toe.
- **Statebestanden driften uit compose én `STATE_FILES` — audit met `docker diff` (2026-08-11)**: CLAUDE.md schrijft voor dat nieuwe statebestanden aan BEIDE lijsten worden toegevoegd, maar dat was 13 keer niet gebeurd. Die stonden in de **writable layer** van de container en waren dus noch gemount, noch opgenomen in de backup — een compose-recreate had ze vernietigd. Zwaarste geval: `monitor_telegram_offset.json`; zonder offset kan de bot oude Telegram-berichten opnieuw verwerken, inclusief `/approve`-commando's uit de stocks-goedkeuringsflow. **Auditcommando:** `sudo docker diff agent_trader_swarm | grep -E "^A /app/[^/]+\.json$"` — alles wat daar verschijnt hoort in de mounts én in `STATE_FILES`. Draai dit vóór elke full deploy.
- **`docker diff` toont bind-mounts als toegevoegd — vals alarm**: na het toevoegen van de 13 mounts bleven de bestanden in `docker diff` staan als `A`. Docker vermeldt bind-mount-bestemmingen die niet in de image bestonden. Verifieer met `docker inspect --format '{{range .Mounts}}{{.Destination}}{{"\n"}}{{end}}'`, niet met `docker diff`.
- **Hot-patch-inventaris: vergelijk inhoud, niet md5**: `docker exec md5sum` versus een Windows-checkout geeft altijd verschillen door regeleindes (LF in de container, CRLF lokaal). Vier "gewijzigde" bestanden bleken inhoudelijk identiek. Normaliseer naar LF vóór je vergelijkt, anders jaag je op spoken.

## Treasury System

The treasury acts as a fully autonomous capital allocator — distributing USDC across yield instruments based on risk/reward, market regime, and liquidity needs.

### Capital Locations
- **Hyperliquid (HL)** — perps trading margin. Target: 30% (WR ≥ 45% → +10pp, WR < 30% → -10pp).
- **Yield protocols** — deployed on Arbitrum, target ~70%. Allocated by `_pick_best_protocol()`.
- **Treasury wallet** (`0x4144e0b5…`) — staging area; USDC here triggers automatic DEPLOY_YIELD proposal.

### Tranche Model
| Tranche | Target | Instruments | Liquidity |
|---|---|---|---|
| Liquidity reserve | ~15% | Aave v3 | Instant |
| Yield core | ~65% | Morpho, GMX GM | 1–3 days |
| Opportunistic | ~20% | HL Funding Harvest, Pendle PT | Position-dependent |

### Protocol Executors
```
TreasuryAgent
  ├── YieldOracle         — on-chain Aave APY via Pool.getReserveData (live)
  ├── RiskModel           — per-protocol risk score (SC/liquidity/counterparty) (live)
  ├── AllocationOptimizer — Gemini LLM tranche split (live, fallback rule-based)
  └── AaveExecutor (live, pool 0x794a61358D…)
      MorphoExecutor (live, BBQUSDC 0x7e97… + GTUSDCC 0x7c57…)
      GainsExecutor (live, gUSDC 0xd3443ee…, ERC-4626)
      FundingHarvestor (live, BTC/ETH HL short)
      PendleExecutor (Fase 3, custom AMM)
```

### Roadmap
- **Fase 1–2** *(voltooid 2026-05-24)*: Morpho ✓ · YIELD_SWITCH ✓ · Gains gUSDC ✓ · FundingHarvest ✓ · RiskModel ✓ · YieldOracle ✓ · AllocationOptimizer ✓
- **Fase 3** *(next)*: Pendle PT executor · Volledig geautomatiseerde multi-protocol rebalancing

### Proposal State Machine
```
PENDING → APPROVED → WITHDRAWING → BRIDGED → DEPLOYED
                   → NEEDS_MANUAL_WITHDRAWAL
                   → MONITORING (FUND_TRADING only) → COMPLETED
REBALANCE: APPROVED → REBALANCING → BRIDGE_BACK_NEEDED → (manual HL deposit)
YIELD_SWITCH: APPROVED (auto) → SWITCHING → DEPLOYED
MANUAL_ACTION_REQUIRED: terminal/informational — no executor acts on it
```
- `run()` every 60 cycles (incl. cycle 1 startup): full DeFiLlama fetch, generate proposals, advance state.
- `run_fast()` every 5 cycles: execution-only pass using cached yield data. Has its OWN local `active` set — add any new proposal status to BOTH `execute_approved_proposals()` AND `run_fast()` local active.
- **YIELD_SWITCH**: fully automatic. Triggered when best automated Arbitrum APY > deployed + 1.5% and balance ≥ $100. One switch at a time. Returns `(proposals, notif_texts)` tuple — callers send Telegram AFTER `_save_proposals()`.
- **YIELD diversification**: automatic. Triggered when single protocol > 80% of yield and total yield > $150. Partial withdrawal to bring source to 65%. `switch_amount_usd` field (not `amount_usd`). Cooldown 12h. Shares YIELD_SWITCH in-flight guard.
- **MANUAL_ACTION_REQUIRED**: emitted when overweight protocol is epoch-based (`immediate_withdraw=false`) — can't auto-move. Fires Telegram alert once per cooldown window. Prefix `TRDM_`. Resolve by manually withdrawing.

### Protocol routing
Use `protocol_type` field (`aave_v3`/`erc4626`/`compound_v3`), not the `protocol` label (can mismatch from pre-fix proposals).

### Pre-flight tests
`tests/pre_flight/check_treasury.py` — 15 checks, 124 assertions, wired into `check_pipeline.py`. Must pass before deploy.

### Treasury Pitfalls

- **False drawdown halt**: `RiskManager.check_portfolio_drawdown()` calls `get_total_yield_balance()` to sum ALL automated protocols. Refactoring to `get_aave_balance()` only makes yield capital look like a drawdown.
- **Curve never good**: `_pick_best_protocol()` hardcoded to never recommend non-Arbitrum non-automated protocols. Do not revert.
- **PENDING TTL**: 6h (`_PROPOSAL_TTL_H`). APPROVED/DEPLOYED/FAILED kept forever in history.
- **`source_treasury` skips bridge**: Goes directly to BRIDGED — USDC already on Arbitrum.
- **Morpho vaults**: Both `automated=true` in `config/treasury_protocols.json`. `vault_address=null` → FAILED proposals.
- **TVL thresholds**: Tier-based (`stable=$5M, medium=$10M, exposure=$50M`). GTUSDCC has $3.2M TVL < $5M threshold — may not appear in opportunities.
- **YIELD_SWITCH SWITCHING**: Must be in `active` set in BOTH `execute_approved_proposals()` AND `run_fast()` local active or switches stall silently.
- **ERC-4626 selector**: `0x6e553f65` = `deposit(uint256,address)`. Compound v3: `0xf2b9fdb8` = `supply(address,uint)`. ERC-4626 partial withdrawal: `0xb460af94` = `withdraw(assets)`.
- **FUND_TRADING proposals**: Informational top-up reminders. Auto-complete when HL balance rises ≥ 90% of proposal amount. User bridges manually via HL web app.
- **FUND_SLEEVE proposals (meta-allocator, G2)**: autonomous funding of the Thematic Exposure Sleeve's separate wallet (`0xBd6c`). Self-contained in `TreasuryAgent` (NOT via `treasury_executor.advance_proposal`): `_check_sleeve_funding()` generates when sleeve < `sleeve_trigger_frac`×target (target = min(`sleeve_cap_usd`, `sleeve_target_pct`% of grand_total)); `_execute_fund_sleeve()` (in run() + run_fast()) runs APPROVED via `_master_send_usdc()` = `sendAsset` master(0x92D4)→sleeve spot→spot with the MASTER key (`_master_signing_client`, HL_VAULT_*). Approval reuses `/approve <id>`; 1st top-up PENDING, then `sleeve_first_topup_approved` flips → auto. **HL transfer rules learned 2026-07-23**: cross-account sends MUST go `sourceDex="spot"` (perp source → "only supports sending assets through spot"); `usdClassTransfer` is disabled on unified accounts; the sleeve's own spot→xyz sweep (`ThematicExposureLab._sweep_idle_to_xyz`, G0) then deploys it to the xyz builder-dex. Config/caps in `config/treasury_allocation.json` (`sleeve_*`). **G3 reverse — SLEEVE_REBALANCE**: `_check_sleeve_rebalance()` pulls excess idle capital (`withdrawable_total`, never position margin) back to the master when sleeve > `sleeve_rebalance_frac`×target (1.40) or > cap; auto-APPROVED (de-risking direction, Telegram-notified); `_execute_sleeve_rebalance()` = `_sleeve_send_to_master()` two hops with the SLEEVE key (xyz→spot, then sleeve spot→master spot). All sendAsset signing shares the `TreasuryAgent._send_asset()` static helper.
- **RPC for Arbitrum**: `https://arbitrum.gateway.tenderly.co` — only working public RPC from GCP. drpc.org/meowrpc.com/arb1.arbitrum.io → 403. ankr requires key. zan.top rate-limits. Retry-with-backoff in `_rpc()` (2s, 4s). 3s sleep between approve + supply in `_deposit_aave()`.
- **HL bridge**: Bridge2 (`0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7`), selector `0xb30b5bce`. Signature tuple order: `(uint256 r, uint256 s, uint8 v)` NOT `(v,r,s)`. EIP-2612 permit, no separate approve TX.
- **EIP-2612 USDC on Arbitrum**: `name="USD Coin"`, `version="2"`, `chainId=42161`, `verifyingContract=0xaf88d065...`. nonces selector=`0x7ecebe00`. Sign: `Account.sign_typed_data(pk, full_message={...})`. r/s are `int` — use `_u256()`.
- **Bridge step 1 skippable**: If USDC already on vault Arb (from failed prior attempt), step 1 skipped, full balance bridged — auto-recovers stuck funds.
- **Spurious YIELD_SWITCH on missing APY**: If deployed protocol absent from cached opps, `current_apy` defaults 0.0 → triggers switch. Skip switch when `pid not in apy_by_id`.
- **Morpho BBQUSDC deposit cap**: Large deposits ($1,670+) revert. Route large amounts to Aave v3. Also $214–220 deposits FAILED (RPC 403 on dry-run + revert) — watch retry behaviour.
- **Liquidity guard — epoch-based vaults never auto-deposit destination**: Protocols with `immediate_withdraw=false` (Gains gUSDC) excluded from ALL automated deployment paths: `_pick_best_protocol()`, `AllocationOptimizer.optimize()`, `_check_yield_switch()`, `_check_yield_diversification()`. Can still withdraw manually and read balance. New protocols: set `immediate_withdraw` honestly in config.
- **SWITCHING uses `switch_amount_usd`**: For partial switches, `amount_usd` = full source balance; only `switch_amount_usd` was withdrawn. Handler: `switch_amt = float(proposal.get("switch_amount_usd") or proposal.get("amount_usd", 0))`. Deposit capped at `switch_amt * 1.05`.
- **GMX GM / Gains gUSDC**: Single-sided USDC counterparty risk — vault absorbs losses when traders win. Statistically favourable long-term.
- **Funding Harvest**: Min rate `_HARVEST_MIN_RATE_8H=0.01%/8h`. BTC/ETH only (`_HARVEST_ALLOWED_ASSETS`). Max notional $150. Auto-closes after 48h or rate < `0.003%/8h`. State survives restarts via `treasury_harvest.json`.
- **Harvest guard**: `"harvest": True` trades must be skipped in the backfill pass, Pass 3 (EXTERNAL_CLOSURE sync), and `evaluate_position()`. Pre-flight check 11 verifies all three guards.
- **Pendle PT**: Custom AMM, not ERC-4626. Requires `swapExactTokenForPt()`. Must hold to maturity to redeem at par.

### Fase 2 Components

**`utils/treasury_risk.py` — RiskModel**
- 5 dimensions: sc(0.25), liquidity(0.25), counterparty(0.30), maturity(0.10), tvl(0.10). Must sum 1.0.
- `enrich_opportunities(opps)` adds `risk_score` dict + `risk_adjusted_apy`, re-sorts by risk-adjusted APY.
- New protocol without `_PROFILES` entry gets `_UNKNOWN_PROFILE` (conservative 0.50) and ranks below well-profiled ones.

**`utils/treasury_yield_oracle.py` — YieldOracle**
- `Aave v3 Pool.getReserveData(USDC)` — selector `0x35ea6a75`. `currentLiquidityRate` at ABI slot 2 (bytes 64–95, third field). APY = `((1 + rate_ray/RAY/SPY)^SPY - 1) * 100`. RAY=1e27, SPY=31536000. Sanity: [0%, 50%].
- Must run BEFORE RiskModel enrichment (pre-flight check 13 verifies). Wrong slot → nonsensical APY caught by sanity filter.

**`utils/treasury_allocation.py` — AllocationOptimizer**
- Gemini LLM returns `[{protocol_id, allocation_pct, rationale}]`. Below $150: skip LLM, use best risk-adjusted protocol. Min alloc $50/tranche.
- Produces multiple DEPLOY_YIELD proposals (one per tranche), IDs `TRP_{now}_{idx}`. In-flight check blocks new proposals while ANY tranche is executing.
- `yield_balances` must be passed from `run()` into `generate_proposals()`. Fast path uses `_pick_best_protocol()` (no LLM).

## Proactive Behaviors

### After editing production code
When files in `agents/`, `utils/`, `core/`, or `main.py` are modified:
1. **Proactively offer to deploy** — "Wil je dat ik dit deploy?" or proceed if intent clear. Follow `/deploy` skill (pre-flight → scp → docker cp → restart → HTTP 200).

### After every deployment
2. **Automatically run diagnostics** — `get_balance()`, `get_free_margin()`, quick drawdown check. Follow `/diag balance`. Report without being asked.

### At end of sessions with significant changes
3. **Run `/review` audit** when: non-obvious bug fixes, new files/state files, changes to exchange_client/risk_manager/execution_agent, multiple deployments. Present report + suggested CLAUDE.md/memory updates. Do NOT auto-save.

### When discovering non-obvious behavior
4. **Suggest memory entry** for: exchange/API quirks, user corrections, surprising bugs. Draft and ask for confirmation.
