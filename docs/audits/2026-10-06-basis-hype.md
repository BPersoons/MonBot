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
| Hefboom op de short | doel 2x, bijsturen buiten [1,4x, 3x] | `LEV_*` |
| Volgorde openen | eerst spot kopen, dan short ter grootte van de gekochte spot | `plan`, `_voer_uit` |
| Koers omhoog (hefboom > 3x) | eerst short kleiner (reduceOnly), dan spot verkopen, dan USDC naar perp | `plan` |
| Koers omlaag (< 1,4x) | USDC naar spot, spot kopen, short groter | `plan` |
| Hedge scheef > 3% en > $11 | short volgt spot (groter, of kleiner met reduceOnly) | `plan` |
| Afbouwen | schakelaar `basis_hype_afbouwen`, of verlies ≥ 50% van de inleg (proeftuinregel), of funding over 7 dagen negatief: short sluiten (reduceOnly), spot verkopen | `plan` |
| Uit | `subsystem_basis_hype_enabled=false`: hij doet niets, de benen blijven gehedged staan | `run_cycle` |
| Fouten | elke fout wordt geteld; na 3 op rij één Telegram-melding; de volgende cyclus plant opnieuw vanuit de werkelijke stand | `run_cycle` |
| Unified account | geweigerd, want daar zou accountValue 0 zijn en de hefboom oneindig lijken | `toestand` |

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

## Reactie bouwer
*(per open punt: opgelost in `<hash>` of weerlegd met bewijs)*
