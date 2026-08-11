# Scorekaart — papieren analyse van één naam

Scoort een kandidaat volgens het raamwerk in `research/README.md`.

> **`research/README.md` is de bron, niet deze skill.** Hier staan alleen de vólgorde, de stopmomenten en de opleverplicht. Spreken de twee elkaar tegen → README wint, en deze skill wordt bijgewerkt. Verzin hier nooit een dimensie, een poort of een drempel bij.

## Arguments

`$ARGUMENTS`

| Vorm | Betekenis |
|---|---|
| `<TICKER>` | scoor één naam volledig |
| `<TICKER> rescore` | herscoor na nieuwe kwartaalcijfers — oude ledger-regel blijft staan en krijgt `superseded_by` |
| `screen <ETF>` | lever alleen kandidaten uit de holdings van `<ETF>`, nog niet scoren |
| *(leeg)* | vraag om een ticker of om een ETF om te screenen |

## Stap 0 — laad het raamwerk

Lees vóór elke kaart, elke keer opnieuw:

1. `research/README.md` — poorten, dimensies, verdict-regels, rekencontroles, divergentie-screen
2. `research/scorecard_template.md` — de vorm van de kaart
3. `research/ledger.json` — bestaat er al een regel voor deze ticker? (dan is dit een `rescore`)

Niet uit het hoofd werken. De regels zijn drie keer aangescherpt na fouten; een verouderde kopie in je hoofd is precies hoe die fouten ontstonden.

## Stap 1 — herkomst van de kandidaat

Vastleggen wáár de naam vandaan komt: ETF-holding · toeleverancier/klant van een bekende naam · nieuwe notering. **Een naam zonder screen-herkomst is geen kandidaat** (README, werkwijze 1).

Bij `screen <ETF>`: haal de holdings op, filter op de drie dingen uit `docs/PLAN_2026-08.md` §4 — overleving, géén overlap met de kern-ETF, wéinig analistendekking — en lever een lijst. Stop daar; scoren is een aparte aanroep.

## Stap 2 — poorten (binair, dit is een stopmoment)

De drie poorten uit README. **Faalt er één → AFVALLER. Direct stoppen.** Geen dimensies, geen koopcase, geen "maar verder is het interessant". Schrijf een korte kaart met alleen de poortberekening en het beslissende getal.

Overleving is exact gedefinieerd — gebruik letterlijk deze formule, uit het **kasstroomoverzicht**:

```
burn_per_kwartaal = |operationele kasstroom| + capex
kasruimte_jaren   = kas / burn_per_kwartaal / 4
```

Winstgevend (positieve operationele kasstroom) → poort PASS zonder berekening; noteer welk kwartaal en welke regel.

**Een poort wordt nooit opgerekt omdat hij ongelegen uitkomt.** Deugt een regel niet, dan pas je hem aan vóór de volgende ronde en loop je álle bestaande kaarten opnieuw langs — nooit ad hoc voor de naam van vandaag (README; `feedback_adaptive_gates_must_decay`).

## Stap 3 — rekencontroles (vijf, alle vijf verplicht)

Voer ze uit vóór de dimensies, want ze kunnen de poortuitslag omdraaien. Uit README §Rekencontroles:

1. **Bron-tag per getal** — welk document · welke regel · welke periode. Type vraag ≠ type bron = fout. Kasvraag → kasstroomoverzicht. Margevraag → W&V. Verwatering → aandelenaantal (zeg erbij: uitstaand of gewogen gemiddeld, en welke klasse). Waardering → marktkap ÷ de regel, beide met peildatum.
2. **Reconciliatie tegen de werkelijkheid** — klopt de aangenomen burn met de gerapporteerde kasverandering tussen twee kwartalen? Verschil >30% → stoppen en uitzoeken. *Dit is de sterkste controle: hij ving de ASTS-fout zonder nieuwe data.*
3. **Twee onafhankelijke routes** voor het poortgetal, die niet dezelfde bron delen. >30% verschil = definitieprobleem, geen afrondingsprobleem.
4. **Adversariële ronde op de cijfers** — één vraag, geen mening over het bedrijf: *"welk getal hier beantwoordt een andere vraag dan er gesteld is?"* Alleen maatstaven, peildata en eenheden.
5. **Nooit een management-cijfer voor een poortberekening** — "pro forma", "adjusted", "run-rate" en "annualized" zijn presentaties, geen feiten. Poortgetallen komen uit de balans of het kasstroomoverzicht in de 10-Q/10-K. Persbericht en earnings call leveren context, nooit het beslissende getal.

Alle vijf krijgen een regel in de kaart, ook als de uitkomst "geen probleem gevonden" is. Een lege controle is een niet-uitgevoerde controle.

Marktkap: over **alle** aandelenklassen, niet alleen de verhandelde.

## Stap 4 — zes dimensies

Uit README: rol in de keten · marge + richting · concurrentie-dynamiek · schaalbaarheid · uitvoering · waardering. Schaal `5..1`, plus `n.v.t.` en `?`.

**Eén zin met een getal per dimensie.** Geen getal gevonden = `?` = niet geanalyseerd. Dat is de belangrijkste regel van de hele pagina, en `?` mag niet worden weggeschreven als een 3 omdat het onhandig staat.

## Stap 5 — divergentie-screen

Verplicht zodra de koers is gedaald. Leg over hetzelfde venster (3-6 mnd) vast: koersverandering · brutomarge-trend over 4 kwartalen · teken van de winstverrassing van de laatste 2 kwartalen · omzetgroei-trend. Classificeer met de tabel in README.

De rij die tegen de intuïtie ingaat: **koers omlaag mét een tegengevallen kwartaal → NIET KOPEN**, minimaal 1-2 kwartalen wachten. Post-earnings drift loopt door in de richting van de verrassing, en neerwaarts sterker dan opwaarts.

## Stap 6 — koopcase, verkoopcase, verzoening — in die volgorde, apart

Drie gescheiden rondes. **Nooit "is dit goed?" vragen.**

1. **Koopcase** — bouw hem zo sterk als de feiten toelaten. Waarom kan dit veelvoudig omhoog?
2. **Verkoopcase** — apart opgebouwd, *niet* als tegenwerping op ronde 1. Waarom gaat dit mislukken?
3. **Verzoening** — welke weegt zwaarder, en **welk getal beslist**. Dat getal komt in de kaart én in de ledger als `deciding_number`.

Modellen zijn meegaand; deze scheiding is de enige tegenkracht die we hebben. Het FA-gewicht staat niet voor niets op 0,20 — hógere fundamentele scores hingen in dit project samen met verlíes.

## Stap 7 — verdict

Uit README, ongewijzigd:

- **KOOPBAAR** — alle poorten PASS · geen `?` · geen dimensie op `1` · waardering ≥ 3
- **VOLGEN** — poorten PASS maar iets is zwak. **Wachtvoorwaarde verplicht:** bij welke prijs of gebeurtenis wordt dit KOOPBAAR?
- **AFVALLER** — een poort faalt, of de these houdt geen stand

**Een `2` blokkeert alleen als die dimensie het beslissende getal levert** (Bart, 2026-08-11). Staat de dimensie waarop `deciding_number` rust op ≤2 → VOLGEN. Staat er elders een `2` → blokkeert niet. Élke `2` laten blokkeren is bewust verworpen: dat zet KOOPBAAR structureel op nul, het zelf-dichtslaande patroon uit `feedback_adaptive_gates_must_decay`.

**Tiebreak bij twijfel over wélk getal beslissend is:** neem het getal dat het **risico** beschrijft, niet dat wat de **kans** beschrijft. Anders bepaalt je formulering het verdict.

**Bij twijfel: niet kopen** (Bart, 2026-08-11). Een gemiste winnaar kost een kans, een gekochte verliezer kost geld — en er zijn genoeg kandidaten. Twijfel = wachten op een lagere prijs of beter bewijs, niet "instappen omdat het bijna past".

These-breuk-voorwaarden **vóór** het verdict opschrijven, niet erna. Achteraf verzin je ze naar de koers.

## Stap 8 — opleveren (kaart + ledger, allebei)

**Kaart:** `research/cards/<TICKER>.md`, vorm van `research/scorecard_template.md`. Bij een rescore: de oude versie blijft leesbaar in dezelfde kaart, met wat er veranderde en waaróm — de methode-correcties in `ASTS.md` zijn het model.

**Ledger-regel** in `research/ledger.json` → `entries[]`. Verplichte velden:

```
ticker · name · scored_at · price_at_score · currency · market_cap_usd
benchmark_price_at_score      ← nooit null, zie hieronder
gates{survival, core_etf_overlap, liquidity}
scores{role_in_chain, margin_and_direction, competition, scalability, execution, valuation}
unanalyzed[] · verdict · deciding_number · card
```
Plus naar situatie: `wait_conditions[]` (verplicht bij VOLGEN) · `thesis_break[]` · `divergence_screen` · `source` · `superseded_by` (bij rescore) · `method_corrections[]` (als een regel is bijgesteld).

**`benchmark_price_at_score` is niet optioneel.** Zonder benchmarkprijs op de scoredatum is de regel over zes maanden niet af te rekenen, en dan is de kaart een mening in plaats van een test. Het instrument staat in `ledger.json._benchmark`; is dat nog `TODO`, gebruik dan de wereld-index-proxy die daar genoteerd staat en noteer dat de uiteindelijke DeGiro-tracker kan afwijken — de index is dezelfde.

Sluit af met: verdict · beslissend getal · wat op `?` staat · hoeveel namen er nu in de ledger staan (poort: **6 maanden · ≥20 namen · versla de wereld-ETF**).

## Waar dit eerder misging

Drie fouten in de ASTS-kaart, drie rondes, en **alle drie definitiefouten** — nooit aritmetiek. Het antwoord zag er telkens goed uit. Dat is het patroon om op te jagen:

| Fout | Wat er gebeurde |
|---|---|
| Nettoverlies voor een kasvraag | W&V-getal op een kasstroomvraag → 4,6 jaar i.p.v. 1,4 |
| Pro-forma-kas van management | Persbericht $3,7 mrd vs balans $2,72 mrd → ~$1 mrd verschil |
| Marktkap op één aandelenklasse | $21,8 mrd i.p.v. $28,4 mrd |

De les die daaruit volgt is stap 3, controle 2: **leg bij elke runway-claim de gerealiseerde kasbeweging over twee kwartalen ernaast.** Die ene toets ving de eerste fout zonder één nieuw gegeven.
