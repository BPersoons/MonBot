# Claimblad — HYPE-basis proefpotje (A1 code, A2 geld)

*Datum: 2026-10-06 · Poort: A1 (deploy van code die geld raakt) + A2 (kapitaalbeweging) · Akkoord Bart 06-10: "akkoord" op een proefpotje van $245*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
- **Nieuw: `utils/basis_hype.py`.** Spot-HYPE long en een HYPE-perp short op een **eigen wallet** (`HL_BASIS_WALLET_ADDRESS` / `HL_BASIS_PRIVATE_KEY`, self-custody, nog aan te maken). Het account moet in de default-modus staan, niet unified.
  - **Pure planning:** `plan()`.
  - **Uitvoering:** `BasisHype`.
  - **Lezen voor de rest van het systeem:** `lees_state()`.
- **`main.py`.** Start de module alleen als beide secrets bestaan, zonder terugval op de hoofdwallet. Hij draait op `cycle_count % 5 == 4`.
- **Meetkant:**
  - `utils/sleeve_nav.py`: potje `basis` met venue `hyperliquid_basis`. Zonder statebestand is de waarde 0; staat er een bestand zonder waarde, dan is dat onmeetbaar en wordt de snapshot uitgesteld.
  - `utils/nav.py`: regel "HYPE-basis (proefpotje)".
  - `utils/verliesbewaking.py`: levert `basis_verlies_usd` (netto inleg uit flows, potje `basis`, min de waarde) en kijkt naar het experiment `basis_hype` in plaats van `basis_traag`. Is het potje live maar onleesbaar, dan volgt een alarm.
- **`config/experimenten.json`.** `basis_hype` met sleeve `basis` en budget $245. Status blijft `idee` tot na de A2-GO en de storting; dan `live`, `verliesbudget_telt_mee: true` en `verlies_meten_vanaf`.
- **State:** `data/basis_hype_state.json`. `data/` is als geheel gemount, dus het hoeft niet in STATE_FILES. Schrijven gebeurt in-place.
- **Toetsen:** `tests/test_basis_hype.py` (29), `tests/test_basis_nav.py` (4) en 3 nieuwe in `tests/test_verliesbewaking.py`.
- **Productie-impact:**
  - Echte orders op HYPE spot en perp, op een nieuwe, aparte wallet.
  - Eén overboeking van ~$115 van de hoofdwallet (0x92D4, spot-USDC dat nu stil staat) naar de nieuwe wallet, via `TreasuryAgent._send_asset` (spot→spot). Die wordt geboekt als flow `swarm → basis` in `data/flows.json`.

## Regels van het potje
| Regel | Waarde | Waar |
|---|---|---|
| Hefboom op de short (na r1) | doel 1,5x, bijsturen buiten [1,0x, 2,0x], HL-instelling 2x — binnen het kader van 2x. Boven 2x wordt altijd bijgestuurd, ook als dat onder het HL-minimum zou vallen (dan $11 terug) | `LEV_*` |
| Volgorde openen (na r1) | eerst de marge naar perp, dan spot kopen, dan de short ter grootte van de gekochte spot. Alleen als het register `live` zegt, er inleg geboekt is en de funding niet negatief is | `plan`, `_voer_uit` |
| Koers omhoog (hefboom > 2x) | eerst short kleiner (reduceOnly), dan spot verkopen, dan USDC naar perp | `plan` |
| Koers omlaag (< 1,0x) | USDC naar spot, spot kopen, short groter | `plan` |
| Hedge scheef > 3% en > $11 | short volgt spot (groter, of kleiner met reduceOnly) | `plan` |
| Afbouwen | schakelaar `basis_hype_afbouwen`, of verlies ≥ 50% van de inleg (proeftuinregel), of funding over 7 dagen negatief: short sluiten (reduceOnly), spot verkopen. **Blijvend** (na r1): vlag `afgebouwd` in de state, heropenen alleen met de hand | `plan` |
| Uit | `subsystem_basis_hype_enabled=false`: hij meet nog wel, maar handelt niet; de benen blijven gehedged staan | `run_cycle` |
| Fouten | elke fout wordt geteld; na 3 op rij één Telegram-melding; de volgende cyclus plant opnieuw vanuit de werkelijke stand | `run_cycle` |
| Accountmodus | alleen exact "default"; unified of `None` wordt geweigerd | `toestand` |
| Ouderdom | staan de benen open en is de meting ouder dan 1 uur, dan is de waarde onmeetbaar (sleeve_nav stelt de snapshot uit; de verliesbewaking geeft een alarm als het potje live staat) | `lees_state` |

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Het papier haalt het: netto op kapitaal 2025 14,9%, 2026 5,7%, geen liquidatie en geen verliesmaand | `python scripts/basis_sim.py HYPE`; register `basis_hype.volgende_stap` |
| 2 | Er komt nooit een short zonder spot eronder: bij openen en bij bijkopen komt de spot eerst, en de short volgt de gemeten spot | `test_cyclus_opent_gehedged`, `test_openen_koopt_eerst_spot_en_short_daarna` |
| 3 | Elke verkleining van de short is reduceOnly | `test_short_kleiner_is_altijd_reduce_only`, `test_short_groter_dan_spot_wordt_reduce_only_verkleind`, `test_afbouwen_sluit_short_reduce_only_en_verkoopt_spot`; mutaties `reduce_only=False` → rood |
| 4 | Elke regel heeft een toets die rood wordt als je hem uitzet | 11 mutaties: reduceOnly (2×), stopverlies, funding, schakelaar, hedge, band, melden, uit-schakelaar, minimumkapitaal → elk ≥ 1 rood |
| 5 | Onmeetbaar is nooit nul: een kapot statebestand of een waarde `None` geeft onmeetbaar in sleeve_nav en nav, en een alarm in de verliesbewaking als het potje live staat | `tests/test_basis_nav.py`, `test_basis_onmeetbaar_terwijl_live_meldt` |
| 6 | Het verlies telt pas in het budget van $250 als het register `live` + `verliesbudget_telt_mee` zegt | `test_basis_verlies_telt_niet_zolang_niet_live` / `_als_live` |
| 7 | Zonder secrets draait er niets; er is geen terugval op de hoofdwallet | `main.py` blok BasisHype |
| 8 | Op de hoofdwallet staat $145,38 spot-USDC waarvan $26,63 "hold" (geen open orders, geen perp-posities; herkomst onbekend), dus er is ~$118 vrij | `spotClearinghouseState` / `frontendOpenOrders` 06-10 |

## A2: de kapitaalbeweging
- **Wat:** ~$115 van 0x92D4 spot naar de nieuwe wallet spot. Dat geld levert nu niets op, en de handelspijplijn staat uit.
- **Waarom niet de volle $245:** het restant moet uit Aave komen, met een brug. Dat volgt pas als de eerste weken laten zien dat de techniek werkt; Barts akkoord dekt het tot $245.
- **Proeftuin:** $255 (dip-koper) + $115 = $370, binnen de $500.
- **Volgorde:**
  1. A1-GO.
  2. Wallet en secrets aanmaken.
  3. Deploy.
  4. Controleren dat `userAbstraction` "default" geeft. Dat kan pas zodra het account bestaat, dus na de storting en vóór de eerste cyclus met geld.
  5. Overboeking.
  6. Flow boeken.
  7. Register op `live` zetten.
  8. De eerste cyclus live volgen: spot gekocht, short gelijk, hefboom ~2x, waarde ≈ inleg min kosten.

## Raakt deze KPI's / poorten
- H1 en H2 (potje `basis` staat al in `kpi.BEHEERD`).
- H3 (verliesbudget, zodra live).
- Proeftuinkapitaal $500, max 50% verlies per potje, hefboom ≤ 2x. Het doel is 2x; bij koersstijging loopt de hefboom kort op tot 3x vóór bijsturen. Die 3x is de hefboom op de short-marge; het potje als geheel heeft netto hefboom ~0, want het is gehedged.

## Risico en terugdraaien
- **Maximaal op het spel:** de inleg (~$115). Afbouwen gebeurt automatisch bij 50% verlies.
- **Echte risico's:**
  - ADL: HL sluit de short bij een squeeze, dan staat de spot even ongedekt. De hedgecheck van de volgende cyclus herstelt dat, binnen ~5 min.
  - Liquidatie als de koers binnen één cyclus > ~45% stijgt (onderhoudsmarge bij 3x).
  - Venue-risico: alles staat op HL.
  - De eerste keer `sendAsset` naar de perp-dex `""` op een default-account (bij de dip-koper ging het naar "xyz").
- **Terugdraaien:**
  - `basis_hype_afbouwen=true` in `config/auto_params.json`: de volgende cyclus sluit de short en verkoopt de spot.
  - Daarna eventueel `subsystem_basis_hype_enabled=false`.
  - Het geld terug naar de master gaat met sendAsset (spot→spot) en de sleutel van de basis-wallet.

## Wat ik zelf niet heb gecontroleerd
- **sendAsset met `destinationDex: ""`** naar de eigen hoofd-perp-dex. Volgens de HL-docs is `""` de default perp-dex, maar ik heb het niet live getest.
- **De modus van een nieuw account** (default of unified). De code weigert unified.
- **Of HL spot-HYPE ooit als marge telt.** In de default-modus niet, aangenomen.
- **De funding die het account echt ontvangt,** tegenover de API-reeks.
- **De hold van $26,63 op de master.**

---

## Audit
*(in te vullen door de controle-agent)*

**r1 (2026-10-06): STOP.** De punten:
1. Het perp-symbool `"HYPE"` bestaat niet.
2. De spotprijs werd via `zip` op positie gekoppeld en kwam zo van de verkeerde munt.
3. Na een funding-stop opende en sloot hij om en om.
4. De hedge herstelde zich niet zonder marge.
5. Er was geen grens op de ouderdom van de meting.
6. Hij handelde los van het register en zonder geboekte inleg.
7. De hefboom van 3x rekte het kader van 2x op, en het liquidatiegetal klopte niet.
8. Kleine punten: modus `None`, 99,5% spotkoop, de hold op de master, overzicht-groep, `signing_client=None`.

## Reactie bouwer
1. Nu `PERP_SYMBOL = "HYPE/USDC:USDC"`. Toets `test_perp_symbool_bestaat_via_de_echte_lookup` draait de echte `_lookup_symbol` op een vastgelegde markets-dict van HL (`tests/fixtures/hl_markets_hype.json`) en toont dat `"HYPE"` None geeft. Mutant terug naar `"HYPE"` → rood.
2. `spotprijs()` koppelt op `ctx["coin"] == "@107"`. Toets met echte HL-ctx (`tests/fixtures/hl_spot_ctx.json`, omgekeerde volgorde plus een vreemde regel) toont ook dat de zip-koppeling een andere prijs geeft. Mutant → 2 rood.
3. Afbouwen zet de vlag `afgebouwd` als eerste stap. Daarna opent hij nooit meer, ook niet bij positieve funding. Openen weigert bovendien bij negatieve funding. Toets `test_afbouwen_is_blijvend_over_drie_cycli` (4 cycli, 1 melding) plus twee plan-toetsen. Mutanten → rood.
4. Bij openen gaat de marge eerst (`verdeel_kas` vóór `spot_koop`). Bij een scheve hedge zonder marge wordt eerst de spot teruggebracht naar het doel en de kas naar perp gezet, en pas dan de short geplaatst. Toetsen `test_cyclus_opent_gehedged_marge_eerst`, `test_scheve_hedge_zonder_marge_…` en `…_zonder_kas_verkoopt_eerst_spot`. Mutanten → rood.
5. `lees_state()` geeft onmeetbaar bij open benen en een meting ouder dan 1 uur. `run_cycle` meet ook als het subsysteem uit staat, dus "uit" maakt de meting niet oud. Toetsen met en zonder open benen. Mutant → rood.
6. Openen alleen met `register_live()` en inleg > 0. Toetsen `test_niet_openen_zonder_live_register` en `…_zonder_geboekte_inleg`. Mutanten → rood. De flow wordt geboekt met de tijd van de overboeking.
7. Teruggebracht binnen het kader: doel 1,5x, band [1,0x; 2,0x], HL-instelling 2x. Boven 2x stuurt hij altijd bij (`test_net_boven_2x_stuurt_bij`). Liquidatiegetal gecorrigeerd: vanaf 2x ~+43% binnen één cyclus. Kosten: de opbrengst op kapitaal is 0,6 × funding in plaats van 0,67 ×, dus ~10% minder.
8. Kleine punten:
   - modus `None` wordt geweigerd (toets);
   - spotkoop met 97%;
   - het overzicht heeft een eigen groep "HYPE-basis";
   - de hold van $26,61 is onverklaard en raakt de overboeking niet (er is ~$118 vrij);
   - `signing_client=None` na "does not exist" kan op deze wallet pas na de storting niet meer optreden. Niet aangepast.

Toetsen: 41 in `test_basis_hype.py`, 73 over de drie bestanden.

**r2 (2026-10-06): GO-mits.** Voorwaarden:
1. Boven 2x kon de short groter worden als er spot-USDC lag.
2. De noodschakelaar was niet getoetst via `run_cycle`.

Klein:
- het terugzetten van de foutenteller verbergt een patroon van afwisselend fout en goed;
- flow pas boeken als het geld zichtbaar is;
- spotfill nog niet zichtbaar;
- het aantal toetsen in de tekst.

Reactie r2:
1. In de tak `h > LEV_MAX` geldt nu altijd `dq = min(dq, -$11/px)`. Toets `test_boven_2x_met_losse_spot_usdc_wordt_short_toch_kleiner`.
2. Toets `test_noodschakelaar_werkt_via_run_cycle` leest de echte sleutel via `get_candidate_value` en verwacht reduceOnly plus de vlag `afgebouwd`.
3. Nieuwe rem: na ≥ 12 handelende cycli in 24 uur handelt hij niet meer, met één melding. Meten gaat door. Toets `test_rem_na_te_veel_handelende_cycli`.
4. Volgorde overgenomen: eerst de overboeking, dan het saldo zien, dan pas de flow boeken.
5. `time.sleep(2)` na de spotkoop.
6. Toetsaantal in de tekst gecorrigeerd.

Tweede tranche: een regel "kas inzetten" volgt bij die stap, met een eigen A1.
