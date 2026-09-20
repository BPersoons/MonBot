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
   `realized_pnl_usd` in hetzelfde bestand zegt $27,68. Verschil $8,11, oorzaak onbekend.
3. **Er zijn geen stromen geboekt.** `data/flows.json` bestaat niet; kapitaal dat het potje
   in- of uitging staat nergens. Nu is dat nog te overzien (budget $255, geen bijstortingen),
   maar bij elke volgende verandering verdwijnt de vergelijkbaarheid.

## 5. Wat er op 25-09 te beslissen valt

- **Doorgaan op $255?** De meting is positief maar te kort om skill aan te tonen.
- **Opschalen?** Niet voordat punt 4 is opgelost én er meer trades zijn: bij 12 trades is
  een voorsprong van 9pp statistisch nauwelijks te onderscheiden van geluk.
- **Stoppen?** Dan gaat $281,75 terug naar het rentepotje, wat ~$8/jaar aan rente oplevert
  en de blootstelling aan Amerikaanse tech met $272 verlaagt.

**Advies van de bouwer (20-09):** doorgaan op de huidige omvang, punt 4 repareren, en pas
bij ≥ 25 gesloten trades opnieuw wegen. Dit potje is geen spreiding maar een weddenschap;
zolang hij klein is, is dat te dragen — en hij is nu het enige onderdeel dat meer verdient
dan de rente.
