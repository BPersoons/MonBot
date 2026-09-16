# Claimblad — de zes bevindingen uit de vorige A1-ronde

*Datum: 2026-09-16 · Poort: **A1** (code die geld raakt) · Mijlpaal: voorwaarden vóór M3*

> Voor de controle-agent. Dit zijn bevindingen 1–4, 6 en 7 uit jouw audit op `1eac851`. Bevinding 5 (Check 14) zit al live in `e22af00`.

## Wat er verandert
- Bestanden: `agents/treasury_agent.py`, `utils/treasury_executor.py`, `tests/test_treasury_cap.py`, `tests/test_treasury_manual_withdrawal.py`.
- **Productie-impact vandaag:** geen. Er staat geen rebalance, geen FUND_TRADING, geen voorstel in NEEDS_MANUAL_WITHDRAWAL, en het rebalance-pad kan met het huidige RANGING-regime niet vuren (HL $151 tegen doel $150, trigger bij < −$114).

## Beweringen
| # | Bevinding | Wat ik deed | Bewijs |
|---|---|---|---|
| 1 | In `run()` konden een deploy én een rebalance in dezelfde cyclus ontstaan | `_check_rebalance_needed` staat nu vóór de generate-block, zoals in `run_fast`; de reden staat in de code (marge-herstel heeft voorrang en houdt zijn eigen guard) | `test_run_doet_eerst_de_rebalance_en_daarna_pas_een_deploy`: de rebalance maakt een APPROVED-voorstel en de deploy wordt in dezelfde cyclus niet meer aangeroepen |
| 2 | Een rebalance die faalde ná de Aave-opname liet USDC op de wallet die de deploy terugduwde naar Aave | `_gestrande_rebalance` (FAILED + `aave_withdrawn_at` + geen `completed_at` + niet eerder opgevolgd) en `_gestrand_geld_naar_hl`: maakt een FUND_TRADING (PENDING) voor dat bedrag, markeert de rebalance met `opgevolgd_door`, meldt één keer. Aangeroepen in `run` én `run_fast`, direct na de rebalance-check | `test_gestrand_rebalance_geld_gaat_naar_hl_en_niet_terug_naar_aave`, `test_een_geslaagde_of_vroeg_gefaalde_rebalance_strandt_niet`, `test_run_fast_pakt_gestrand_geld_op_en_deployt_niet` (aansluiting) |
| 3 | Twee definities van "rebalance onderweg" | `_check_rebalance_needed` gebruikt nu dezelfde constante `_REBALANCE_ONDERWEG` | `test_tweede_rebalance_kan_niet_ontstaan_tijdens_het_bridgen` (alle vier statussen) |
| 4 | FUND_TRADING ontbrak in de helper terwijl `flows` hem als transit telt | `_FUND_TRADING_ONDERWEG = {PENDING, APPROVED, MONITORING}` als vierde tak | `test_fund_trading_blokkeert_een_beweging_naar_yield` (COMPLETED blokkeert niet) |
| 6 | De verlooptak stond vóór de saldo-poll | Saldo eerst; aangekomen geld gaat naar BRIDGED en verloopt niet meer | `test_geld_dat_net_op_tijd_aankomt_wint_van_de_verlooptijd`, `test_handmatige_opname_verloopt_na_48u_als_het_geld_er_niet_is` |
| 7 | Geen plain-text-fallback in `_send_telegram` | Tweede poging zonder `parse_mode`; faalt die ook, dan `logger.error` | `test_telegram_valt_terug_op_platte_tekst` (twee pogingen, tekst ongewijzigd) |

**Mutatietoetsen:** `_FUND_TRADING_ONDERWEG` leeg → toets rood; `_gestrande_rebalance` altijd None → zowel de unit- als de `run_fast`-aansluitingstoets rood.

## Raakt deze KPI's / poorten
- M3-cap per protocol, H1 (gestrand geld dat als opbrengst zou landen), Check 24 saldo-controle tijdens transit.

## Risico en terugdraaien
- **Grootste risico's:**
  - `_FUND_TRADING_ONDERWEG` bevat PENDING. Een FUND_TRADING dat blijft staan, blokkeert dus alle yield-bewegingen; de PENDING-TTL van 6 uur is het enige vangnet, en die geldt niet voor MONITORING.
  - Het gestrande-geld-pad maakt een voorstel dat **een mens moet uitvoeren** (handmatige bridge). Tot dat gebeurt staat kasbeheer stil — bewust, maar het is stilstand.
  - `opgevolgd_door` staat in `treasury_proposals.json`; gaat dat bestand verloren, dan kan het voorstel opnieuw ontstaan. Het is gemount en staat in `STATE_FILES`.
  - De volgordewijziging in `run()` betekent dat een rebalance nu voorrang krijgt boven een deploy van vers geld op de wallet. Dat is de bedoeling, maar het is een gedragswijziging bij krappe HL-marge.
- **Terugdraaien:** `git revert` + deploy.

## Wat ik zelf niet heb gecontroleerd (vóór de audit)
- Of een FUND_TRADING in MONITORING in de praktijk ooit blijft hangen (dan blokkeert hij zonder TTL).
- Of `_MIN_DEPLOY_USD` de juiste ondergrens is voor het gestrande bedrag — ik hergebruik hem, maar een bridge naar HL heeft een eigen minimum ($5 volgens de foutmelding van 23-07).
- Of de nieuwe volgorde in `run()` iets breekt in de tranche-logica van de optimizer, die `treasury_usdc` eerder in de cyclus leest.
- De Telegram-fallback is niet in productie beproefd; de toets mockt `urlopen`.

---

## Audit
**Oordeel: STOP** op `3e6f184`. Twee blokkerende bevindingen, allebei in het nieuwe gestrande-geld-pad; de vier andere reparaties zijn schoon (alle zes mutaties rood, 309 toetsen groen, volgordewijziging raakt de tranche-logica aantoonbaar niet).

**Correctie op mijn claimblad:** ik schreef "geen voorstel dat dit raakt". Onjuist — op de VM staat `TRR_20260723_1501` (REBALANCE, FAILED, $267,28, `aave_withdrawn_at` 2026-07-23, geen `completed_at`, 55 dagen oud). Dat record voldoet precies aan mijn nieuwe detectie.

| # | Bevinding | Reactie |
|---|---|---|
| 1 | **[blokkerend]** `_gestrande_rebalance` heeft geen tijdsgrens en geen koppeling aan de echte dollars; het 23-07-record staat live en zou bij de eerste switch (~$1.600 kort op de wallet) $267 daarvan claimen, met een feitelijk onjuiste melding | **Aanvaard — feature teruggetrokken.** Zie besluit hieronder |
| 2 | **[blokkerend]** Het vangnet dat ik claimde (PENDING-TTL 6u) bestaat niet op dit pad: `_upsert_proposals` ruimt stale PENDING alleen op wanneer er géén blokkade is. Een blijvend PENDING/MONITORING FUND_TRADING bevriest alle vier de bewegingen én zet de saldo-controle van het veilige potje permanent uit | **Aanvaard — blokkade teruggetrokken.** Mijn claim was fout; ik had de aanroepplek van de TTL niet nagelopen |
| 3 | MONITORING is nu blokkerend maar staat niet in Check 14 en is niet af te wijzen | Vervalt met de terugtrekking; komt terug als voorwaarde |
| 4 | Een tweede rebalance kan de FUND_TRADING afsluiten via een HL-stijging → valse stroom yield_core→swarm van $267 op H1/NAV | Vervalt met de terugtrekking; komt terug als voorwaarde |
| 5 | De detector keek maar naar één van de twee adressen waar gestrand bridge-geld kan liggen; onder $100 werd `opgevolgd_door` niet gezet, dus hij vuurde elke 5 minuten opnieuw | Vervalt met de terugtrekking; komt terug als voorwaarde |
| 6 | `_MIN_DEPLOY_USD` is verdedigbaar; het bridge-minimum van $5 is niet de relevante grens | Genoteerd — mijn eigen twijfel was ongegrond |
| 7 | De Telegram-fallback dekt een 400 wél, maar niet `ok:false` bij HTTP 200, en verdubbelt de timeout (2×10s per melding) | **Blijft staan in deze commit** (strikt beter dan niets), en gaat mee in de volgende ronde: body lezen en een kortere fallback-timeout |

## Besluit: splitsen
Het gestrande-geld-pad (`_gestrande_rebalance`, `_gestrand_geld_naar_hl`, de twee aanroepen) en `_FUND_TRADING_ONDERWEG` zijn **uit deze commit verwijderd**, inclusief hun drie toetsen. Wat blijft: de volgorde in `run()` (bevinding 1 van de vorige ronde), één definitie van "rebalance onderweg" (3), saldo vóór verlopen (6) en de Telegram-fallback (7) — precies de vier die de controle-agent schoon noemde. De verwijderde code blijft leesbaar in `3e6f184`.

**Voorwaarden voor de herbouw (eigen ronde, eigen audit):**
1. Tijdsgrens (`aave_withdrawn_at` binnen 24u) **én** geen latere COMPLETED REBALANCE/DEPLOY_YIELD, met een toets die faalt op het echte record `TRR_20260723_1501`.
2. De blokkade zelf begrensd in tijd, of de TTL-opruiming vóór de `has_in_flight`-bepaling — met een toets dat kasbeheer na N uur weer beweegt.
3. MONITORING in Check 14 en `/reject` toestaan op MONITORING.
4. De FUND_TRADING afsluiten op het **verdwijnen van de wallet-USDC**, niet op een HL-stijging (anders sluit de bridge van een andere rebalance hem af en ontstaat er een valse stroom).
5. Beide adressen lezen (treasury-wallet én het vault-Arb-adres).
6. Telegram: responsbody lezen (`ok:false`) en een kortere fallback-timeout.

**Antwoorden op de open vragen:**
- *Het oude record met de hand afsluiten vóór de deploy?* Nee. Het blijft staan als echte testcase voor voorwaarde 1; met de hand markeren verbergt het probleem en laat elke toekomstige FAILED-rebalance eeuwig scherp staan.
- *Hoe eindigt een FUND_TRADING als niemand bridget?* Dat is precies voorwaarde 2 + 3: een leeftijdsgrens op de blokkade, en afwijzen moet kunnen.
- *Waarom sluit hij af op een HL-stijging?* Historisch, en het is fout — voorwaarde 4 draait dat om naar de gebeurtenis die we echt bedoelen.
