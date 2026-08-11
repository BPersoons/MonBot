# Directional Core Redesign

**Status:** ontwerp (G0) — ter review
**Datum:** 2026-07-21
**Auteur:** swarm-onderhoud (n.a.v. Bart's kern-eis: "de juiste trades op het juiste moment, en flag het als dat niet zo is")

---

## 1. Aanleiding (live data)

Op 2026-07-21 waren **26 van de 26** gesloten trades SHORT, in een bevestigde
`TRENDING_BULL` (ADX 31+, BTC BULLISH). WR 34.6%, netto **−$32.83** — vrijwel
uitsluitend counter-trend squeezes (KBONK −$26/−$14, SKHX −$11, WLD −$7).

De funnel opende dus systematisch shorts tegen de trend in. Dat is geen
analyse-fout van een enkele agent; het is een **structurele richting-scheefstand**
die uit de architectuur volgt. Er staat nu een tijdelijke `BULL_SHORT_STOP`
(interim gate in `project_lead.py`) die het bloeden stelpt. Dit document beschrijft
de definitieve vervanging.

---

## 2. Volledige inventarisatie — waar richting & threshold worden aangeraakt

De richting-beslissing is verspreid over **vier onafhankelijke subsystemen** die
elkaar niet kennen. Elk heeft een eigen, deels tegenstrijdige logica.

### A. Richting-*selectie* — `agents/research_agent.py`
| Regel | Wat | Probleem |
|---|---|---|
| ~368–380 | `best_direction` = LONG/SHORT op basis van recente **mini-backtest PnL**; flipt naar SHORT zodra `pnl_short > pnl_long and trades_short >= 2` | Recency-chasing: in een bull met pullbacks scoort de short-backtest op de terugval → kiest SHORT. Lage drempel (2 trades). |
| ~382–395 | Macro-override: forceer SHORT in `TRENDING_BEAR` | **Asymmetrisch** — er is geen symmetrische "forceer LONG in TRENDING_BULL". |
| ~455–480 | Sentiment-breakout → LONG, breakdown → SHORT | Onafhankelijk richting-pad, geen regime-check. |
| ~199–236 | Mean-reversion RSI/BB → LONG/SHORT | Idem, apart pad. |
| ~140–177 | Pullback-validatie richting | Idem. |

### B. Threshold-*manipulatie* — `agents/project_lead.py`
| Regel | Wat | Probleem |
|---|---|---|
| 83–92 | `_get_score_threshold()` — basis (auto-param 0.20, fallback 0.40) | ok |
| 236–243 | `_REGIME_THRESHOLD_MULT` — regime-scalar op threshold | Laag 1 van de stapel |
| 256–269 | `_DEFAULT_REGIME_DIR_MULTIPLIERS` — regime×richting bootstrap-tabel | Laag 2 |
| 109–186 | `_load_regime_dir_multipliers()` — shadow-gevoede herberekening met **handmatige overrides** (r.155/166/175) | Zelf-corrigerend bedoeld, maar traag (n≥15) en al 3× handmatig geplakt |
| 527–530 | `threshold = basis × regime_mult × rd_mult × (0.60 als SHORT)` | **De stapel** — vier vermenigvuldigingen op één drempel |
| 543 | Interim `BULL_SHORT_STOP` | Tijdelijk, moet weg met deze redesign |
| 597–598 | LLM-beslisbanden afgeleid van `_effective_threshold` | Erft de hele stapel |
| 912–938 | `SETUP_MIN_CONVICTION` per timeframe × **0.60 SHORT-korting** (opnieuw) | Tweede, aparte SHORT-korting |

### C. Signaal-*weging* per richting/regime — `agents/project_lead.py`
| Regel | Wat |
|---|---|
| 190–207 | `_determine_strategic_weights` — SHORT krijgt TA-dominante weging 0.60/0.20/0.20 |
| 424–433 | `_regime_boost` — signaal-multipliers per regime |
| 441–451 | SHORT sluit FA/SA uit, inverteert macro-vibe |
| 470–511 | RANGING SA/FA-poorten |

### D. Risk-laag — `agents/risk_manager.py`
| Regel | Wat |
|---|---|
| 427–436 | `MACRO_GATE` — nu observability-only (was hard block, botste met shadow-data) |
| 440–451 | FA/SA short-logica |
| 495–503 | Blok op gecorreleerde same-direction exposure |

**Kernobservatie:** de richting wordt op ~8 plekken over 3 bestanden aangeraakt.
Geen enkele plek heeft het volledige beeld. De threshold alleen al draagt **vijf**
richting/regime-correcties (regime-mult, rd-mult, ×0.60 in gate 1, ×0.60 in
conviction-gate, interim stop). Elke correctie is ooit toegevoegd om het symptoom
van een vorige te dempen. Dat is de definitie van niet-corrigeerbaar pleisterwerk
— en het staat al drie keer in `CLAUDE.md` als faalpatroon (EXP-002, "one gate
system per dimension", auditor self-tightening).

---

## 3. Ontwerpprincipe

> **Kies geen richting om die daarna te rechtvaardigen. Produceer één
> regime-bewuste, signed conviction-score. Het teken ís de richting; de grootte
> passeert één symmetrische drempel.**

Concreet betekent dat:
1. **Richting-edge zit IN de score**, niet in post-hoc drempelkorting. Trend-volgend
   krijgt amplitude, counter-trend wordt gedempt — symmetrisch voor long en short.
2. **Eén threshold**, gelijk voor beide richtingen. Geen ×0.60. Geen regime×richting
   multiplier-tabel. Een short die in een bull niet door de lat komt, hoort er niet
   te komen — dat is correct gedrag, geen bug om weg te compenseren.
3. **Een supervisor die scheefstand flagt** vóórdat het geld kost — Bart's expliciete eis.

---

## 4. Doelarchitectuur

### Laag 1 — Regime-correct signaal (de edge) — **OPTIE B, gekozen 2026-07-21**

**Beslissing:** neem de al-bewezen, regime-bewuste discrete signaalfuncties
`signal_crypto` / `signal_tech` / `signal_commodities` (nu in
`scripts/strategy_final.py`, backtest +44% in maart-mei, +15pp vs baseline op
huidige 60d data) rechtstreeks als **richtingsbron** van laag 1. Ze zijn
regime-bewust *by construction* (EMA200-gate + asset-klasse-specifieke
richtingsregels) — precies de discipline die we willen. Geen continue
`regime_alignment`-factor meer nodig; die was een retrofit op de oude continue
architectuur en vervalt.

```
direction, base_rule = signal_for_asset(asset_class, df, i)   # -1 / 0 / +1
magnitude            = |continue TA-composite|                # voor sizing + kwaliteitslat
GO als direction != 0 en magnitude >= threshold               # één threshold, beide richtingen
```

- **Richting** = de discrete regel (−1/0/+1). Geen `best_direction` mini-backtest
  meer, geen force-SHORT override.
- **Magnitude/conviction** = de continue TA-composite (voor sizing en een
  kwaliteitsdrempel). FA/SA mogen magnitude moduleren, nooit richting
  (behoudt de LONG-only SA-edge; zie `feedback_sa_already_degraded`).
- **Eén threshold** voor beide richtingen. Geen ×0.60, geen regime×richting-tabel.

**Waarom niet de continue alignment-factor (Optie A):** de shadow_book (die zo'n
factor zou voeden) is bewezen onbetrouwbaar voor richting (overwaardeert shorts —
zie §1a), en het +44%-harnas heeft geen threshold/alignment-knop om tegen te
kalibreren. De discrete regels wérken al en zijn interpreteerbaar; ze adopteren is
lager risico dan een continue benadering ervan tunen.

**Wat verdwijnt:** `_REGIME_THRESHOLD_MULT`, `_DEFAULT_REGIME_DIR_MULTIPLIERS`,
`_load_regime_dir_multipliers`, beide ×0.60 SHORT-kortingen, de research_agent
mini-backtest direction-picker + force-SHORT override, de interim
`BULL_SHORT_STOP`, en de (nooit gebruikte) `regime_alignment`-factor uit G1.

### Laag 2 — Supervisor (het vangnet)

Nieuwe `SwarmMonitor` **Check 19: Directional pathology** (past in het bestaande
`_safe_check`-patroon, 18 checks al aanwezig). Draait elke monitor-ronde:

1. **Eenzijdigheid** — laatste N (=8) uitgevoerde trades allemaal dezelfde richting
   → WARNING. (Had de −$33 na ~trade 5 gevlagd, niet na 26.)
2. **Richting-vs-regime mismatch** — >X% (=70%) van open/recente trades tegen de
   BTC-regime in → WARNING, optioneel auto-halt op die richting tot review.
3. **Realized-vs-shadow divergentie** — als de live WR van een (regime,richting)-cel
   structureel onder de shadow-voorspelling zakt (bijv. >15pp over n≥10) → flag:
   "het model liegt over deze cel".

Output: Telegram-alert + een leesbare regel in het P&L-digest, zodat Bart het ziet.
Auto-halt is opt-in per check (default: alleen flaggen, niet blokkeren — één
gate-systeem per dimensie, geen stille harde blokkade bovenop laag 1).

---

## 5. Wat dit expliciet NIET doet

- Geen nieuwe multiplier bovenop de bestaande. Het **verwijdert** de stapel.
- Geen "doe het omgekeerde van de agents". De agents zijn niet anti-predictief;
  ze werden alleen eenzijdig door de architectuur geduwd. Inverteren zou in de
  volgende bear-fase juist opblazen.
- Geen handmatige per-cel tuning. Kalibratie is één keer, via backtest, als geheel.

---

## 6. Validatie-eis (verplicht vóór cutover)

De symmetrische één-threshold variant moet bewijzen dat hij niet slechter is dan
het ijkpunt vóór hij live gaat:

1. **Backtest tegen het ijkpunt** (`scripts/strategy_*.py`, 60d, 18 HL-tickers,
   2026-03/05). Baseline = +44.2%. Nieuwe variant moet **≥ baseline** halen, per
   asset-klasse gerapporteerd.
2. **Replay van recente live shadow-decisions** (`shadow_report.json` /
   `decision_history.json`): zou de nieuwe score de 26 verlieslatende shorts hebben
   geweigerd én winstgevende trades hebben behouden?
3. **Supervisor droog getest**: zou Check 19 de scheefstand van 07-21 hebben
   geflagd, en géén valse alarmen in gezonde periodes.

---

## 7. Migratie — poorten (geen datums)

| Poort | Inhoud | Klaar wanneer |
|---|---|---|
| **G0** | Inventarisatie + dit ontwerp | ✅ **klaar** |
| **G1** | Laag-1 signed score gebouwd in **shadow/parallel** modus (alleen loggen, geen gedragswijziging); vergelijk N dagen tegen live beslissingen | ✅ **klaar & draait** — `utils/directional_core_shadow.py` + `scripts/analyze_directional_shadow.py`. Vroege observatie: ×0.70 counter-trend demping te mild (ADA/CASHCAT klaren de drempel als counter-trend short) → strak kalibreren in G3 |
| **G2** | Supervisor Check 21 live in **flag-only** modus (eenzijdigheid + richting-vs-regime mismatch) | ✅ **klaar & live** — `swarm_monitor.py` Check 21; geverifieerd tegen de 26-shorts data (beide signalen vuren) |
| **G3** (Optie B) | **G3a** ✅: `core/directional_signals.py` + tests (bit-identiek geport). **G3b** ✅ GEDEPLOYED 2026-07-21: `_rule_direction()` autoritatieve richting via `get_ohlcv_df()`; multiplier-stapel/×0.60(2×)/force-SHORT/interim-stop verwijderd; symmetrische drempel. **G3c** ✅ gedekt via historische validatie (`validate_rule_direction.py`: alle 26 verliesshorts → NONE, +$32.83) + strategy_final +15pp. | ✅ prod HTTP 200, RULE_NO_SETUP/RULE_DIR live, 0 tracebacks |
| **G4** | ✅ GEDEPLOYED 2026-07-21: G1-shadow (`directional_core_shadow.py`) + `analyze_directional_shadow.py` verwijderd, `_load_regime_dir_multipliers`/`_DEFAULT_REGIME_DIR_MULTIPLIERS`/`_regime_dir_multipliers`/`_SHADOW_MIN_SAMPLES` weg. `CLAUDE.md` + memory bijgewerkt met dated breuklijn. | ✅ Repo schoon, HTTP 200 |

### §1a — Reconciliatie-bevinding (G3 stap 1, 2026-07-21)
Realized (Supabase maart n=19 bull-longs +$34.59 / n=2 bull-shorts −$3.58) én de live
juli-data (26 bull-shorts −$33) zeggen béide: **in een bull werkt LONG, verliest SHORT.**
De shadow_book zegt het omgekeerde (bull-short +0.37, bull-long −0.07) → **shadow_book
overwaardeert shorts systematisch** (meetartefact van vaste 4.5% TP/24u exit). Conclusie:
shadow_book uitgesloten als richting-kalibratiebron; trend-volgen is directioneel correct;
kalibreer/valideer op het 60d OHLCV-harnas. Los issue genoteerd: Supabase closed-trade
sync stopte ~half maart (realized ground-truth is dun). Script:
`scripts/reconcile_shadow_vs_realized.py`.

Elke poort is afzonderlijk reverteerbaar. De interim `BULL_SHORT_STOP` blijft staan
tot en met G2 en wordt pas in G3 verwijderd.

---

## 8. Beslissingen (vastgelegd 2026-07-21)

1. **Supervisor bij richting-vs-regime mismatch: alleen flaggen.** Telegram-alert +
   regel in P&L-digest, géén automatische blokkade. Bewust geen tweede harde gate
   bovenop laag 1 — dat is het "one gate system per dimension"-faalpatroon. Bart
   beslist per geval of hij ingrijpt.
2. **regime_alignment startwaarden: backtest bepaalt ze.** ×1.15/×0.70/×0.85 zijn
   placeholders; §6-backtest kalibreert ze als geheel tegen het +44% ijkpunt. Geen
   handmatige per-cel tuning.
3. **RANGING: beide richtingen, neutraal (×1.0).** Geen trend om te volgen → geen
   versterking/demping. Mean-reversion long én short toegestaan, kwaliteit geborgd
   door de normale symmetrische threshold. Sluit aan bij live data (mean-rev LONG
   WR 51%).
```
