# LEU — Centrus Energy Corp.

*Gescoord: 2026-09-22 · Koers: $154,85 (slot 21-09) · Marktkap: $3,17 mrd (20,45 mln aandelen A+B) · Bron kandidaat: keten — themakaart Nucleair (`research/themes.json`, herziening 21-09): de enige beursgenoteerde westerse verrijker, dus het tolhuisje "verrijking/HALEU"*

## Poorten

| Poort | Eis | Waarde | Bron (document · regel · periode) | Uitslag |
|---|---|---|---|---|
| Overleving | `kas / (\|op. kasstroom\| + capex) / 4` ≥ 3 jaar | **11,4 jaar** op TTM (burn $41,0 mln per kwartaal = \|−$55,0\|/4 + $108,8/4); **5,5 jaar** op de capex van het laatste kwartaal ($71,6 mln) | kasstroomoverzicht 10-Q Q2 2026 + 10-K 2025 (SEC XBRL); kas $1.868,5 mln per 30-06-2026 | **PASS** |
| Overlap kern-ETF | niet al zwaar aanwezig | ≈ 0%: $3,2 mrd valt onder de large/mid-grens van WEBN; niet in de top-10 (justETF, 23-07-2026) | holdings WEBN | **PASS** |
| Liquiditeit | voldoende dagvolume | ~932.000 aandelen per dag × $155 ≈ $144 mln | yfinance, gemiddelde over 10 dagen | **PASS** |

## Rekencontroles (verplicht — zie README)

| Controle | Uitkomst |
|---|---|
| **1. Bron-tag** | Kasvraag → kasstroomoverzicht (operationele kasstroom en investeringen, SEC-tags `NetCashProvidedByUsedInOperatingActivities`, `PaymentsToAcquirePropertyPlantAndEquipment`). Waardering → marktkap ÷ W&V-regels, peildatum 21-09-2026. Aandelen: A + B (19,73 + 0,72 mln), niet alleen klasse A. |
| **2. Reconciliatie** | **Eerst NIET gesloten.** yfinance-kas Q4-25 → Q1-26: −$89,0 mln, terwijl operationele kasstroom + capex −$58,3 mln geeft (53% verschil). **Oorzaak: definitie.** yfinance toont kas zónder geblokkeerde kas; die steeg van $2,9 naar $33,0 mln. Met kas incl. geblokkeerd (SEC): $1.960,1 → $1.901,2 = −$58,9 mln tegen operationeel −$35,1 + investeren −$23,2 + financieren −$0,3 = −$58,6. **Sluit op $0,3 mln.** Q1 → Q2-26: +$0,7 tegen +$18,4 − $71,6 + $53,8 = +$0,6. Sluit. |
| **3. Twee routes** | Route 1 yfinance per kwartaal, route 2 SEC XBRL cumulatief (jaar tot datum, zelf gedifferentieerd). TTM operationele kasstroom −$55,0 mln langs beide, capex TTM $108,8 mln langs beide. Beide routes gaan terug op dezelfde 10-Q's, dus niet volledig onafhankelijk. De reconciliatie met de werkelijke kasverandering (controle 2) is de onafhankelijke toets, en die sluit. |
| **4. Cijfer-aanval** | (a) De kaspositie van $1,87 mrd staat tegenover **$1,18 mrd converteerbare schuld** (balans): de overlevingspoort vraagt kas, maar netto is het ~$0,7 mrd. (b) Een operationele kasstroom van +$18,4 mln in Q2 is één kwartaal; TTM is −$55,0. (c) Omzet is grillig ($74,9 → $146,2 → $76,7 → $176,1 mln): een groei van +14% j/j in Q2 zegt weinig. |
| **5. Geen management-cijfer** | Geen poortgetal uit een persbericht. Het DOE-bedrag ($900 mln; $1,07 mrd met opties) komt uit berichtgeving en een 8-K-bijlage en staat alleen in de koopcase, niet in een poort. |

## Dimensies

| # | Dimensie | Score | Getal | Bron (document · regel · periode) |
|---|---|---|---|---|
| 1 | Rol in de keten | 3 | Eén van de **drie** DOE-verrijkingsopdrachten van elk $900 mln (Centrus, General Matter, Orano): de concurrenten krijgen hetzelfde geld. Nu de enige die HALEU aan de DOE levert. | ANS Nuclear Newswire 06-01-2026; POWER Magazine (900 kg) |
| 2 | Marge + richting | 2 | Brutomarge TTM 23,7% ($112,1 / $473,9 mln). 2e kw 2026 28,3%, tegen 34,9% een jaar eerder. Grillig: −6% / 24% / 41% / 28%. | W&V, 10-Q's Q3 2025 t/m Q2 2026 (yfinance) |
| 3 | Concurrentie-dynamiek | ? | Marktaandeel en de trend erin niet gevonden. Urenco USA en Orano breiden uit, maar zonder getal. | — |
| 4 | Schaalbaarheid | 2 | Capex TTM $108,8 mln = 23% van de omzet; in Q2 $71,6 mln = 41% van de kwartaalomzet. Kapitaalintensief tot de capaciteit er in 2029 staat. | kasstroomoverzicht Q2 2026 |
| 5 | Uitvoering | 4 | Fase II (900 kg HALEU) geleverd op 25-06-2025, vóór de deadline van 30-06-2025. Contract verlengd tot 30-06-2026; commerciële productie vanaf 01-07-2026. | Centrus-persbericht/POWER Magazine 25-06-2025; ANS 25-06-2025; SEC 8-K 2026 |
| 6 | Waardering | 2 | Marktkap $3,17 mrd ÷ nettowinst TTM $48,5 mln = **65×**; ÷ omzet TTM $473,9 mln = 6,7×. Verwachte PE 41. Voor een bedrijf met 24% brutomarge, waarvan de HALEU-omzet pas vanaf 2029 schaal krijgt. | marktkap 21-09-2026; W&V TTM |

## Divergentie-screen (bij een koersdaling)

| Check | Waarde |
|---|---|
| Koersverandering (3-6 mnd) | −15,7% (3 mnd), −17,1% (6 mnd); −66,6% onder de 52w-top ($464,25); −24,8% onder het 200d-gemiddelde |
| Brutomarge-trend (4 kwartalen) | −6% → 24% → 41% → 28%: stijgend vanaf een dal, maar grillig en lager dan een jaar eerder (35%) |
| Teken winstverrassing (laatste 2 kwartalen) | **positief**: Q1 2026 EPS $1,05 tegen verwacht $0,27; Q2 $1,77 tegen $0,81 (daarvóór twee keer negatief) |
| Omzetgroei-trend | +14% j/j in Q2 2026; grillige reeks |
| **Classificatie** | **KOOP-kandidaat** volgens de tabel (koers omlaag, kwartaal beter dan verwacht), maar met een kanttekening: de verrassingen zijn gemeten tegen lage verwachtingen, en de brutomarge daalde j/j |

## Koopcase

Centrus is het enige beursgenoteerde westerse bedrijf in de schakel die de keten vastzet: verrijking.
- **Wetgeving:** de Russische importban geldt, met ontheffingen tot 2028.
- **Contract:** de DOE-opdracht van $900 mln is getekend ($1,07 mrd met opties), de HALEU-cascade gaat per 01-07-2026 commercieel draaien, en Fase II is op tijd geleverd.
- **Kas:** $1,87 mrd financiert de uitbreiding zonder dat het bedrijf direct naar de markt moet.
- **Koers en cijfers:** de koers staat 67% onder de top, terwijl de laatste twee kwartalen ruim boven de verwachting uitkwamen.

Komen de SMR's (X-energy, TerraPower, Oklo) rond 2030 op schaal en blijft Centrus de eerste HALEU-leverancier, dan kan de omzet een veelvoud van nu worden. Dit is de klassieke uitschieter: klein, enige speler, overheidsgeld.

## Verkoopcase

- **Wederverkoop, geen eigen productie:** vandaag is het bedrijf vooral een doorverkoper van verrijkt uranium tegen een brutomarge van 24%, grotendeels uit Russische levering. Dezelfde ban die de these draagt, bedreigt die aanvoer.
- **Concurrentie met hetzelfde geld:** General Matter en Orano kregen elk ook $900 mln. Het tolhuisje is dus niet exclusief, en Urenco draait al in de VS.
- **Waardering:** 65× de winst en 6,7× de omzet voor een bedrijf waarvan de nieuwe capaciteit pas in 2029 komt. De markt heeft een groot deel van het succes al ingeprijsd.
- **Verwatering:** $53,9 mln aan nieuwe aandelen in Q2, plus $1,18 mrd converteerbare obligaties.
- **Historie:** de voorganger USEC ging in 2014 failliet op ditzelfde centrifugeproject.

## Verzoening

De verkoopcase weegt nu zwaarder. De kansen zijn echt, maar ze liggen in 2029 en later, en worden al voor 65× de winst betaald. Het beslissende getal is volgens de tiebreak **het getal dat het risico beschrijft**: de waardering van 65× de winst van de laatste vier kwartalen, op een brutomarge van 24% die j/j daalde. Die dimensie (6) staat op 2, en ook dimensie 3 staat op `?`. **VOLGEN.**

## Verdict: VOLGEN

**Wachtvoorwaarden** (één volstaat):
1. **Prijs:** koers ≤ $71. Dat is ~30× de winst van de laatste vier kwartalen ($2,37 per aandeel). Een uitschieter hoeft niet voor elke prijs.
2. **Gebeurtenis (het DOE-geld wordt zichtbaar):** twee kwartalen op rij omzet ≥ $200 mln én brutomarge ≥ 30%.

## These-breuk-voorwaarden

*Vóór aankoop opschrijven. Bij het intreden hiervan verkopen, ongeacht de koers.*

1. De DOE-opdracht wordt ingetrokken, of de commerciële HALEU-productie (vanaf 01-07-2026) stopt.
2. De brutomarge ligt twee kwartalen op rij onder 15%: de wederverkoop verslechtert.
3. Het aantal aandelen stijgt in 12 maanden met meer dan 10% (van 20,0 mln), zonder aantoonbare capaciteitsgroei.

## Mijlpalen-ledger

| Beloofd | Wanneer | Gehaald? |
|---|---|---|
| Fase II: 900 kg HALEU aan de DOE | 30-06-2025 | **ja**, 25-06-2025 |
| HALEU-cascade commercieel | 01-07-2026 | aangekondigd (8-K); te controleren in Q3-cijfers |
| Eerste nieuwe capaciteit Piketon (DOE-opdracht) | 2029 | open |

## Niet geanalyseerd

- **Concurrentie (dimensie 3):** marktaandeel van Centrus in LEU en HALEU tegenover Urenco USA en Orano, en de trend daarin. Blokkeert KOOPBAAR.
- **Afhankelijkheid van Russische levering (TENEX):** welk deel van de omzet het is, en tot wanneer de contracten en ontheffingen lopen. Staat in de 10-K, maar is niet uitgelezen.
- **Analistendekking** is 17: niet de "weinig dekking" die het plan zoekt. Die hypothese wordt met deze naam dus niet getoetst.
