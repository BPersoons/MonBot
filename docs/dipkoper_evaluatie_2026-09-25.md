# Dip-koper — voorbereiding op de evaluatie van 25-09-2026

*Gemeten 20-09. Dit is de onderbouwing voor het besluit: doorgaan, stoppen, of anders inrichten.*

De dip-koper (`thematic_exposure`, wallet `0xBd6c`, xyz-perp-dex) koopt terugvallen in
Amerikaanse largecaps binnen vastgelegde thema's, met een fundamentele check bij instap en
een software-stop op −25%.

## 1. Wat het potje heeft gedaan

Meetperiode **19-07 t/m 20-09 (60 dagen)**. Vóór 19-07 is de reeks onbruikbaar: op die dag
sprong het potje van $1.247,99 naar $255,00 door een wijziging in de meetdefinitie, niet
door een verlies.

| maat | waarde |
|---|---|
| budget bij aanvang | $255,00 |
| kas nu | $12,70 |
| open posities (6) nu | $269,05 (kostprijs $271,98) |
| **potje nu** | **$281,75** |
| **resultaat** | **+$26,75 = +10,49%** (geannualiseerd ~+80%) |

Dit is de **geldmaat**: kas plus posities tegen het budget. Winnaars én verliezers zitten
erin, want de kas weerspiegelt wat er werkelijk is afgerekend.

## 2. Waartegen je het moet afzetten

| vergelijking | 60 dagen | verschil |
|---|---|---|
| **dip-koper** | **+10,49%** | — |
| wereldindexfonds WEBN (USD) | +2,44% | **+8,05pp** |
| dezelfde vijf namen simpelweg vasthouden | +1,64% | **+8,85pp** |

Die laatste regel is de scherpste: het gaat niet om de vraag of largecap-tech het goed deed
(dat deed het nauwelijks: BABA −5,9%, AVGO −5,4%, TSLA −1,4%, GOOGL −0,6%, alleen ORCL
+21,6%), maar of het **timen van terugvallen en het afrekenen van winst** iets toevoegt.
In dit venster: ja, ongeveer 9 procentpunt.

## 3. Wat deze cijfers niet zeggen

- **De steekproef is klein.** 12 trades, 6 gesloten, 60 dagen. Met zo weinig posities is
  het resultaat padafhankelijk; één ORCL-trade kan het beeld dragen.
- **Het is dezelfde weddenschap als de index.** Gemeten beta tegen WEBN is **1,08**
  (wekelijks, Dimson-gecorrigeerd, 2 jaar). Als spreiding voegt dit potje niets toe; het is
  een geconcentreerde inzet op Amerikaanse tech bovenop wat WEBN al bezit.
- **De eerdere validatie was negatief.** Op 16 jaar echte aandelendata gedroeg dezelfde
  regelset zich index-achtig en verloor hij in een dalende markt
  (memory `feedback_sleeve_validation`). Dit venster (60 dagen, stijgende markt) weerlegt
  dat niet.
- **De vergelijking "dezelfde namen vasthouden" gebruikt de vijf namen die nú open staan.**
  De zes gesloten namen zaten daar niet in. Een zuiverdere toets rekent per positie het
  eigen resultaat af tegen het aandeel over exact dezelfde houdperiode — dat staat hieronder
  als open punt.

## 4. Meetproblemen die vóór het besluit opgelost moeten zijn

1. **Het handelslogboek mist afsluitingen.** `trade_log.json` kent 6 gesloten dip-trades
   (+$15,78), het positiebestand kent er 8. **CRWV (−25,2%) en MRVL (−3,6%) — de twee
   verliezers — hebben in het positiebestand geen `realized_pnl_usd`.** Wie op het
   handelslogboek rekent, meet dus alleen overlevers. De geldmaat in §1 heeft hier geen
   last van, maar elke analyse per trade wel.
2. **De optelling klopt niet.** De som van de posities is $19,57, het veld
   `realized_pnl_usd` in hetzelfde bestand zegt $27,68. Verschil $8,11.

   **Opgehelderd op 21-09 met de Hyperliquid-fills** (`scripts/dipkoper_resultaat.py`, de
   bron voor elke evaluatie per naam):

   | | bedrag |
   |---|---|
   | gerealiseerd op de eigen wallet sinds 23-07 | +$29,67 |
   | fees | −$0,16 |
   | funding | −$1,79 |
   | **netto** | **+$27,72** |

   - Het positiebestand houdt per ticker één vak bij. Een tweede ronde in dezelfde naam
     overschrijft de eerste. CRCL (+$4,71), ORCL (+$6,87) en TSLA (+$1,76) verdwenen zo uit
     de som.
   - CRWV (−$3,17) sloot op 29-07, vóór het resultaat per positie werd bijgehouden.
   - Samen verklaart dat de som per positie op $0,07 na.
   - Het totaalveld boekt tegen de markprijs, niet tegen de fillprijs (−$2), en telt geen
     fees of funding. Dat het toch bijna gelijk is aan de netto uitkomst, is toeval.
   - MRVL (−$0,99) en een eerste CRWV-ronde (+$0,07) liepen op 17 en 18-07 nog via de
     hoofdwallet, vóór de eigen wallet bestond. Het echte verlies op MRVL was dus $0,99, niet
     "−3,6% van een positie".
   - **Gevolg voor het besluit:** het gerealiseerde resultaat is +$27,72 op het budget van
     $255, verdeeld over 9 gesloten rondes (8 winst, 1 verlies). Open posities staan in §1.
   - **Nog te doen (geldcode, A1):** de dip-koper moet een gesloten ronde bewaren vóór hij
     dezelfde naam opnieuw opent.
3. **Er zijn geen stromen geboekt.** `data/flows.json` bestaat niet; kapitaal dat het potje
   in- of uitging staat nergens. Nu is dat nog te overzien (budget $255, geen bijstortingen),
   maar bij elke volgende verandering verdwijnt de vergelijkbaarheid.

## 4b. De lange termijn: 16 jaar, eerlijk vergeleken (gemeten 21-09)

`scripts/sleeve_harness.py --aandelen` over 2010–2026, met dezelfde regels als live,
0,1% kosten per kant. De versie **zonder** herbeleggen koopt 16 jaar lang posities van
vaste $42,50 en laat de winst als kas staan; die meet daardoor vooral inactief geld. Voor
de schaalvraag telt de versie **mét** herbeleggen:

| 2010–2026 | rendement | per jaar | maximale daling |
|---|---|---|---|
| dip-koper, winst herbeleggen | **+1.672%** | ~18,9% | ~27% (zonder herbeleggen gemeten) |
| Nasdaq-100 vasthouden (QQQ) | +1.666% | 18,8% | 35,1% |
| wereldindex (URTH, sinds 2012) | +448% | 12,3% | 34,0% |

**De dip-koper evenaart de Nasdaq-100 — met 17 aandelen die met de kennis van nu zijn
gekozen** (NVDA, AMD, PLTR, MU …). Met achteraf gekozen winnaars alleen de index halen,
betekent dat de koopregels op lange termijn niets toevoegen boven de index. De voorsprong
van 60 dagen (§2) is daarmee waarschijnlijk beta en geluk, geen structureel voordeel.
Het enige verschil in zijn voordeel: een wat kleinere maximale daling.

**Ook getoetst en gestopt:** een marktfilter (alleen dips kopen als de Nasdaq-100 boven
zijn 200-daags gemiddelde staat). Vooraf vastgelegd: wint alleen als het rendement gelijk
blijft, de maximale daling minstens 25% kleiner wordt, het slechtste jaar beter is en het
standhoudt zonder de beste naam. Uitkomst: rendement +407% vs +403% (ja), daling 25,8% vs
27,5% (nee, maar 6% kleiner), 2022 −8,8% vs −12,9% (ja), zonder NVDA +346% vs +410% (nee).

## 5. Wat er op 25-09 te beslissen valt

- **Doorgaan op $255?** De meting is positief maar te kort om skill aan te tonen.
- **Opschalen?** Niet voordat punt 4 is opgelost én er meer trades zijn: bij 12 trades is
  een voorsprong van 9pp statistisch nauwelijks te onderscheiden van geluk.
- **Stoppen?** Dan gaat $281,75 terug naar het rentepotje, wat ~$8/jaar aan rente oplevert
  en de blootstelling aan Amerikaanse tech met $272 verlaagt.

**Advies van de bouwer (bijgesteld 21-09):** **niet opschalen.** Over 16 jaar evenaart de
dip-koper de Nasdaq-100 met achteraf gekozen namen; er is geen aangetoond voordeel boven de
index, en opschalen is dan vooral meer tech-beta kopen via een duurdere route. Doorgaan op
$255 kan als proeftuin (hij kost weinig en levert meetdata), maar de motor moet zijn tijd
steken in bronnen die *niet* afhangen van de richting van tech-aandelen.
