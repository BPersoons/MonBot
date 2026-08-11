# Research — scorekaarten

Papieren analyse van kandidaat-namen en ETF's, vanaf 2026-08-10. Geen kapitaal nodig, geen broker nodig.

**Doel:** over 6 maanden kunnen toetsen of onze selectie de wereld-ETF verslaat. Dat vraagt geen geld — het vraagt gescoorde namen, een vastgelegde datum en een prijs. Zie de poort in het plan: *6 maanden · ≥20 gescoorde namen · versla de wereld-ETF over dezelfde periode.*

## Stand per 2026-08-11

**20 van 20 namen gescoord — het aantal is gehaald.** Vier screenronden, ~300 namen door de laag-1-screen, alle twintig met prijs én benchmarkprijs (URTH $210,11 op 2026-08-10). Verdeling: **15 VOLGEN · 5 AFVALLER · 0 KOOPBAAR**.

Wat rest is tijd. De poort valt rond **2027-02-10** (zes maanden na de eerste regel). Tot die tijd: maandelijks `python research/track.py meet`, en herscoren zodra de cijfers landen — `python research/track.py due`. Eerstvolgende: **DOCU op 2026-09-03**, de rest eind okt / begin nov.

Nul KOOPBAAR is geen storing maar de uitkomst van twee dingen: bijna niets stond onder zijn 200-daags gemiddelde (22% van 299 namen), en waar dat wél zo was, waren de marges meestal mee omlaag gegaan. **LDOS staat het dichtst bij koopwaardig.**

## Werkwijze

1. **Kandidaat komt uit een screen**, niet uit een onderbuikgevoel. Bron: holdings van thema-ETF's, toeleveranciers/klanten van bekende namen, nieuwe noteringen.
2. **Poorten eerst** (binair). Faalt er één → AFVALLER, geen verdere analyse. Scheelt tijd en voorkomt dat je jezelf een verhaal aanpraat.
3. **Zes dimensies, elk met een getal.** Geen getal gevonden = `?` = niet geanalyseerd. Eén `?` blokkeert KOOPBAAR. Dit is de belangrijkste regel op deze pagina.
4. **Bear-case apart opbouwen.** Niet "is dit goed?" vragen — één ronde de koopcase bouwen, één ronde de verkoopcase, dan pas verzoenen. LLM's zijn meegaand; deze scheiding is de tegenkracht.
5. **These-breuk-voorwaarden vóór aankoop opschrijven.** Achteraf verzin je ze naar de koers.
6. **Kaart + ledger-regel opslaan.** De ledger maakt het toetsbaar; zonder prijs-op-scoredatum kun je later niets meten.

## Poorten (binair)

| Poort | Eis | Waarom |
|---|---|---|
| Overleving | Kasruimte ≥ 3 jaar, óf winstgevend | Doodsoorzaak #1 is dat het geld op is vóór de these uitkomt |
| Overlap | Zit niet al zwaar in de kern-ETF | Anders is het concentratie, geen blootstelling |
| Liquiditeit | Genoeg dagvolume om in/uit te komen | Bij deze omvang zelden bindend |

**Kasruimte is exact gedefinieerd** (na de fout in ASTS-kaart 1):

```
burn_per_kwartaal = |operationele kasstroom| + capex        ← kasstroomoverzicht
kasruimte_jaren   = kas / burn_per_kwartaal / 4
```

**Niet** het nettoverlies uit de winst-en-verliesrekening. Bij kapitaalintensieve bedrijven is capex de echte verbranding — bij ASTS scheelde dat een factor 2,4 (4,6 jaar → 1,9 jaar) en het verschil besliste de poort.

## Bij twijfel: niet kopen (Bart, 2026-08-11)

Grensgevallen hoeven niet. Er zijn veel kandidaten, dus de kosten zijn asymmetrisch: een gemiste winnaar kost je een kans, een gekochte verliezer kost je geld. **Twijfel = wachten op een lagere prijs of op beter bewijs, niet instappen "omdat het bijna past".**

Praktisch: een poort wordt **nooit opgerekt omdat hij ongelegen uitkomt**. Deugt de regel niet, dan pas je hem aan vóór de volgende ronde en loop je alle kaarten opnieuw langs — nooit ad hoc voor de naam die je toevallig leuk vindt. Dat is exact de fout die dit project eerder maakte met zelf-versoepelende gates (zie `feedback_adaptive_gates_must_decay`).

## Dimensies (1-5)

| # | Dimensie | Wat je meet |
|---|---|---|
| 1 | Rol in de keten | Waar zit het, en kan iemand eromheen? |
| 2 | Marge + richting | Bruto/operationeel, stijgend of dalend. Dalend = moat erodeert |
| 3 | Concurrentie-dynamiek | Marktaandeel én de trend erin |
| 4 | Schaalbaarheid | Groeit omzet sneller dan kosten? Kapitaalintensiteit |
| 5 | Uitvoering | Beloofde mijlpalen gehaald of gemist |
| 6 | Waardering | Wat zit er al in de prijs? |

`5` structureel voordeel · `4` sterk · `3` gemiddeld · `2` zwak · `1` structureel nadeel · `n.v.t.` niet van toepassing · `?` niet geanalyseerd

## Verdict

- **KOOPBAAR** — alle poorten PASS, geen `?`, geen dimensie op `1`, waardering ≥ 3
- **VOLGEN** — poorten PASS maar iets is zwak. **Wachtvoorwaarde verplicht**: bij welke prijs of gebeurtenis wordt dit KOOPBAAR?
- **AFVALLER** — een poort faalt, of de these houdt geen stand

**Wanneer blokkeert een `2`?** (Bart, 2026-08-11, na het NTCT-grensgeval)

> Een dimensie op `2` blokkeert KOOPBAAR **niet** — behalve wanneer die dimensie het beslissende getal levert. Staat de dimensie waarop `deciding_number` rust op ≤2, dan is het VOLGEN.
>
> **Tiebreak** (Bart, 2026-08-11, na OTEX en LDOS): is er twijfel over wélk getal beslissend is, dan telt **het getal dat het risico beschrijft, niet het getal dat de kans beschrijft.** Zonder deze afspraak bepaalt de formulering het verdict — bij LDOS gaf "operationele winst −5,5%" VOLGEN en "guidance op consensus terwijl de koers −35% staat" KOOPBAAR, op precies dezelfde cijfers. De keuze voor de risicokant sluit aan bij *bij twijfel niet kopen*.

De regel gebruikt wat de kaart toch al moet opschrijven (*welk getal beslist*), dus er komt geen veld en geen drempel bij. Het alternatief — élke `2` blokkeert — is bewust verworpen: elk echt bedrijf heeft een zwakke plek, dus die lezing zet KOOPBAAR structureel op nul. Dat is exact het zelf-dichtslaande patroon dat dit project al drie keer nekte (PerformanceAuditor, EXP-002, de dead zone na de redesign — zie `feedback_adaptive_gates_must_decay`). Een raamwerk dat nooit "ja" zegt, toetst nooit of zijn "ja" deugt.

*Toegepast op de eerste zes kaarten (2026-08-11): geen enkel verdict verandert.* NTCT blijft VOLGEN — het beslissende getal (+4% eigen groei tegen +8,9% marktgroei) **is** dimensie 3, en die staat op 2. Bij ITRI, MYRG en PLPC lag er al een `?` of een `1`, dus de regel was daar niet bindend.

## De divergentie-screen (Bart, 2026-08-11)

Bart's toevoeging: de kans zit in bedrijven met **negatief handelaarssentiment terwijl de marges en winst dat niet laten zien**. De koers is dan sentiment-gedreven, niet fundamenteel — en dus laag ten opzichte van wat het waard is.

Dat is een goede en toetsbare stelling. **Classificeer bij elke koersdaling de oorzaak** voordat je koopt:

| Situatie | Actie | Waarom |
|---|---|---|
| Koers omlaag · marges/EPS vlak of stijgend · geen negatieve verrassing | **KOOP-kandidaat** | Sentiment-gedreven daling. Dit is de kans |
| Koers omlaag · kwartaal in lijn of beter | **KOOP-kandidaat** | Onderreactie; drift loopt historisch de goede kant op |
| Koers omlaag · **kwartaal tegengevallen** | **NIET KOPEN**, minimaal 1-2 kwartalen wachten | Zie hieronder |
| Koers omlaag · marges dalen structureel | **AFVALLER** | Fundamentele verslechtering, geen sentiment |

**De derde rij is een correctie op de intuïtie** ("als ze tegenvallen en de prijs zakt, is dat misschien ook een kans"). Post-earnings announcement drift is een van de best gedocumenteerde anomalieën in de financiële literatuur: koersen blijven ná een winstverrassing **in de richting van die verrassing** doordrijven, wekenlang tot maandenlang. En de **neerwaartse drift na een tegenvaller is sterker dan de opwaartse na een meevaller**. Een gemiste kwartaalverwachting kopen is dus tegen de drift in gaan — precies de vallende-messen-variant waar ook onze eigen sleeve-data voor waarschuwt (37% van de posities ging >20% onder water; 54% van individuele aandelen bereikt zijn oude top nooit meer).

Niet elk kwartaal hoeft schitterend te zijn — klopt. Maar *in lijn* is iets anders dan *tegengevallen*, en die grens is precies de scheidslijn.

**Meetbaar maken:** per kandidaat over hetzelfde venster (3-6 maanden) vastleggen — koersverandering · brutomarge-trend over 4 kwartalen · teken van de winstverrassing laatste 2 kwartalen · omzetgroei-trend. **Divergentie = koers fors negatief terwijl de andere drie vlak of positief zijn.**

> **Dit verbetert de sleeve die al werkt.** `utils/thematic_exposure_lab.py` koopt dips op `pullback_z ≥ 1.5` — puur op prijs, zónder fundamentele toets. Deze screen eroverheen is precies de scheidslijn tussen dips die herstellen en dips die dat nooit doen. Van de bestaande onderdelen is dit de goedkoopste echte verbetering.

Dit maakt ook "ondergewaardeerde groeibedrijven" concreet: groei intact + koers omlaag = waardering samengedrukt zonder dat het bedrijf slechter werd.

## Bestanden

```
research/
  README.md               deze pagina
  scorecard_template.md   lege kaart
  ledger.json             machine-leesbaar: datum, prijs, score, verdict, benchmark
  cards/<TICKER>.md       de analyse per naam
  track.py                meet + signaleer (geen oordeel)
  tracking.json           snapshots van track.py meet
```

## Cadans

```bash
python research/track.py meet    # maandelijks: elke regel tegen de wereld-ETF
python research/track.py due     # welke kaarten zijn toe aan herscoring?
```

`meet` haalt koersen via yfinance, rekent elk aandeel af tegen de benchmark op de scoredatum, groepeert het resultaat per verdict en waarschuwt zodra een prijs-wachtvoorwaarde (`wait_price_below`) geraakt wordt. `due` gebruikt de echte earnings-datum per naam, met een 90-dagenvangnet.

**Het script scoort niets en beslist niets** — het meet en signaleert. Het oordeel blijft een handmatige `/scorecard <TICKER>`-aanroep. Dat is bewust: `docs/PLAN_2026-08.md` §2 zet automatisering van de onderzoekscadans pas op de agenda vanaf ~€100k.

Drie ritmes:

| Ritme | Wat |
|---|---|
| elke 1-2 weken | nieuwe namen screenen en scoren, tot de 20 vol is |
| **op de cijfers** (niet op de kalender) | `due` → `/scorecard <TICKER> rescore` |
| maandelijks | `meet` |

**De ledger is het punt.** Elke regel legt vast wat we vonden, op welke datum en tegen welke prijs — inclusief de benchmarkprijs op diezelfde dag. Over zes maanden rekent dat af of hoge scores écht aan goede uitkomsten voorafgingen. Zonder die regels is het een verzameling meningen.

---

# Rekencontroles — hoe we fouten eerder vinden

De overlevingsfout in ASTS-kaart 1 (factor 2,4 mis) is gevonden doordat er toevallig nieuwe data verscheen, **niet doordat een controle hem ving**. Dat is het echte probleem: het was geen rekenfout maar een **definitiefout** — de aritmetiek klopte, de gekozen maatstaf niet. Dat type glipt door elke plausibiliteitstoets, want het antwoord *ziet er goed uit*.

Vier controles, elk verplicht bij elke kaart.

### 1. Bron-tag per getal — vangt maatstaf-mismatch

Elk getal krijgt: **welk document · welke regel · welke periode.**

Een kasvraag hoort beantwoord met een getal uit het **kasstroomoverzicht**. Was dat opgeschreven bij ASTS ("bron: winst-en-verliesrekening, nettoverlies"), dan was direct zichtbaar dat een *kas*vraag met een *winst*getal werd beantwoord. **Type vraag ≠ type bron = fout.**

| Vraag gaat over | Verplichte bron |
|---|---|
| Kas, runway, burn | Kasstroomoverzicht |
| Marge, winst | Winst-en-verliesrekening |
| Verwatering | Aandelenaantal (specificeer: uitstaand of gewogen gemiddeld, en welke klasse) |
| Waardering | Marktkap ÷ de betreffende regel, beide met peildatum |

### 2. Reconciliatie tegen de werkelijkheid — de sterkste controle

**Klopt mijn aangenomen burn met de gerapporteerde kasverandering tussen twee kwartalen?**

Bij ASTS: Q1 kas $3,5 mrd → Q2 $3,7 mrd. Bij een burn van $191M/kwartaal had de kas moeten *dalen*. Hij **steeg** — dus werd er kapitaal opgehaald, dus was de burn hoger dan aangenomen. **Dat stond in kaart 1 en ik heb het niet gecontroleerd.** Deze ene toets had de fout meteen gevangen, zonder nieuwe data.

Regel: bij elke runway-claim de kasbeweging over twee gerapporteerde kwartalen ernaast leggen. Verschil >30% tussen aangenomen en gerealiseerde burn → stoppen en uitzoeken.

### 3. Twee onafhankelijke routes voor elk poortgetal

Bereken het beslissende getal op twee manieren die niet dezelfde bron delen. Wijken ze meer dan 30% af, dan is er een definitieprobleem — niet een afrondingsprobleem.

*Runway route A:* kas ÷ (opex + capex). *Route B:* kas ÷ gerealiseerde kasdaling per kwartaal.

### 4. Adversariële ronde op de cijfers, niet op het verhaal

We doen al bull-case en bear-case apart. Dat toetst de *these*. Voeg een derde ronde toe met één opdracht: **"welk getal hier beantwoordt een andere vraag dan er gesteld is?"** Geen mening over het bedrijf — alleen aanvallen op de maatstaven, de peildata en de eenheden.

### 5. Nooit een management-cijfer voor een poortberekening

Toegevoegd 2026-08-11, na de derde fout in dezelfde kaart. De herscoring gebruikte managements **">$3,7 mrd pro forma cash"** uit het persbericht. De 10-Q-balans zei **$2,72 mrd** — een verschil van bijna $1 mrd, en genoeg om "grensgeval" te veranderen in "faalt ruim".

**"Pro forma", "adjusted", "run-rate" en "annualized" zijn geen feiten maar presentaties.** Voor elk poortgetal geldt: balans of kasstroomoverzicht, uit de 10-Q/10-K. Persberichten en earnings calls mogen de *context* leveren, nooit het getal waarop een poort draait.

### Wat de controles in de praktijk vingen (ASTS, 3 rondes)

| Controle | Resultaat |
|---|---|
| 1. Bron-tag | Ving 2 fouten: W&V-getal voor een kasvraag; persbericht-getal voor een balansvraag |
| 2. Reconciliatie | Ving fout 1 zonder nieuwe data — kas steeg terwijl de aangenomen burn een daling eiste |
| 3. Twee routes | ✅ Burn-schatting klopte binnen 1% (guidance vs gerealiseerd). Het was de *kas* die fout was — nuttig signaal: het bevestigde welke helft van de breuk niet deugde |
| 4. Cijfer-aanval | "$3,7 mrd pro forma" beantwoordt "hoeveel hopen ze" op de vraag "hoeveel hebben ze" |
| 5. Geen management-cijfers | Nieuw, direct uit deze les |

Drie rondes, drie fouten, alle drie **definitiefouten** — nooit aritmetiek. Dat is het patroon om op te jagen. De 10-Q loste bovendien de openstaande `?`-punten op: aandelenklassen (A 299,8M · B 11,2M · C 78,2M) verklaarden de marktkap-discrepantie volledig.
