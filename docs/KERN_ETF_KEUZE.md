# Het wereldindexfonds — welke, en waarom

`docs/PLAN_2026-08.md` §3 punt 4 zegt: *"Kern-ETF kopen. Kies er één van DeGiro's
kernselectie."* Die keuze was nooit gemaakt. Dit document maakt hem, met de
onderbouwing, zodat de aankoop op de dag dat de rekening opengaat een handeling
van vijf minuten is en geen onderzoeksmiddag.

Dit is **40% van Fase A** en het staat op nul. Van alles in dit project is dit
het grootste gat tussen plan en werkelijkheid.

---

## De drie kandidaten

| | Amundi Prime All Country World | Vanguard FTSE All-World | iShares Core MSCI World |
|---|---|---|---|
| Tickercode | **WEBN** | VWCE | IWDA |
| ISIN | `IE0003XJA0J9` | `IE00BK5BQT80` | `IE00B4L5Y983` |
| Index | Solactive GBS Global Markets | FTSE All-World | MSCI World |
| Landen | ontwikkeld **+ opkomend** | ontwikkeld **+ opkomend** | **alleen ontwikkeld** |
| Jaarlijkse kosten | **0,07%** | 0,19% | 0,20% |
| Fondsgrootte | € 2,7 mrd | ~€ 30 mrd | ~€ 100 mrd |
| Dividend | herbeleggend | herbeleggend | herbeleggend |
| Domicilie | Ierland | Ierland | Ierland |

Alle drie zijn grote/middelgrote bedrijven wereldwijd, volledige replicatie, Iers
gedomicilieerd. Dat laatste betekent dat het dividendlek voor alle drie hetzelfde
is — geen onderscheidend punt.

## De keuze: WEBN

**Twee redenen, en ze wijzen dezelfde kant op.**

**1. De kosten groeien mee met het vermogen, de rest niet.** 0,07% tegen 0,19%
is 0,12 procentpunt. Op de eerste aankoop is dat verwaarloosbaar; op €100k is het
**€120 per jaar**, elk jaar, zonder dat er iets voor gedaan hoeft te worden. Dat
is precies het type winst dat mét de schaal meegroeit — in tegenstelling tot een
kostenbesparing op de server, die altijd hetzelfde bedrag blijft.

**2. Opkomende markten hoor je erin te hebben, en IWDA heeft ze niet.** MSCI
World is 23 ontwikkelde landen; geen China, India, Taiwan, Brazilië. Dat is geen
"wereld"-index maar een keuze om ~10% van de wereldeconomie weg te laten. Wil je
één fonds dat de hele markt koopt — en dat is precies wat dit potje moet doen —
dan valt IWDA af op de definitie, niet op de kosten.

Daarmee blijft WEBN over tegen VWCE, en dat is puur een kostenverschil van
0,12pp in het voordeel van WEBN.

### Wat er tegen WEBN pleit, eerlijk

- **Jonger en kleiner** (€2,7 mrd tegen €30 mrd). Bij een fusie of herstructurering
  van het fonds word je gedwongen verkocht. In **box 3 kost dat niets** — er is
  geen vermogenswinstbelasting die dan afrekent. Voor een Belgische of Duitse
  belegger zou dit zwaarder wegen; voor jou niet.
- **Solactive in plaats van FTSE/MSCI.** Minder bekend indexhuis, methodologisch
  vergelijkbaar voor grote+middelgrote bedrijven wereldwijd. Het verschil in
  samenstelling met FTSE All-World is klein.
- ⚠️ **Controleer de 0,07% bij aankoop.** Bij ultragoedkope fondsen komt het voor
  dat een lage kostenratio tijdelijk is (een tariefkorting die afloopt). Loopt hij
  af, dan is overstappen in box 3 goedkoop — één order.

## De aankoop: één order, niet vier

De kernselectie geldt sinds **1 oktober 2025 alleen nog op Tradegate**: €1
handlingkosten per order, geen commissie, en de Fair Use Policy is afgeschaft.
Zoek dus op de **ISIN** en let op dat de order op **Tradegate** staat.

Wat €1 per order betekent, afhankelijk van de ordergrootte:

| Ordergrootte | €1 als percentage |
|---|---|
| €200 | 0,50% |
| €500 | 0,20% |
| €1.200 | **0,08%** |

Bij deze bedragen domineren de transactiekosten de jaarlijkse kosten volledig:
één order van €1.200 kost eenmalig €1, terwijl het kostenverschil tussen WEBN en
VWCE op datzelfde bedrag €0,84 **per jaar** is. Conclusie: **spreid niet over
kleine orders.** Dat staat al in het plan en het klopt nog steeds.

Vermijd ook de valutakosten: koop de **in euro's genoteerde regel** op Tradegate.
Staat je rekening op AutoFX en koop je een in dollars genoteerde regel, dan tikt
DeGiro 0,25% per transactie aan — meer dan drie jaar kostenverschil, in één keer
weggegeven.

---

## De vraag die eerst beantwoord moet worden: waar komt het geld vandaan?

Dit blokkeert de aankoop, ongeacht welk fonds.

Al het vermogen staat nu in **USDC op Aave en Hyperliquid**. DeGiro koopt met
**euro's van een bankrekening**. Er is geen route tussen die twee die niet via een
bank loopt — en de eerder vastgelegde wens was juist: *"ik wil nog niet naar de
bank, stablecoin USDC bij Hyperliquid is voor nu voldoende als eindstation."*

Twee mogelijkheden:

**A. Verse euro's** (salaris/spaargeld) naar DeGiro. Het bestaande USDC blijft
staan waar het staat. Fase A wordt dan bereikt door groei van bovenaf in plaats
van door verschuiving. Geen uitstapstappen, geen omzettingskosten.

**B. Uitstappen uit USDC** → bank → DeGiro. Dan komt `docs/UITSTAP_NAAR_EUROS.md`
in werking en gaat de eerder gekozen eindbestemming (USDC blijft staan) van tafel.

**Dit is de duurste openstaande beslissing in het plan**, en niet omdat er kosten
aan zitten: zolang hij open staat, blijft 40% van Fase A op nul en is er geen
benchmark waar de rest van het plan zich aan kan meten.

---

*Vastgelegd 2026-08-17. Bronnen: DeGiro's eigen tarievenpagina voor de ETF
Kernselectie (Tradegate, €1) en de fondsdocumentatie van Amundi, Vanguard en
iShares voor kostenratio's, indices en fondsgroottes. Herijk de kostenratio's
bij aankoop — die veranderen (VWCE ging in oktober 2025 van 0,22% naar 0,19%).*
