# Claimblad — Fase 0 + meetfundament (M1/M2)

*Datum: 2026-09-15 · Poort: A1 · Mijlpalen: M1 (gedeployed) en M2 (nog niet gedeployed)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft wat en welk bewijs.

## Wat er verandert

| Commit | Wat | Productie |
|---|---|---|
| `159df9f` | scorekaart: NaN-guard, weigering bij opslaan, alarm bij onvolledige meting, 16 dagen hersteld | GitHub Actions |
| `38d53da` | handelspijplijn uit via `subsystem_handelspijplijn_enabled`; monitor slaat pijplijnchecks over | gedeployed 18:11 UTC |
| `52d268c` | ShadowBasis achter schakelaar; controle-agent + claimblad-sjabloon | gedeployed 18:11 UTC |
| HEAD (lokaal) | `utils/flows.py`, `utils/kpi.py`, `utils/verliesbewaking.py` (Check 24), SleeveNAV telt broker mee, `config/experimenten.json`, `scripts/predeploy.py`, DD-limieten | nog niet |

Handmatige productie-ingrepen (in-place, md5 host = container geverifieerd):
- `config/auto_params.json`: `subsystem_handelspijplijn_enabled=false`, `subsystem_shadow_basis_enabled=false`
- `trade_log.json`: XYZ-INTC terug op OPEN (stond ten onrechte op GHOST_POSITION_SYNC sinds 08-13; positie 0.25 aantoonbaar open op 0xBd6c)
- `config/sleeves.json`: DD-limieten yield_core 1, basis 2, house 8

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Met de pijplijn uit blijft positiebeheer van open posities werken | Phase 3.5 in `main.py` leest `trade_log.json`, niet `active_setups`; na deploy: sleeve `last_updated` 18:13 UTC |
| 2 | Pijplijn uit geeft geen valse alarmen meer, en geen gemiste echte | `tests/test_swarm_monitor.py::test_pijplijn_uit_slaat_alleen_de_pijplijnchecks_over` |
| 3 | Check 12b mag aan blijven | leest alle gesloten trades incl. dip-koper (`_check_sustained_degradation`) |
| 4 | Een overboeking tussen potjes geeft geen vals verliesalarm | `tests/test_verliesbewaking.py::test_saldo_daling_na_flowcorrectie`, `::test_geld_onderweg_geeft_geen_oordeel_en_houdt_basislijn` |
| 5 | KPI-rendement is flow-gecorrigeerd en klopt | `tests/test_kpi.py::test_h1_h2_flowgecorrigeerd_met_de_hand` (met de hand uitgerekend) |
| 6 | Onmeetbaar wordt nooit nul | `kpi.bereken` weigert NaN; `SleeveNAV._tradfi_value` geeft None; verliesbewaking: 3 rondes onmeetbaar = alarm |
| 7 | Staat-bestanden driften niet | `scripts/predeploy.py` state-audit, `tests/test_predeploy.py::test_de_echte_repo_is_consistent` |
| 8 | Nieuwe statebestanden overleven een redeploy | `data/kpi.json`, `data/flows.json`, `data/verliesbewaking_state.json`, `data/oefening_actief.json` staan onder `./data` (gemount) |
| 9 | Geen enkele wijziging plaatst of sluit een order | verliesbewaking meldt kills alleen; pijplijnschakelaar schakelt instap uit |

## Raakt deze KPI's / poorten
- H1–H5 (definities in `utils/kpi.py`), alle drempels in `config/experimenten.json`.

## Risico en terugdraaien
- Grootste risico's: (a) vals alarm-spervuur via Check 24 (cooldown 6u/24u); (b) SleeveNAV-snapshot die dagen uitblijft als yfinance faalt voor de broker; (c) Check 20 alarmeert nu op 15% i.p.v. 20%.
- Geen geld direct op het spel.
- Terugdraaien: `git revert` + deploy; pijplijn: sleutel op true.

## Wat ik zelf niet heb gecontroleerd
- Het formaat van HL `userVaultEquities` bij een echte inleg (nu `[]`).
- Of de lijst "geld onderweg"-statussen in `utils/flows.py` volledig is voor alle proposal-types.
- Of `treasury_state.json.timestamp` UTC is (behandeld als UTC).
- De eerste KPI-run in productie.

---

## Audit
**Oordeel A1 ronde 1 (controle-agent, 13,2 min): GO-mits** — M1 blijft staan; M2 pas deployen na bevindingen 1–5. Geen blokkerende bevindingen (geen enkele wijziging plaatst orders).

## Reactie bouwer (ronde 1)

| # | Bevinding | Reactie |
|---|---|---|
| 1 | `nav._koers` zonder dropna/isfinite → broker stil als $0 | **Opgelost.** `dropna()` + `math.isfinite`; `SleeveNAV._tradfi_value` weigert NaN/fout-potjes. Toets: `tests/test_nav_koers.py` |
| 2 | Valse KILL na DEPLOY_YIELD vanaf HL (stroom geboekt ná het geld meetelt) | **Opgelost.** Elke yield_core-stroom (`ts > basislijn.ts`) of transit → geen saldo-oordeel, basislijn opnieuw; share-price-checks blijven oordelen. Toets: `test_geen_valse_kill_na_deploy_yield_race` (het auditscenario, incl. dat de bewaking daarna wél weer vuurt) |
| 3 | `BRIDGING_TO_HL`, `NEEDS_MANUAL_WITHDRAWAL`, FUND_TRADING ontbraken | **Opgelost.** Beide statussen in `ONDERWEG_STATUSSEN`; FUND_TRADING/COMPLETED = yield_core → swarm op `completed_at`. Toets: `test_fund_trading_en_alle_transitstatussen` |
| 4 | Stille nul bij RPC-fout → valse 100%-KILL | **Opgelost.** Protocol met eerder saldo > $1 dat nu 0 meldt zonder stroom → totaal onmeetbaar, basislijn blijft. Toets: `test_protocol_saldo_nul_na_rpc_fout_is_onmeetbaar` |
| 5 | Morpho share price dood (18 decimalen) | **Opgelost.** `convertToAssets(10**decimals)`; prijs 0 → onmeetbaar. Toets: `test_share_price_rekent_met_decimalen` |
| 6 | Experimentverlies twee definities (kpi H3 vs verliesbewaking) | **Open, bewust:** geen HLP-geld vóór M5; wordt één berekening in de HLP-module vóór de eerste inleg. Vastgelegd als voorwaarde M5 |
| 7 | DD-limieten in `sleeves.json` dubbel en niet flow-gecorrigeerd; Check 20-melding noemt 20% | **Opgelost.** Aanscherping teruggedraaid naar 3/5/20 (repo + host in-place, md5 gelijk); flow-gecorrigeerde bewaking zit alleen in Check 24. Check 20-melding toont de registerdrempel. Niet-flow-gecorrigeerde walletpiek van Check 20: bestaand gedrag, genoteerd |
| 8 | `market_regime.json` bevriest met pijplijn uit | **Geaccepteerd.** Raakt alleen het HL-margedoel van kasbeheer (nu $150); lage inzet. Opnieuw bekijken als de HL-trading-target ertoe gaat doen |
| 9 | KPI-kosten na 30 dagen + vandaag onvolledig | **Opgelost.** `kosten_per_dag` blijft in `kpi.json`; kosten tellen op de begindatum van het interval. Toets: `test_kosten_blijven_bewaard_als_cost_log_ze_kwijt_is`. Bijvangst via de pre-deploy-poort: een NaN op een dag zonder kosten glipte door → reeks wordt nu vooraf gescand (`test_nan_op_een_dag_zonder_kosten_wordt_ook_geweigerd`) |
| 10 | HLP niet gevonden → 0.0 | **Opgelost.** Onmeetbaar. Toets: `test_hlp_niet_gevonden_is_onmeetbaar` |
| 11 | Phase 3.4 uit bij pijplijn uit | **Geaccepteerd.** Alle open posities zijn van de dip-koper |
| open vraag | Fluid-wijzigingen in de werkmap | Apart A2-claimblad (STOP). Fluid staat nu **`automated: false`**, zodat de M2-deploy geen kapitaal verplaatst |
| open vraag | Stilval dip-koper niet meer bewaakt nu Check 18 overslaat | **Toegevoegd:** alarm als open dip-koper-posities > 180 min niet bijgewerkt (`dip_koper_max_stilstand_minuten` in het register). Toets: `test_dip_koper_stilstand` |
| open vraag | Wie boekt broker-stortingen/HLP-inleg in `data/flows.json` | Broker: `/boek-order` wordt uitgebreid met `utils.flows.boek_flow` (M2b). HLP: de module boekt zelf (M5) |
| open vraag | Kill-actie "switch naar ander protocol" bestaat niet | **Klopt.** Registertekst nu eerlijk: melden + handmatig opnemen; automatisch pas met een eigen A1/A2 |

Pre-deploy-poort na de fixes: **groen** (state-audit, syntax, 253 toetsen, pipeline).
