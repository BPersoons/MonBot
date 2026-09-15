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
*(in te vullen door de controle-agent)*

## Reactie bouwer
