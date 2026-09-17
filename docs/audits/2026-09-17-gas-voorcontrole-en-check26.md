# Claimblad — REBALANCE-voorcontrole op de hele keten + monitor Check 26 (ETH voor gas)

*Datum: 2026-09-17 · Poort: A1 (deploy van code die geld raakt) · Mijlpaal: M3 (voorwaarden uit de A2-audit gasbijvulling van 16-09)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert

Niets hiervan is nog gecommit; zie `git diff` op de twee productiebestanden.

**`utils/treasury_executor.py`** (geldcode)
- Nieuw: `_rebalance_kan_afmaken(treasury_pk)`. Deze functie wordt aangeroepen in de REBALANCE-tak van `APPROVED`, **vóór** `withdraw_aave_to_wallet`. Hij gooit een fout (en er wordt dus niets opgenomen) in vier gevallen:
  1. er is geen vault-sleutel;
  2. het adres van de vault-sleutel is niet `_vault_adres()`, of `_vault_adres()` is onbekend;
  3. het ETH-saldo van de treasury of de vault is onleesbaar;
  4. de treasury heeft minder dan `_MIN_ETH_FOR_GAS + 2 × 2 × 3,9e-6` (0,0001156), of de vault minder dan `_MIN_ETH_FOR_GAS + 2 × 1,7e-6` (0,0001034).
- De fout valt in de bestaande `except`. Het gevolg is `FAILED` met de foutmelding, een Telegram-bericht "Aave withdrawal mislukt: …" en **geen** `aave_withdrawn_at`.
- Nieuw in `_bridge_usdc_to_hl`: dezelfde adrescontrole op de vault-sleutel, vóór elke transactie. Die is nodig voor voorstellen die al in `BRIDGE_BACK_NEEDED` staan.
- Nieuwe constanten: `_GAS_KOSTEN_AAVE_ETH`, `_GAS_KOSTEN_BRIDGE_ETH`, `_GAS_MARGE_FACTOR`.

**`agents/swarm_monitor.py`** — Check 26 `_check_eth_gas` (alleen melden)
- Meet hooguit één keer per uur het ETH-saldo van de treasury (`_TREASURY_WALLET`) en de vault (`_vault_adres()`).
- Waarschuwt als er **minder dan 15 transacties** over zijn tot `_MIN_ETH_FOR_GAS`. Daarbij rekent hij per transactie 3,9e-6 ETH voor de treasury en 1,7e-6 voor de vault.
- Een nieuwe melding volgt pas na 72 u, of nadat het saldo eerst boven 15 × 1,5 transacties is uitgekomen (hysterese).
- De stempel komt er alleen als `_send_telegram` True teruggeeft. Een onleesbaar saldo geeft alleen een logregel en laat de staat staan.
- De tekst verschilt per wallet:
  - treasury: bijvullen kan intern via `stuur_eth_voor_gas` (A2);
  - vault: nieuw ETH is nodig, dus een besluit van Bart.

**Toetsen**
- Nieuw: `tests/test_rebalance_voorcontrole.py` (13) en `tests/test_eth_gas_check.py` (15).

**Productie-impact**
- Een REBALANCE start alleen nog als de hele keten kan afmaken.
- Bart krijgt hoogstens één gasmelding per wallet per 3 dagen.

## Beweringen

| # | Bewering | Bewijs |
|---|---|---|
| G1 | Tot nu toe bleek een gastekort op de vault pas ná de Aave-opname. | `utils/treasury_executor.py`: in de REBALANCE-tak van `APPROVED` kijkt `withdraw_aave_to_wallet` alleen naar de treasury (`_check_eth_gas(to_address)`). De vault wordt pas gecontroleerd in `_bridge_usdc_to_hl` (`_check_eth_gas(vault_arb)`), en die draait in `BRIDGE_BACK_NEEDED`, dus ná `aave_withdrawn_at`. Zie ook de audit `2026-09-16-gas-bijvullen.md` (M3-voorwaarde) en `docs/PLAN_2026-08.md` M3. |
| G2 | Ook de treasury kon halverwege stoppen. De opname slaagt al bij ≥ 0,0001 ETH, maar de overboeking naar de vault (stap 1 van de bridge) vraagt nog een transactie. | `_bridge_usdc_to_hl`, stap 1: `_check_eth_gas(treasury)` vóór `_send_tx(... _GAS_TRANSFER)`. Toets: `test_treasury_met_gas_voor_een_stap_maar_niet_voor_de_keten`. |
| G3 | `get_vault_private_key()` valt terug op `HL_PRIVATE_KEY`, de sleutel van de agent-wallet (een ander HL-account). HL schrijft een bridge-storting bij op de afzender, dus zonder vault-sleutel zou het geld op het verkeerde account landen. | `utils/treasury_executor.py`, `get_vault_private_key`: `for secret_name in ("HL_VAULT_PRIVATE_KEY", "HL_PRIVATE_KEY")`. `reference_hl_bridge_abi` / de docstring van `_bridge_usdc_to_hl`: "HL credits vault_arb_address". CLAUDE.md: `HL_WALLET_ADDRESS` / `HL_PRIVATE_KEY` = agent-wallet. |
| G4 | De grenzen passen bij de stand van na de bijvulling van vanavond. Treasury 0,000474 ≥ 0,0001156 en vault 0,000147 ≥ 0,0001034, dus een REBALANCE blijft mogelijk. Check 26 geeft bij die stand geen melding: de vault heeft nog ~27 bridges ruimte en de grens ligt bij 15. | Toetsen `test_stand_na_de_bijvulling_van_vanavond_mag_rebalancen`, `test_genoeg_gas_meldt_niets` en `test_vaste_ethgrens_zou_de_hoofdwallet_meteen_laten_alarmeren`. Verwachte stand: PLAN M3 en de uitvoer van `gas_bijvullen_uitvoeren.py`. |
| G5 | Een mislukte voorcontrole laat geen spoor na dat Check 25 als gestrand geld zou melden. | `_check_gestrand_rebalance_geld` kijkt alleen naar REBALANCE-voorstellen met status FAILED **en** `aave_withdrawn_at`. Toets: `test_te_weinig_gas_op_de_vault_neemt_niets_op` (`"aave_withdrawn_at" not in uit`). |
| G6 | Stempels van Check 26 overleven een herstart. | `_save_alert_state()` wordt aan het eind van `_run_checks` aangeroepen en schrijft naar `monitor_alert_state.json`. Dat bestand is gemount (`docker-compose.prod.yml:68`) en staat in `STATE_FILES`. Toets: `test_stempels_overleven_een_herstart`. |
| G7 | Toetsen en mutaties. | **Voorcontrole:** 13 toetsen, 11/11 mutaties gevangen (`mut_voorcontrole.py`): niet aangeroepen, ná de opname, geen sleutelcontrole, geen adrescontrole, onbekend adres toegestaan, marge van één stap, geen marge op de vault, RPC-fout doorgelaten, grens verschoven, en in de bridge geen adrescontrole of onbekend adres toegestaan. **Check 26:** 15 toetsen, 11/11 gevangen (`mut_gascheck.py`), waaronder "niet geregistreerd" (de toets draait nu echt `_run_checks`). **Volledige suite:** 400 geslaagd. |

## Raakt deze KPI's / poorten

- **M3-voorwaarden (a):** vault-gas vóór de opname, en een monitorcheck op het ETH-saldo.
  - Na deze wijziging blijven voor M3 over: (c) automatisch herstel van gestrand geld (zes voorwaarden) en (d) een nieuwe A2.
- **H4/H5:** een gastekort wordt nu gezien vóórdat het een beweging breekt.

## Risico en terugdraaien

**Wat kan misgaan.**
- Een REBALANCE wordt vaker geweigerd dan nodig, bijvoorbeeld als `_vault_adres()` door een secret-hapering even onbekend is.
  - Gevolg: FAILED plus een melding, en de volgende volledige run stelt hem opnieuw voor.
  - Er is geen cooldown na FAILED in `_check_rebalance_needed`. Blijft het probleem bestaan, dan komt er ~elk uur een "mislukt"-melding. Dat was al zo bij een gastekort op de treasury.
  - Geld staat daarbij **niet** op het spel: er is niets opgenomen.
- De adrescontrole in `_bridge_usdc_to_hl` kan een bestaand `BRIDGE_BACK_NEEDED`-voorstel laten falen als het vault-adres even onleesbaar is. Dan volgt een FAILED mét `aave_withdrawn_at`, en Check 25 meldt dat. Het alternatief is het geld naar een ander account sturen.
- **Maximaal op het spel:** niets extra; de wijziging voegt alleen weigeringen toe. Op dit moment staat er geen REBALANCE open (te controleren in `treasury_proposals.json`).

**Terugdraaien.** Commit terugdraaien en een full deploy of hot-patch van beide bestanden.

## Wat ik zelf niet heb gecontroleerd

- **De kosten van een ERC-20-overboeking.** Die zijn niet apart gemeten; ik reken 3,9e-6, even duur als een Aave-actie. Een gewone ETH-overboeking kostte 4,3e-7.
- **Of `_vault_adres()` in de container altijd het adres geeft.** Na de deploy van vanavond zit het in de image. Vandaag staat het nog niet in de container (import mislukt).
- **Of de pre-flight `check_treasury` een REBALANCE-geval doorloopt dat nu anders uitvalt.** `check_pipeline` draait op dit moment.

---

## Audit

*Controle-agent, 2026-09-17 (overgenomen door de bouwer; de agent heeft geen schrijftools).*

**Oordeel: GO-mits.** De code doet wat het blad zegt, en de toetsen zijn echt: alle 22 mutaties van de bouwer en 5 eigen mutaties worden rood. Er zijn twee belangrijke punten:
- bij een blijvende weigering komen er veel meer meldingen dan het blad zegt;
- voor de reserve van de hoofdwallet gelden drie verschillende drempels, waardoor het bijvuladvies van Check 26 de REBALANCE kan blokkeren.

**Bevindingen**

1. **[belangrijk] Bij een blijvende weigering komen er twee meldingen per ~5 minuten, niet "~elk uur".**
   - `_check_rebalance_needed` draait ook in `run_fast` (`agents/treasury_agent.py:2090`), elke 5 cycli (`main.py:488-490`).
   - FAILED telt niet als onderweg (`:91`, `:1181-1183`), en `_deploy_geblokkeerd` kijkt alleen naar DEPLOY_YIELD en YIELD_SWITCH (`:811`).
   - Simulatie (`aud3_spam.py`, vault 0,000102): 6 rondes gaven 6 FAILED-voorstellen, 12 Telegram-meldingen en 0 opnames. Dat is ~24 meldingen per uur en ~288 FAILED-records per dag.
   - Op dit moment kan het niet gebeuren: HL staat op $150,52 bij een doel van $150 en een drift van $264.
   - **Mits:** bouw een rem naar het voorbeeld van `_deploy_geblokkeerd` (≥ 2 FAILED REBALANCE zonder `aave_withdrawn_at` in 24 u → geen nieuw voorstel, hooguit 1 melding per 24 u), met een toets die rood wordt zonder rem. Dit moet klaar zijn vóór M3 (d) en vóór elke wijziging die de trigger weer bereikbaar maakt.
2. **[belangrijk] Drie drempels voor dezelfde reserve van de hoofdwallet.**
   - `stuur_eth_voor_gas` houdt de afzender op ≥ `_MIN_ETH_FOR_GAS` (`utils/treasury_executor.py:428-434`).
   - De voorcontrole eist ≥ 0,0001034 (`:361`).
   - Check 26 waarschuwt onder 0,0001255.
   - De treasury-melding zegt dat bijvullen intern vanaf de hoofdwallet kan (`agents/swarm_monitor.py:2494-2496`).
   - Voor de 0,00035 van vanavond is dit in orde.
   - **Mits (vóór de volgende bijvulling of A2):** leg de reserve op één plek vast en gebruik die ook in `stuur_eth_voor_gas`. De treasury-tekst noemt dan wat de hoofdwallet kan missen, of dat er nieuw ETH nodig is.
3. **[klein] Vaste gaslimiet van 80.000 op de overboeking in stap 1** (`:69`, `:824-826`). Zes receipts gebruikten 57.483–62.642 gas, dus tot 78%. Een tekort daar komt ná de opname. Advies: `_estimate_gas(..., fallback=_GAS_TRANSFER)`.
4. **[klein] Gaskosten staan vast in ETH, gemeten bij 0,02 gwei.** De treasury-marge houdt tot ~0,079 gwei. Beter: gas-eenheden × `eth_gasPrice`.
5. **[klein] Onbekend vault-adres in `BRIDGE_BACK_NEEDED` → meteen FAILED, en dat ná de opname** (`:802-807` → `:1633-1635`). Bij een ontbrekende sleutel wacht de code (`:1610-1613`); wachten is hier ook beter.
6. **[klein] Check 26 escaleert nooit bij blijvend onmeetbaar** (`swarm_monitor.py:2472-2480`). Voorstel: één melding na ~24 u zonder meting.
7. **[klein] Naamgeving.** "vault-wallet" moet "hoofdwallet" zijn (`docs/NAMEN.md:78`).
8. **[klein] Telling in G7.** Er staat "12/12" voor `mut_gascheck.py`, maar het zijn er 11/11.
9. **[klein] Deploy.**
   - Deploy beide bestanden samen als full deploy: Check 26 importeert `_vault_adres`, en dat zit niet in de draaiende image.
   - Deploy vóór de bijvulling geeft één terechte treasury-melding.
10. **[belangrijk, buiten scope] Guard-gat in `_get_recent_wr`** (`treasury_agent.py:573-578`): trades met `thematic_exposure` en `harvest` worden niet uitgesloten.
    - Op de VM zijn 5 van de 13 gesloten trades van het potje.
    - Bij ≥ 20 trades met WR ≥ 45% komt er +10pp bij. Dan wordt het doel $528 en vuurt de REBALANCE.
    - Dit is de enige route waarlangs REBALANCE wakker wordt.

**Zonder bevinding gecontroleerd**
- **Paden geteld.**
  - YIELD_SWITCH, diversificatie en DEPLOY_YIELD: het venster is ~1 transactie, en de USDC blijft op onze eigen wallet.
  - FUND_TRADING: alleen bewaken.
  - FUND_SLEEVE, SLEEVE_REBALANCE en `fund_xyz_dex.py`: `sendAsset`, dus geen gas op Arbitrum.
- **Plek van de voorcontrole:** vóór de opname en binnen de `try`. De mutatie "buiten try" maakt 6 toetsen rood.
- **G3 op de VM (alleen adressen vergeleken):**
  - het adres van de vault-sleutel is gelijk aan `HL_VAULT_ADDRESS`;
  - de terugval op `HL_PRIVATE_KEY` zou een ander adres geven;
  - de bridge schrijft bij op de eigenaar van de permit.
- **Legitiem pad intact:** `main.py:163-172` zet `HL_VAULT_ADDRESS` in de omgeving.
- **Receipts (Tenderly):**

  | Soort transactie | Aantal | Kosten (ETH) |
  |---|---|---|
  | Aave-opname | 7 | 3,59–3,93e-6 |
  | Bridge | 6 | 1,68–1,70e-6 |
  | Aave-storting | 6 | 3,37–3,50e-6 |
  | ERC-20-overboeking | 6 | 1,15–1,25e-6 |

  Gasprijs 0,020 gwei.
- **Stand on-chain:** treasury 0,000124084 en vault 0,000497046, wat past bij G4.
- **G5 en G6** kloppen. Er staat geen REBALANCE open; de laatste was op 23-07.
- **Toetsen:**
  - 28/28 nieuwe toetsen;
  - volledige suite 400 geslaagd;
  - `check_treasury` 132/0;
  - `check_syntax` 257 bestanden in orde.
- **Mutaties:** 11/11 en 11/11, plus 5/5 eigen mutaties rood.

**Pre-mortem**
- (a) Een overboeking van 80k gas valt zonder gas ná een opname.
- (b) Een bijvulling volgens de tekst van Check 26 blokkeert de REBALANCE.
- (c) De REBALANCE wordt wakker door de WR-boost van trades van het potje.

**Gemiste kans:** met drift 10% ≥ doel 5–10% vuurt REBALANCE nooit. Besluit of REBALANCE live hoort te zijn; zo niet, dan is M3 (c) mogelijk overbodig.

**Open vragen**
- Wordt `market_regime.json` nog ververst?
- Hoort REBALANCE live te zijn?
- Wat komt vanavond eerst: de bijvulling of de deploy?

## Reactie bouwer

*Ronde 2, 2026-09-17. Nog ongecommit; zie de werkkopie.*

| # | Status | Wat |
|---|---|---|
| 1 | **opgelost** | `TreasuryAgent._rebalance_geblokkeerd()`, aangeroepen in `_check_rebalance_needed` na de onderweg-guard: bij ≥ 2 FAILED REBALANCE in 24 u geen nieuw voorstel, en hooguit 1 pauzemelding per 24 u. Hij telt **elke** FAILED REBALANCE, ook met opname: dan ligt er al geld op Arbitrum. Toetsen: `test_blijvende_rebalance_weigering_geeft_geen_meldingsregen` (12 fast-passes geven 2 voorstellen en 1 pauzemelding), `test_rem_telt_alleen_de_laatste_24_uur`, `test_rem_telt_geen_andere_soorten_fouten`. |
| 2 | **opgelost** | Eén reserve: `_GAS_WAARSCHUW_TX = 15` en `_HOOFDWALLET_RESERVE_ETH = _MIN + 15 × 1,7e-6` (0,0001255) in `treasury_executor`. `stuur_eth_voor_gas` eist nu `bedrag + reserve`. Check 26 haalt kosten, aantal en reserve uit die module. De treasury-melding noemt wat de hoofdwallet kan missen (saldo − reserve, alleen als dat ≥ 15 Aave-acties is), anders "kan niets missen → nieuw ETH → Bart". Onmeetbaar geeft "onbekend". Toetsen: `test_afzender_houdt_de_reserve_van_de_hoofdwallet_over`, `test_bijvulling_van_vanavond_past_binnen_de_reserve` (0,000497046 ≥ 0,00035 + 0,0001255), `test_treasury_melding_*` (3×), `test_advies_rekent_met_de_reserve_niet_met_de_blokkadegrens`, `test_reserve_van_de_hoofdwallet_valt_precies_op_de_waarschuwingsgrens`. |
| 3 | **opgelost** | De overboeking in stap 1 gebruikt `_estimate_gas(_USDC_ARB, data, treasury, _GAS_TRANSFER)`. Toets: `test_overboeking_in_de_bridge_gebruikt_een_schatting_met_ondergrens`. |
| 4 | **bewust niet** | Gas-eenheden × `eth_gasPrice` is beter, maar de marge houdt tot ~4× de huidige gasprijs, en de voorcontrole is een ondergrens (een tekort geeft nog steeds een FAILED vóór de opname). Genoteerd voor wanneer M3 (d) aan de beurt is. |
| 5 | **opgelost** | In `BRIDGE_BACK_NEEDED` wacht de code nu als `_vault_adres()` leeg is, net als bij een ontbrekende sleutel. Toets: `test_bridge_back_wacht_als_het_vaultadres_even_onbekend_is`. |
| 6 | **opgelost** | `_eth_gas_onmeetbaar`: na 24 u zonder meting één melding, daarna hooguit elke 72 u. Een geslaagde meting zet de klok terug. Toetsen: `test_een_dag_onmeetbaar_geeft_een_melding`, `test_een_geslaagde_meting_zet_de_onmeetbaar_klok_terug`. |
| 7 | **opgelost** | De melding zegt "treasury-wallet" en "hoofdwallet" (`GAS_ROLLEN`). |
| 8 | **opgelost** | De telling is gecorrigeerd. |
| 9 | **gevolgd** | Full deploy van beide bestanden samen, eerst de deploy en dan de bijvulling (`stuur_eth_voor_gas` zit pas na de deploy in de image). Die ene terechte treasury-melding tussen deploy en bijvulling accepteer ik. |
| 10 | **opgelost** | `_get_recent_wr` sluit `harvest` en `thematic_exposure` uit. Toets: `test_winrate_telt_potje_en_oogstregels_niet_mee` (19 echte trades plus 6 potjesregels geeft `None`). |

**Mutaties ronde 2**
- `mut_a1r2.py`: 13/13 rood (rem, meldklok, soorten, 24 u, WR-guard, reserve, transfergas, wachten, escalatie, herhaalklok, klok terug, adviesconditie, reserve in advies).
- `mut_gascheck2.py` (Check 26 na herschrijving): 12/12 rood.
- `mut_voorcontrole.py`: 11/11 rood.
- Eén **gelijkwaardige** mutant: `if rol == "treasury"` → `if True`. Voor de hoofdwallet onder de grens is saldo − reserve altijd < 0, dus die tak zegt ook "nieuw ETH → Bart".
- Volledige suite: **418 geslaagd**.

**Open vragen van de audit**
- **`market_regime.json`:** nagaan bij de deploy van vanavond. De schrijver is de ResearchAgent, en die zit achter de pijplijnschakelaar.
- **Hoort REBALANCE live te zijn?** Advies aan Bart: laten staan als vangnet voor HL-marge. Met de rem, de voorcontrole en de WR-guard kan hij geen regen of gestrand geld meer maken zonder melding. M3 (c) (automatisch herstel) wordt pas nodig als REBALANCE werkelijk kan vuren; tot dan volstaat de detectie in Check 25.
- **Volgorde vanavond:** eerst de deploy, dan de bijvulling.

## Audit ronde 2

*Controle-agent, 2026-09-17 (overgenomen door de bouwer).*

**Oordeel: GO.** Alle punten uit ronde 1 zijn opgelost, of met een geldige reden afgewezen (#4). Er is niets blokkerends of belangrijks. Wel vijf kleine punten:

1. **Vier eigen mutaties op de rem bleven groen:** geslaagde rebalances meegeteld, drempel 11, een pauzemelding per uur, en de meldstempel na een tweede storing.
2. **De pauzetekst klopt niet.** Er staat "tot 24u na de laatste fout", maar de rem gaat open 24 u na de oudste van de twee. Simulatie over 72 u: 6 FAILED en 3 pauzemeldingen, tegen ~288 per dag zonder rem.
3. **Tijden met en zonder tijdzone door elkaar.** Op de VM (UTC) is het venster 24 u, lokaal (CEST) 26 u.
4. **Reservecontrole zonder transactiekosten.** Een bijvulling precies op de grens eindigt ~4,6e-7 onder de reserve. Vanavond is de marge 2,15e-5.
5. **De docstring belooft meer dan de code doet.** Eén FAILED mét opname blokkeert niets.

**Gecontroleerd:**
- Mutaties van de bouwer 13/13, 12/12 en 11/11 rood; eigen mutaties op de WR-guard, de schattingsvloer en de reserve rood.
- Gelijkwaardige mutant bevestigd: van 251.000 saldi met een alarm kiest er 0 het interne advies.
- De bijvulling past (0,000497046 ≥ 0,0004755). Daarna blijft er ruimte voor 27,4 bridges en 95,9 treasury-transacties.
- `_estimate_gas` begrenst op [80k, 1,5M].
- De rem telt alleen FAILED, en er is één agentinstantie.
- Stand op de VM: 21 voorstellen, niets onderweg.
- WR-guard op echte data: 13 trades, 8 na de guard.
- Suite 419 geslaagd, pijplijn 132/0.

## Reactie bouwer ronde 2

| # | Status | Wat |
|---|---|---|
| 1 | **opgelost** | Nieuwe toetsen: `test_rem_drempel_is_twee`, `test_geslaagde_rebalances_remmen_niet`, `test_pauzemelding_hooguit_een_keer_per_dag` (+2 u geen melding, +25 u wel) en `test_tweede_storing_na_herstel_meldt_weer_na_een_dag`. De mutaties van de auditor (`r2_eigen.py`) worden daardoor rood, op de reserve-mutatie na; die is in `mut_r2b.py` aangepast aan de nieuwe regel en ook rood. |
| 2 | **opgelost** | De tekst luidt nu: "zolang er in de laatste 24u 2 of meer mislukten". Het docstring zegt dat de rem opengaat 24 u na de oudste fout. |
| 3 | **opgelost** | `grens` en `nu` gebruiken `time.time()` (ook in `_deploy_geblokkeerd`), en `_parse_ts` leest een tijd zonder zone als UTC. Toetsen: `test_rem_venster_is_24_uur_ook_met_tijdzone_en_zonder` en `test_verse_naieve_fout_remt_ook_buiten_utc`. De mutatie `parse_ts_lokaal` is rood buiten UTC; op een UTC-machine is hij gelijkwaardig. |
| 4 | **opgelost** | `nodig = bedrag + _HOOFDWALLET_RESERVE_ETH + _GAS_KOSTEN_OVERBOEKING_ETH` (1e-6). Toets: `test_reserve_rekent_de_kosten_van_de_overboeking_mee`. Vanavond blijft er 2,05e-5 marge. |
| 5 | **opgelost** | Het docstring zegt nu dat één FAILED mét opname niets blokkeert; dat geval meldt Check 25 en hoort bij M3 (c). |

**Mutaties na ronde 2** (`mut_a1r2`, `mut_r2b`, `r2_eigen`): alle rood, op één na. `parse_ts_lokaal` is rood buiten UTC en gelijkwaardig op UTC. Suite **408 geslaagd**: de 19 GitHub-waakhondtoetsen zijn uit de werkkopie gehaald, er kwamen 9 nieuwe bij. `check_pipeline` 132/0.
