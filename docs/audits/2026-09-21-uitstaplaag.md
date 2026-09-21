# Claimblad: uitstaplaag per bezit (papiertoetsen en schaduwsignaal WEBN)

*Datum: 2026-09-21 · Poort: A2 (motorstap naar trede 2; het signaal wordt later advies over het grootste potje) · Mijlpaal: geen (motor)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Hierin staat **wat** er verandert en
> **welk bewijs** er is, niet hoe ik tot de conclusie kwam. Controleer alles zelf aan de bron.

## Wat er verandert

**Besluit Bart, 21-09 (`docs/besluiten.md`, laatste rij):** het doel is stabiel groeien, met een
in- en uitstaplaag per bezit. Dat vervangt "geen timing" uit het Conviction Barbell-plan voor de
risicopotjes.

**Commits.** `4b3765c` bevat het besluit en de crypto-toets. De rest van dit blad staat nog niet
gecommit:
- `research/uitstapregel_crypto.py`: BTC/ETH, **niet geslaagd**.
- `research/uitstapregel_wereld.py`: Developed ex US en Europa, 1991-2026, Kenneth French. **Geslaagd.**
- `research/uitstapregel_thema.py`: 49 industrieën, **niet geslaagd**. Daarom geen signaal voor GRID.
- `research/uitstapsignaal.py` en `research/uitstap_signaal.json` vormen het schaduwsignaal voor
  WEBN.DE (maandslot tegen het 10-maandsgemiddelde). Het signaal draait in
  `.github/workflows/scorekaart.yml` en stuurt alleen een Telegram-bericht als de stand omslaat.
- `tests/test_uitstapsignaal.py`: 8 toetsen.
- `utils/motor.py`, twee wijzigingen:
  - nieuwe status `meet_vooruit`. Die telt niet als stilstand, maar moet een `herzien`-datum hebben;
  - `gestopt` telt niet meer als stilstand en vult geen trede. Voorheen zou de motor over een week
    alle gestopte toetsen melden met "een stap verder of stoppen".
- `tests/test_motor.py` heeft 2 toetsen erbij.
- `config/experimenten.json`:
  - `uitstapregel_crash` gaat naar trede 2 met status `meet_vooruit`, herzien 2026-11-03;
  - nieuw: `uitstapregel_crypto` en `uitstapregel_thema`, beide gestopt.

**Productie-impact.** Geen swarm-code en geen VM. Er beweegt geen geld. De workflow draait in
GitHub Actions. Het enige effect naar buiten is een Telegram-bericht aan Bart bij een omslag. Het
signaal gaat over WEBN, 136 stuks à ~€12,84, dus ~€1.750, bij DeGiro. Bart voert zelf uit (er is
geen API) en tijdens de schaduwfase is het signaal een advies.

## Beweringen

| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| 1 | De regel is in alle drie de scripts identiek en kijkt niet vooruit. Beslist wordt op het slot van maand t, belegd in maand t+1 (`shift(1)`). | `research/uitstapregel.py:46-52` (`regel`). `uitstapregel_wereld.py` en `_thema.py` importeren die functie. `uitstapregel_crypto.py:33-42` heeft een eigen kopie met dezelfde `shift(1)`. |
| 2 | De criteria stonden vast vóór elke run en zijn daarna niet veranderd. | Docstrings van de drie scripts. Git bevat alleen de eindversie; de runvolgorde is: crypto, wereld, thema. Ik heb geen criterium aangepast na het zien van een uitkomst. |
| 3 | Buiten de VS en in Europa slaagt de regel: de daling gaat van 56% naar 25% (ex-US) en van 59% naar 33% (Europa), en rendement per daling is beter, ook in 2007-2026. | `python research/uitstapregel_wereld.py <scratchpad>` met de French-CSV's (download: `mba.tuck.dartmouth.edu/.../ftp/Developed_ex_US_3_Factors_CSV.zip`, `Europe_3_Factors_CSV.zip`). |
| 4 | Op crypto zakt de regel door: BTC haalt criterium 1 niet over de hele reeks; ETH haalt 1 en 2 niet. | `python research/uitstapregel_crypto.py` (yfinance). |
| 5 | Op industrieën zakt de regel door: 10/40 (1927-2026) en 27/49 (2007-2026), grens 2/3. | `python research/uitstapregel_thema.py <scratchpad>`. |
| 6 | Het signaal gebruikt alleen afgesloten maanden. Een ontbrekende of ongeldige koers betekent "onmeetbaar" en geen "in". Een omslag in teruggerekende maanden (vóór 2026-09) geeft geen melding. | `research/uitstapsignaal.py` (`maandsloten`, `verwerk`) en `tests/test_uitstapsignaal.py`. Mutaties die ik zelf dacht na te gaan: de lopende-maandfilter weghalen, `>` wordt `>=`, de EERSTE_VOORUIT-voorwaarde weghalen. Elk daarvan moet een toets rood maken. |
| 7 | De stand is nu IN: slot aug €12,84 tegen gemiddelde €11,88 (+8,1%). De controle met IWDA.AS geeft ook IN. | `python research/uitstapsignaal.py stand` |
| 8 | Een fout in het signaal breekt de scorekaart niet (`continue-on-error`). | `.github/workflows/scorekaart.yml` |

## Raakt deze KPI's en poorten
- Geen KPI's H1-H5 direct. Indirect het grootste potje: de broker, ~42% van het vermogen.
- Motor: `docs/MOTOR.md`, trede 2. De poort naar "advies aan Bart" ligt op 03-11: twee maandsloten
  vooruit gemeten, met de koers binnen 1% van DeGiro.

## Risico en terugdraaien
- **Wat kan misgaan.** Een onterecht "uit" laat Bart zijn kernfonds verkopen. Het risico is dan
  gemist rendement, geen verlies van de hoofdsom. De grootste bekende kosten zijn schijnsignalen in
  een V-herstel (2020): in euro's 2010-2026 kostte de regel 3,4pp per jaar.
- **Terugdraaien.** Haal de workflowstap weg, of zet `uitstapregel_crash` op gestopt.

## Wat ik zelf niet heb gecontroleerd
- **Munteenheid.** De French-reeksen zijn in dollars, met de Amerikaanse T-bill als kas. Een
  Nederlandse belegger ziet de index in euro's en parkeert tegen de €STR. Ik heb de regel niet op
  de ex-US-index in euro's getoetst.
- **Uitvoering.** Ik rekende met uitvoering op het maandslot. Bart handelt pas de dag daarna of
  later.
- **Datalek in yfinance.** Of het laatste slot van de maand in yfinance compleet is als de
  workflow op de eerste werkdag om 22:30 UTC draait.
- **Periode van de toetsen.** Ex-US en Europa 1991-2026 overlappen met de VS-periode; het zijn geen
  onafhankelijke crashes. 2008 domineert in alle drie.
- **Uitvoerbaarheid.** Of een geldmarktfonds bij DeGiro zonder extra kosten te kopen is (kernselectie).

---

## Audit
*(in te vullen door de controle-agent)*

> **21-09, bouwer:** de eerste auditpoging brak af op de uitgavenlimiet (reset 14:00). Tot de audit er
> is, heb ik zelf gecontroleerd:
> - **7 mutaties** in `research/uitstapsignaal.py`: de filter op de lopende maand, `>` wordt `>=`, de
>   EERSTE_VOORUIT-voorwaarde, de NaN/nul-guard, de schaduwstand, de dubbele-maandguard en de vlag
>   `teruggerekend`. Elke mutatie maakt een toets rood.
> - **4 mutaties** in `utils/motor.py`. Ook die maken elk een toets rood.
> - De volledige reeks: 472 passed.
>
> **Deadline van de audit:** de eerste mogelijke melding is de run na het slot van september, op
> 01-10. Een omslag in september kan alleen als WEBN meer dan 8% zakt.

## Reactie bouwer
*(per open punt: opgelost in `<hash>` of weerlegd met bewijs)*
