# Claimblad — kasbeheer: drie geldbugs + cap per protocol

*Datum: 2026-09-15 · Poort: **A1** (code die geld raakt) · Mijlpaal: M3-voorbereiding · Aanleiding: A2-audit op Fluid (STOP)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft wat en welk bewijs.

## Wat er verandert
- Commit: de laatste `fix(kasbeheer): …` na `d7dff82` (`git log --oneline -3`).
- Bestanden: `utils/treasury_executor.py`, `agents/treasury_agent.py`, `config/experimenten.json` (`globaal.max_aandeel_per_rendementsprotocol`), `tests/pre_flight/check_treasury.py`, `tests/test_treasury_rpc.py`, `tests/test_treasury_cap.py`.
- **Productie-impact vandaag:** naar verwachting geen gedragswijziging. Fluid staat op `automated: false` en Morpho valt onder de TVL-drempel, dus Aave is de enige automatische bestemming. De fixes worden pas actief bij een switch of diversificatie.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Een gedeeltelijke switch vanuit Aave neemt alleen `switch_amount_usd` op, naar beneden afgerond op centen | `advance_proposal`, YIELD_SWITCH-tak aave_v3; `check_treasury` case B2 (2490,137 saldo, deel 871,559 → opname 871,55) |
| 2 | Een volledige Aave-opname kan niet meer reverten door afronding | `withdraw_aave_to_wallet(..., volledig=True)` → `amount = 2**256-1`; `test_volledige_aave_opname_vraagt_uint256_max`; `check_treasury` "volledig=True" |
| 3 | Een revert in de dry-run stopt de transactie; een echte RPC-storing blijft "overslaan" | `_rpc` bewaart `json_fout`, `_simulate_tx` raiset bij "revert"/code 3; `test_revert_verdwijnt_niet_achter_een_transportfout`, `test_dry_run_stopt_bij_een_revert`, `test_dry_run_slaat_over_bij_een_echte_storing` |
| 4 | Na ≥ 2 mislukte deploys/switches in 24u maakt kasbeheer geen nieuwe deploy-voorstellen, op alle aanmaakplekken | `_deploy_geblokkeerd` in `run()` (generate + HL-excess) en `run_fast()` (generate + HL-excess); `test_deploys_geblokkeerd_na_twee_fouten_in_24u`, `test_oude_fouten_en_andere_types_tellen_niet` |
| 5 | Geen niet-benchmark-protocol boven 65% van het veilige potje via switch, diversificatie of nieuw geld | `_max_aandeel_per_protocol`, `_check_yield_switch` (gedeeltelijke switch), `_check_yield_diversification`, `_begrens_allocaties`; `check_treasury` cases H/I; `tests/test_treasury_cap.py` |
| 6 | Bij de cap verdwijnt geen geld | `_begrens_allocaties`: rest naar Aave, of blijft op de wallet als Aave niet beschikbaar is; `test_nieuw_geld_boven_de_cap_gaat_naar_de_benchmark` (som blijft 1000) |
| 7 | Pre-deploy-poort groen | `python scripts/predeploy.py`: state-audit, syntax, pytest, pipeline; `check_treasury` 132 passed |

## Raakt deze KPI's / poorten
- Veilig-integriteit (Check 24), H1/H2 (rente), M3-poort Fluid; `globaal.veilig_min_direct_opneembaar`.

## Risico en terugdraaien
- **Grootste risico's:**
  - `uint256.max` bij een Aave-pool die dat niet accepteert. Aave v3 ondersteunt het expliciet, maar het is in dit project nooit uitgevoerd.
  - Een revert-detectie op tekst ("revert") die bij een andere RPC anders geformuleerd is.
  - De retry-rem blokkeert ook een terecht nieuw deploy-voorstel tot 24u na twee fouten; daarna gaat het vanzelf weer.
  - `_parse_ts` + `utcnow()` tijdzone-gedrag.
- **Op het spel:** het veilige potje ($2.490) bij een switch of deploy; vandaag gebeurt die niet.
- **Terugdraaien:** `git revert` van deze commit + deploy.

## Wat ik zelf niet heb gecontroleerd
- Een `eth_call` met `uint256.max` op de echte Aave-pool voor het treasury-adres (read-only te simuleren).
- Of Tenderly bij een revert letterlijk "execution reverted" of code 3 teruggeeft (de audit gaf error `0x47bc4b2c`; tekst onbekend).
- Of `_parse_ts` naive ISO-tijden hetzelfde behandelt als `datetime.utcnow().timestamp()` (lokale-tijdzonevalkuil).
- Of er naast `run`/`run_fast`/HL-excess nog een plek is die DEPLOY_YIELD of YIELD_SWITCH aanmaakt.

---

## Audit
*(in te vullen door de controle-agent)*

## Reactie bouwer
