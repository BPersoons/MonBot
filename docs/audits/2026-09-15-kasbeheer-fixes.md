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
**Oordeel A1 ronde 1 (controle-agent, 10 min): STOP.** Niets hiervan was gedeployed.

## Reactie bouwer (ronde 1)

| # | Bevinding | Reactie |
|---|---|---|
| 1 | Revert nog steeds verstopt: ankr geeft na Tenderly een JSON-fout "Unauthorized" die de revert verdringt | **Opgelost.** `_rpc` raiset een revert (`_is_revert`) direct en probeert daarna geen andere RPC's. Andere JSON-fouten worden onthouden. Toetsen: `test_echte_rpc_volgorde_revert_wint_van_een_latere_json_fout` (Tenderly revert → ankr Unauthorized → 403 → 403), `test_json_fout_eerst_en_dan_revert_geeft_ook_de_revert` |
| 2 | Naïeve fix laat elke storting mislukken: dry-run vóór de approve revert altijd op de allowance (werkte alleen doordat de revert werd ingeslikt) | **Opgelost.** Dry-run verplaatst naar ná approve + allowance-check in `_deposit_aave`, `_deposit_erc4626` en `_deposit_compound_v3`, binnen het try-blok. Een revert trekt de approve weer in en verstuurt geen supply. Toetsen: `test_deposit_dry_run_komt_na_de_approve`, `test_revert_in_dry_run_trekt_de_approve_in_en_stort_niet` |
| 3 | Cap werkt niet in `run_fast` (geen `yield_balances`) | **Opgelost.** `generate_proposals` leest zelf strikte on-chain saldi (`_strikte_yield_saldi` → `verliesbewaking._saldi_onchain`), los van de caller. Toets: `test_cap_op_nieuw_geld_gebruikt_strikte_saldi_ook_zonder_yield_balances` |
| 4 | `_check_hl_excess` zonder cap | **Opgelost.** Past het overschot niet onder de cap, dan gaat het naar de benchmark; zonder benchmark wordt het tot de ruimte verkleind of overgeslagen. **Bijvangst:** `protocol_id`/`protocol_type` kwamen uit `best.get("id"/"type")`, maar een opportunity heeft die velden niet → HL-overschot werd altijd als `aave_v3` gerouteerd. Nu uit `protocol_config` |
| 5 | Retry-rem remt geen switches | **Opgelost.** `_switch_en_diversificatie` zet beide checks achter `_deploy_geblokkeerd`, gebruikt in `run()` en `run_fast()`. Aansluitingstoets: `test_rem_zit_voor_switch_diversificatie_hl_excess_en_deploy_in_run_fast` |
| 6 | Cap leunt op stille nullen | **Opgelost.** Cap gebruikt overal strikte saldi; onleesbaar → geen beweging naar een niet-benchmark (switch/diversificatie overslaan, nieuw geld naar de benchmark). Toets: `test_onleesbare_saldi_sturen_nieuw_geld_naar_de_benchmark` |
| 7 | Gasmarge volledige opname | **Opgelost.** Aave-withdraw gebruikt `_estimate_gas(..., _GAS_WITHDRAW)` |
| 8 | Toetsen dekken aansluiting niet | **Opgelost** voor de rem in `run_fast` (zie 5) en de cap in de fast-route (zie 3) |
| open vraag | Rem ook op switches? | Ja — zie 5 |
| open vraag | Dry-run met state-override of ná de approve? | Ná de approve: eenvoudig en toetsbaar; kost bij een revert alleen de approve- en revoke-gas |
| bijvangst | Pre-flight | `check_treasury` gebruikt case-saldi als strikte saldi (geen netwerk), en case F accepteert de helper mits die beide checks én de rem aanroept |

**Oordeel A1 ronde 2 (controle-agent, 9,2 min): GO-mits.** Voorwaarde vóór deploy: een aansluitingstoets voor de rem in `run()`. Voorwaarden vóór M3: geld onderweg bij de cap, en volgordetoetsen voor erc4626.

## Reactie bouwer (ronde 2)

| # | Bevinding | Reactie |
|---|---|---|
| 1 | Rem in `run()` niet getoetst (voorwaarde deploy) | **Opgelost.** `test_rem_zit_voor_switch_diversificatie_hl_excess_en_deploy_in_run`: met 2 fouten in 24u worden switch, diversificatie, HL-excess en generate niet aangeroepen; zonder fouten wel |
| 2 | Cap telt geld onderweg niet (voorwaarde M3) | **Opgelost door uitsluiten, niet door optellen.** Geen HL-overschot tijdens een YIELD_SWITCH APPROVED/SWITCHING (`_check_hl_excess`); geen switch of diversificatie zolang een DEPLOY_YIELD onderweg is (`_DEPLOY_ONDERWEG`). Samen met de bestaande guards (geen generate tijdens DEPLOY_YIELD in-flight of SWITCHING) is er nooit meer dan één beweging naar yield tegelijk. Toetsen met positieve controle: `test_geen_switch_zolang_een_deploy_onderweg_is`, `test_geen_diversificatie_zolang_een_deploy_onderweg_is`, `test_geen_hl_overschot_zolang_een_switch_loopt`. Mutatietoets: met `_DEPLOY_ONDERWEG = set()` falen de eerste twee |
| 3 | erc4626-volgorde ongetoetst (voorwaarde M3) | **Opgelost.** `test_erc4626_dry_run_komt_na_de_approve`, `test_erc4626_revert_in_dry_run_trekt_de_approve_in_en_stort_niet` |
| 4 | Dode `_check_treasury_wallet_usdc` | **Verwijderd** (geen aanroepers; grep over de repo) |
| 5 | Approve kan blijven hangen bij allowance mismatch | Niet gewijzigd: geen geldrisico (USDC blijft op de wallet, allowance naar een geverifieerd contract); staat op de lijst |
| open vraag | Geld onderweg meetellen of uitsluiten? | Uitsluiten — eenvoudiger, toetsbaar, en de kosten (een switch wacht een bridge van minuten af) zijn verwaarloosbaar |
