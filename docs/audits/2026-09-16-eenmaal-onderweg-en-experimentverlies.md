# Claimblad — één beweging tegelijk, verlopen opname, en één definitie van experimentverlies

*Datum: 2026-09-16 · Poort: **A1** (code die geld raakt) · Mijlpaal: voorwaarden vóór M3 (Fluid) en M5 (HLP)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft wat er verandert en welk bewijs er is.

## Wat er verandert
- Vervolg op `108e912` (gedeployed 2026-09-15 ~21:10 UTC). Deze commit is de volgende `fix(kasbeheer)`/`fix(meting)` — zie `git log --oneline -3`.
- Bestanden: `agents/treasury_agent.py`, `utils/treasury_executor.py`, `agents/swarm_monitor.py`, `utils/experimenten.py` (nieuw), `utils/kpi.py`, `utils/verliesbewaking.py`, `config/experimenten.json`, `scripts/verify_live.py`, toetsen.
- **Productie-impact vandaag:** kasbeheer doet vandaag geen bewegingen (Fluid `automated: false`, Morpho onder de TVL-drempel, geen lopende voorstellen). De meetwijziging is wél direct zichtbaar: H3 gaat van $1.087,80 naar $0,00.

## Aanleiding
1. Hertoets van 15-09 (bevindingen 1 en 2): `run_fast` kon een switch en een deploy in dezelfde ronde maken, en een DEPLOY_YIELD in NEEDS_MANUAL_WITHDRAWAL blokkeerde alles stil en zonder einde.
2. **Gevonden in productie op 16-09:** `data/kpi.json` meldde H3 = **$1.087,80** experimentverlies voor `hlp_vault`, terwijl HLP niet bestaat en er geen dollar in zit. Oorzaak: het experiment wijst naar potje `house` (de bestaande HL-rekening) en `kpi.py` telde de hele historie van dat potje. `verliesbewaking.py` rekende het anders (inleg − equity uit `hlp_sleeve_state.json`) en kwam op $0. Dat was al bekend als "voorwaarde vóór M5" en blijkt nu ook een verkeerde KPI te hebben opgeleverd.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Kasbeheer maakt nooit twee bewegingen naar/tussen rendementsprotocollen tegelijk, op álle vijf aanmaakplekken | `_yield_beweging_onderweg` (één definitie) in `generate`-guard van `run` én `run_fast`, `_check_hl_excess`, `_check_yield_switch`, `_check_yield_diversification`; `test_run_fast_geen_deploy_in_de_ronde_waarin_een_switch_ontstaat`, `test_geen_switch_zolang_een_deploy_onderweg_is`, `test_geen_diversificatie_zolang_een_deploy_onderweg_is`, `test_geen_hl_overschot_zolang_een_switch_loopt` |
| 2 | Een APPROVED-switch telt als onderweg (dat was de fout van gisteren) | `_SWITCH_ONDERWEG = {"APPROVED", "SWITCHING"}`; mutatietoets: met de oude regel (alleen SWITCHING) én met geen regel faalt de `run_fast`-toets |
| 3 | Een handmatige HL-opname verloopt na 48 uur naar EXPIRED en leest het saldo dan niet meer | `_MANUAL_WITHDRAWAL_TTL_H`, `manual_withdrawal_since`; `tests/test_treasury_manual_withdrawal.py` (verlopen, binnen 48u door, oud voorstel zonder veld, WITHDRAWING verloopt niet, onleesbare tijd verloopt niet) |
| 4 | Een vastgelopen handmatige opname is zichtbaar | `swarm_monitor.py` Check 14 kent NEEDS_MANUAL_WITHDRAWAL (> 6u → Telegram); `test_monitor_meldt_een_hangende_handmatige_opname` |
| 5 | EXPIRED is eindstatus: geen executor-set, geen onderweg-set, geen rem-teller | `active`-sets in `execute_approved_proposals`/`run_fast`, `_DEPLOY_ONDERWEG`, `flows.ONDERWEG_STATUSSEN`, `_deploy_geblokkeerd` (telt FAILED) |
| 6 | Eén definitie van experimentverlies, gedeeld door H3 en het verliesbudget | `utils/experimenten.py`: `telt_mee_voor_budget` (status live **én** `verliesbudget_telt_mee`) en `verlies_usd(inleg_netto, waarde)`; gebruikt in `kpi.py` H3 en `verliesbewaking.evalueer` |
| 7 | Verlies wordt gemeten vanaf de start van het experiment, niet vanaf het begin van de reeks | `verlies_meten_vanaf` in het register; `test_h3_meet_pas_vanaf_de_startdatum_van_het_experiment`, `test_h3_telt_een_experiment_dat_nog_niet_leeft_niet_mee` |
| 8 | Onmeetbaar blijft onmeetbaar | `verlies_usd` geeft None bij None/NaN; H3 zet dan `experimentverlies:<naam>` in de H5-lijst in plaats van $0 |
| 9 | De valse FAIL van `verify_live` is weg zonder een echte spookpositie te verbergen | `_phantoms` sluit alleen dip-koper-trades uit (eigen wallet `0xBd6c`); harvest-trades draaien op de hoofdwallet en blijven getoetst |
| 10 | Pre-deploy-poort groen | `python scripts/predeploy.py`: state-audit, syntax, pytest, pipeline; `check_treasury` 132 passed |

## Raakt deze KPI's / poorten
- H3 (verliesbudget $250 / alarm $125), H5 (onmeetbaar), Check 24 budget-kill, M3-cap per protocol, M5-voorwaarde voor HLP-inleg.

## Risico en terugdraaien
- **Grootste risico's:**
  - De strengere regel kan een terechte beweging uitstellen: zolang een DEPLOY_YIELD of switch onderweg is, gebeurt er niets anders. Kosten: gemiste spread, orde van grootte $37/jaar op $2.490 bij 1,5pp.
  - `telt_mee_voor_budget` eist nu `status == "live"`. Zet ik dat bij het live gaan van HLP niet om, dan bewaakt het budget **niets** — een stille nul in de andere richting. Vastgelegd in `voorwaarde_voor_inleg` en in het besluitenlog.
  - 48 uur kan te kort zijn voor een echte handmatige opname in een weekend.
  - `verlies_meten_vanaf` is handmatig; een verkeerde datum verschuift de meting.
- **Op het spel:** vandaag niets (geen bewegingen, geen HLP). Vanaf M3/M5: het veilige potje ($2.490) en de HLP-inleg ($500).
- **Terugdraaien:** `git revert` van deze commit + deploy; `kpi.json` herberekent zichzelf de volgende dag.

## Wat ik zelf niet heb gecontroleerd
- Of `_uren_sinds` op de VM (UTC) hetzelfde oordeelt als lokaal — de tijdzone-valkuil van `_parse_ts`.
- Of een oud voorstel in productie een `updated_at` heeft dat later is bijgewerkt dan het moment van NEEDS_MANUAL_WITHDRAWAL (dan verloopt hij later dan 48u na de echte start).
- Of er naast H3 en het verliesbudget nog een derde plek is die "experimentverlies" berekent.
- De historische regel in `data/kpi.json` met H3 = $1.087,80 blijft staan tot de volgende dagelijkse berekening; ik heb nog niet bepaald of die herschreven moet worden.
