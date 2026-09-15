# Runtime-statebestanden

> Letterlijk verplaatst uit CLAUDE.md op 2026-09-15 (S3: CLAUDE.md afslanken). De inhoud hieronder is niet herschreven; correcties die sindsdien gelden staan in dit kader.
> 
> - De pre-deploy-poort `python scripts/predeploy.py` controleert nu automatisch dat compose-mounts en `STATE_FILES` gelijk lopen (in beide richtingen); die toets draait ook in pytest.
> - Nieuw sinds 2026-09-15, onder de gemounte map `data/`: `data/kpi.json` (KPI's H1-H5), `data/flows.json` (handmatige kapitaalstromen), `data/verliesbewaking_state.json` (Check 24), `data/oefening_actief.json` (brandoefening-vlag), naast het al bestaande `data/sleeve_nav.json`.
> - `config/experimenten.json` (drempels) zit bewust in de IMAGE, niet gemount: een drempel wijzigen loopt via audit en deploy.

## Runtime State Files (root dir, JSON)

Sinds 2026-07-06 zijn álle leer- en positie-statebestanden volume-mounted in `docker-compose.prod.yml` (shadow_book/report, shadow_basis_*, ticker_state, decision_history, treasury_harvest/proposals, audited_trades, portfolio_peak, cost_log, polymarket_shadow_log, config/treasury_allocation) — ze overleven een full redeploy. `deploy_update.sh` stap 2b migreert container-state eenmalig naar de host vóór de stop; de `STATE_FILES`-lijst daar moet synchroon blijven met de compose-mounts. Nieuwe statebestanden die een redeploy moeten overleven: voeg toe aan BEIDE.

> **Een hand-onderhouden `config/*.json` heeft VIER plekken, niet twee** (geleerd bij `config/broker_holdings.json`, 2026-08-20). Naast (1) de compose-mount en (2) de backup-lus in `deploy_update.sh` moet hij ook in (3) de **seeding-lus** (`for cfg in conviction_core barbell_targets broker_holdings`) en (4) de **`chmod 666`-regel** daaronder. Punt 3 is de gevaarlijke: staat het bestand niet op de host wanneer `docker-compose up` draait, dan maakt Docker een **map** van de mount-bestemming en faalt elke `json.load` erop. De seeding-lus haalt hem uit de image — daarom moet zo'n configbestand óók in git staan. Onderscheid: runtime-**state** hoort in `STATE_FILES` (mag leeg getouched worden), hand-onderhouden **config** hoort in de seeding-lus (mag dat juist nóóit, dan zijn de instellingen weg).

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
