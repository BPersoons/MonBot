# Claimblad — REBALANCE telt als "onderweg" (V6) en de stroom na een verlopen opname (V5)

*Datum: 2026-09-16 · Poort: **A1** (code die geld raakt) · Mijlpaal: voorwaarden vóór M3 en vóór de eerstvolgende HL→yield-deploy*

> Voor de controle-agent. Dit zijn de twee openstaande voorwaarden uit jouw audit van vanochtend op `fe5aed9`/`33d89cc` (V5 en V6). V1–V3 zijn gedeployed en geverifieerd, V4 blijft staan tot M5.

## Wat er verandert
- Vervolg op `e4fb96e` (live sinds 16-09 07:39 UTC).
- Bestanden: `agents/treasury_agent.py` (V6), `utils/treasury_executor.py` (V5, meldingstekst), `.claude/commands/boek-order.md` (V5, werkwijze), `tests/test_treasury_cap.py`.
- **Productie-impact vandaag:** geen gedragswijziging. Er loopt geen REBALANCE en geen voorstel in NEEDS_MANUAL_WITHDRAWAL; Aave is het enige geautomatiseerde protocol, dus er is geen switch mogelijk.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Een lopende REBALANCE blokkeert switch, diversificatie, HL-overschot en nieuwe deploys | `_REBALANCE_ONDERWEG = {APPROVED, REBALANCING, BRIDGE_BACK_NEEDED, BRIDGING_TO_HL}` als derde tak in `_yield_beweging_onderweg`; die helper zit op alle vijf aanmaakplekken (ongewijzigd t.o.v. jouw vorige controle) |
| 2 | De statusset dekt de hele REBALANCE-keten | Statusmachine in `utils/treasury_executor.py` (kopregel): APPROVED → REBALANCING → BRIDGE_BACK_NEEDED → BRIDGING_TO_HL → COMPLETED. Alleen COMPLETED/FAILED blijven buiten de set |
| 3 | Een afgeronde rebalance blokkeert niets | `test_geen_yield_beweging_tijdens_een_rebalance` toetst COMPLETED expliciet (switch komt er dan wél) |
| 4 | De toets bijt | Mutatie: helper zonder de REBALANCE-tak → `test_geen_yield_beweging_tijdens_een_rebalance` faalt ("gevangen") |
| 5 | `_check_rebalance_needed` blijft werken | Die functie heeft een eigen in-flight-guard en draait als eerste in `run`/`run_fast`; de helper wordt daar niet vóór aangeroepen |
| 6 | Bij een verlopen opname is er op dát moment niets te boeken | NEEDS_MANUAL_WITHDRAWAL betekent dat de bridge nooit startte: de USDC staat nog op Hyperliquid (jouw eigen bevinding). De melding geeft daarom een **instructie** voor het geval Bart later alsnog opneemt, geen automatische boeking |
| 7 | De instructie staat ook in de werkwijze | `/boek-order` stap 1b noemt nu expliciet: handmatige opname HL → treasury-wallet = `swarm` → `yield_core`, en de omgekeerde richting |
| 8 | Pre-deploy-poort groen | `python scripts/predeploy.py`: state-audit, syntax, pytest, pipeline. CI groen op `69612e2` |

## Raakt deze KPI's / poorten
- M3-cap per protocol (V6), H1 (niet-geboekte stroom telt als opbrengst, V5), Check 24 saldo-controle tijdens transit.

## Risico en terugdraaien
- **Grootste risico's:**
  - Strenger blokkeren betekent langer wachten: een rebalance duurt tot de handmatige HL-storting is gedaan (stap 2 van het voorstel). Zolang die openstaat, gebeurt er geen switch of deploy. Bij een rebalance die blijft hangen in BRIDGE_BACK_NEEDED is dat mogelijk lang — dezelfde klasse als de NEEDS_MANUAL-lus, maar zonder verlooptijd.
  - V5 leunt volledig op discipline: een melding die Bart moet opvolgen. Dat is zwakker dan code, en het is precies het zwakke punt dat `/boek-order` al noemt voor de broker.
- **Op het spel:** vandaag niets; vanaf M3 de cap van 65% per protocol.
- **Terugdraaien:** `git revert` + deploy.

## Wat ik zelf niet heb gecontroleerd (vóór de audit)
- Of een REBALANCE in de praktijk lang in BRIDGE_BACK_NEEDED blijft staan (dan is een verlooptijd nodig, zoals bij de handmatige opname).
- Of er nog een pad is waarlangs geld tussen `swarm` en `yield_core` beweegt zonder proposal — de bekende zijn: handmatige opname, handmatige storting, en de bridge-stap van een rebalance.
- Of de Telegram-melding bij EXPIRED in de praktijk leesbaar is (Markdown met backticks in een melding die ook `_md_escape` passeert bij monitorberichten; deze melding gaat via de executor, niet via de monitor).

---

## Audit
**Oordeel: GO-mits.** `1eac851` mag gedeployed worden — strikt strenger dan wat live staat, en het repareert een botsing die in productie **twee keer** is voorgekomen (18-07 en 23-07: een DEPLOY_YIELD aangemaakt in dezelfde seconde als `aave_withdrawn_at` van een lopende rebalance, om dezelfde dollars).

**Correcties op mijn claimblad:**
- Bewering 2 is onvolledig: FAILED valt buiten de set, en een rebalance die ná de Aave-opname faalt laat USDC op de wallet staan die de deploy-detector terug naar Aave duwt (`TRR_20260723_1501` → `TRP_20260723_2002_0`, $434,31) terwijl HL juist marge tekortkwam.
- Mijn risicoparagraaf klopte niet: BRIDGE_BACK_NEEDED wacht **niet** op een handmatige storting — de executor bridget zelf. De hele keten duurt historisch 10–30 minuten, dus de blokkade is minuten, geen dagen. De `steps`-tekst van het rebalance-voorstel is verouderd.
- De toets dekt maar één van de vijf aanroepplekken; een aansluitingstoets op `run()` voor REBALANCE ontbreekt.

| # | Bevinding | Reactie |
|---|---|---|
| 5 | BRIDGE_BACK_NEEDED en BRIDGING_TO_HL onzichtbaar in Check 14 (**voorwaarde bij de deploy**) | **Opgelost** in deze deploy: beide toegevoegd aan de vastgelopen-check (> 6u → Telegram) |
| 1 | In `run()` kunnen een deploy én een rebalance in dezelfde cyclus ontstaan | **Aanvaard, volgende ronde.** `_check_rebalance_needed` gaat vóór de generate-block, zoals in `run_fast`, mét aansluitingstoets |
| 2 | Gefaalde rebalance ná de opname duwt geld terug naar Aave | **Aanvaard, volgende ronde.** Geen FAILED in de set (dat bevriest alles), maar apart melden en het wallet-saldo naar FUND_TRADING sturen |
| 3 | Twee definities van "rebalance onderweg" (BRIDGING_TO_HL ontbreekt in de eigen guard) | **Aanvaard, volgende ronde.** Eén constante |
| 4 | FUND_TRADING ontbreekt in de helper terwijl `flows` hem wél als transit telt | **Aanvaard, volgende ronde** (incl. PENDING, met de TTL van 6u als vangnet) |
| 6 | Verloop-race: EXPIRED vóór de saldo-poll | **Aanvaard, volgende ronde.** Saldo eerst lezen, dan pas verlopen |
| 7 | Geen plain-text-fallback in `_send_telegram`, geen toets op de tekst | **Aanvaard, volgende ronde.** Zelfde patroon als `sleeve_nav`/`thematic_exposure_lab` |

**Antwoorden op de open vragen:**
- *V5 had twee helften; alleen de instructie is gebouwd.* Klopt, en dat had in het claimblad moeten staan. De tweede helft (deploy pas vrijgeven als de stroom geboekt is) vergt een blokkade op iets dat een mens moet doen — dat wil ik samen met bevinding 2 bouwen, want die twee raken dezelfde route.
- *Waarom staat `_check_rebalance_needed` buiten de helper?* Omdat marge-herstel voorrang heeft; dat was impliciet. Wordt expliciet in de code gezet bij bevinding 1.
- *Verouderde `steps`-tekst?* Ja, gaat mee in de volgende ronde.
