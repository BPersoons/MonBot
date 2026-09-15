# Strategiehistorie van de handelsbot

> Letterlijk verplaatst uit CLAUDE.md op 2026-09-15 (S3: CLAUDE.md afslanken). De inhoud hieronder is niet herschreven; correcties die sindsdien gelden staan in dit kader.
> 
> - **De handelspijplijn staat UIT sinds 2026-09-15** (`subsystem_handelspijplijn_enabled=false`), bovenop de pauze van 2026-08-10 (`score_threshold` 0,40, armed-gate aan). Richting voorspellen is weerlegd; zie `docs/PLAN_2026-08.md` en `docs/besluiten.md`.
> - ⚠️ FOUT hieronder: "Pauzeren = veilige stand: `armed_mode_enabled=False` + `score_threshold` hoog". `armed_mode_enabled=False` OPENT de funnel. Pauzeren = drempel 0,40 mét de armed-gate AAN.
> - Het +44%-ijkpunt is NIET het live-systeem (F0-diagnose: −153% op een getrouwe harness).

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
