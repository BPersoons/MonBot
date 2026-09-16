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

## Wat ik zelf niet heb gecontroleerd
- Of een FUND_TRADING in MONITORING in de praktijk ooit blijft hangen (dan blokkeert hij zonder TTL).
- Of `_MIN_DEPLOY_USD` de juiste ondergrens is voor het gestrande bedrag — ik hergebruik hem, maar een bridge naar HL heeft een eigen minimum ($5 volgens de foutmelding van 23-07).
- Of de nieuwe volgorde in `run()` iets breekt in de tranche-logica van de optimizer, die `treasury_usdc` eerder in de cyclus leest.
- De Telegram-fallback is niet in productie beproefd; de toets mockt `urlopen`.
