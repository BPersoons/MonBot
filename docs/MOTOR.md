# De motor — van idee naar winst, en weer terug

*Vastgesteld 2026-09-21 op verzoek van Bart: "Ik wil altijd een proeftuin houden om nieuwe
ideeën te testen. Daaruit vloeien ideeën door naar schalen. Deze motor moet continu blijven
lopen. Nieuwe ideeën kunnen tweaks zijn van iets dat al winst maakt, of een hele nieuwe
opbrengstbron."*

## Waarom

Tot nu toe liepen ideeën als losse projecten: M3 (Fluid), M5 (HLP), M6 (basis). Elk kreeg
zijn eigen plan, zijn eigen poort en zijn eigen audit, en daarna stond de motor stil tot het
volgende idee. Ideeën stonden verspreid over `docs/PLAN_2026-08.md`, `docs/MASTERPLAN.md` en
het geheugen van de bouwer. Het gevolg: veel werk, weinig doorstroom.

De motor lost dat op met **vaste treden, vaste poorten en een vast ritme**. Er staat altijd
iets op elke trede, en elk idee eindigt ergens: geschaald of gestopt, met de reden erbij.

## De vijf treden

| trede | wat gebeurt er | geld | poort naar de volgende trede |
|---|---|---|---|
| **0 · idee** | één regel hypothese, de bron, en wat het zou opleveren | €0 | de hypothese is meetbaar en heeft een benchmark |
| **1 · papier** | backtest of analyse op historische data, na kosten | €0 | beter dan de benchmark na kosten, in ≥ 2 marktregimes, niet gedragen door één trade |
| **2 · schaduw** | draait live mee zonder geld, 2–4 weken | €0 | het schaduwresultaat ligt binnen de marge van het papieren resultaat |
| **3 · proeftuin** | klein live, uit het proeftuinkapitaal | **$500 totaal** (Bart 22-09); per potje het minimum dat de strategie niet vervormt | de poort uit het register: aantal trades of dagen, geldmaat tegen de benchmark, gecorrigeerd voor beta |
| **4 · schalen** | eigen potje, meer kapitaal | **besluit Bart** | doorlopende bewaking en kill-regels |

Een idee mag een trede overslaan als de trede niets toevoegt (een renteprotocol heeft geen
schaduwfase nodig), maar dat staat dan expliciet in het register.

**Twee soorten ideeën, dezelfde treden:**
- **Tweaks** op iets wat al op trede 3 of 4 staat (een andere stop, een ander thema, een
  andere instapregel). Die vergelijken we met de huidige versie, niet met de index.
- **Nieuwe opbrengstbronnen** (een nieuw protocol, een nieuwe markt, een nieuwe strategie).
  Die vergelijken we met de benchmark van hun potje.

## De spelregels

1. **Eén meetstandaard.** Elk experiment wordt gemeten met geld (kas + posities tegen de
   inleg), flow-gecorrigeerd, tegen zijn benchmark, en met de beta erbij
   (`scripts/blootstelling.py`). Rendement van een protocol komt uit de share price
   (`utils/rendement.py`). Nooit uit een lijst trades alleen — die mist de verliezers
   (memory `feedback_meet_het_potje_met_geld`).
2. **Het proeftuinkapitaal is $500 in totaal** (Bart 22-09). Geen vast maximum aantal
   experimenten: het kapitaal begrenst. Elk potje mag **hooguit 50%** verliezen voor het stopt,
   dus het verliesbudget blijft $250 (alarm $125). Per potje het **minimum**: elke geplande order
   minstens 2× de minimumorder van de beurs (Hyperliquid $10, dus ~$50-100 per potje). Vaste
   kosten per order (DeGiro ~€1-3) zijn experimentkosten en mogen; bij schalen dalen ze relatief.
2b. **Geld alleen waar geld het enige is dat ons iets leert.** Een koop-en-houd-these (een
   mandje, een losse naam) meet je vooruit op papier even goed als met geld; dat is gratis en
   onbeperkt (de scorekaart doet het al). Een publiek meetbare bron (HLP-vault, funding) meet je
   in de schaduw. Echt geld is nodig waar onze EIGEN uitvoering meespeelt: stops, deelverkopen,
   funding op een positie, fills, en fouten in de code (zoals het ontbrekende reduceOnly op 21-09).
2c. **Parallel, niet na elkaar.** Papier en schaduw draaien zoveel tegelijk als er ideeën zijn.
   Tijd is de schaarse factor, niet geld: een idee wacht nooit op een ander idee.
2d. **Hoe meer potjes tegelijk, hoe strenger de toets om te schalen.** Bij veel experimenten wint
   er altijd één door toeval; schalen vraagt minstens 6 maanden vooruit gemeten resultaat.
3. **Geen geld vóór de meter er staat.** Een experiment gaat pas naar trede 3 als zijn poort
   meetbaar is in code (de les van M3, 19-09).
4. **Een poort wordt nooit opgerekt.** Haalt een experiment zijn poort niet, dan stopt het.
   Het mag later opnieuw beginnen met nieuwe data of een nieuwe hypothese — niet met een
   lagere lat.
5. **Elk stoppen komt in `docs/besluiten.md`**, met de data. Zo komt een gestopt idee niet
   terug zonder nieuwe informatie.
6. **Schalen is altijd een besluit van Bart.** De bouwer levert de meting en een advies.
7. **Geldcode gaat langs de controle-agent** (A1), elke kapitaalbeweging ook (A2), op elke trede.

## Het ritme

| wanneer | wat |
|---|---|
| **elke werkronde** (`/werkronde`) | live experimenten langs hun kill-regels; de motor tonen (`python -m utils.motor`) |
| **elke week** | minstens één idee een trede verder, of gestopt |
| **elke maand** | per experiment op trede 3 en 4 een oordeel: doorgaan, stoppen of promoveren |
| **per kwartaal** | opschalen of afbouwen voorleggen aan Bart |

## Waar de ideeën vandaan komen

- **Tweaks van wat werkt.** Nu alleen de dip-koper (+10,5% in 60 dagen tegen +1,6% voor
  dezelfde namen vasthouden, maar 12 trades).
- **Het MASTERPLAN** (bronnen A–F): funding en basis, market-making-vaults, vaste rente
  (Pendle), jonge-marktinefficiënties (xyz-lab), early incentives, optie-inkomen.
- **Van buiten**, zoals de handelsprompts van 17-09. Die gaan door dezelfde treden, en
  worden gefilterd op wat al weerlegd is (`docs/besluiten.md`).

## Waar de experimenten draaien

De VM draait 24/7 op e2-small (het dagvenster is op 21-09 door de controle-agent gestopt, zie
`docs/audits/2026-09-21-vm-venster.md`). Schaduw-experimenten met live data draaien daar.
GitHub Actions start uren te laat, dus alleen voor trage strategieën (memory
`reference_github_actions_vertraging`), zoals het maandelijkse uitstapsignaal. Trede 1 (papier)
draait lokaal of in Actions.

## Stand bij de start (21-09)

De actuele stand staat in `config/experimenten.json` (veld `trede`) en wordt getoond met
`python -m utils.motor`.
