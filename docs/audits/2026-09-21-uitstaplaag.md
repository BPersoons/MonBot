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

### Controle-agent, ronde 1 (21-09): **GO-mits**
De schaduwmeting mag lopen. Voorwaarde 1 moet vóór 01-10 geregeld zijn, voorwaarden 2 en 3 vóór de poort van 03-11.
*(De bouwer heeft dit oordeel letterlijk overgenomen: de controle-agent heeft alleen leesrechten.)*

1. **[belangrijk, vóór 01-10] De schaduwmelding geeft een verkoopopdracht** ("verkoop WEBN en parkeer…", `uitstapsignaal.py:113-117`), terwijl het signaal pas na 03-11 advies is. Tot die poort hoort er "SCHADUW — geen actie" te staan.
2. **[belangrijk, vóór 03-11] Het papieren oordeel is mooier opgeschreven dan het is.**
   - **(a) De VS-toets is niet geslaagd** op het vooraf vastgelegde criterium: het rendement was 1,8pp lager, de grens was 1,5pp. De maat "rendement per daling" kwam er pas ná die uitslag bij, via het besluit van Bart. Toch staat er "geslaagd op drie brede markten".
   - **(b) Buiten de steekproef rust het oordeel op één gebeurtenis: 2008.** Over 2010-01..2026-07 halen de markten buiten de VS een daling van ×0,88, Europa ×0,95 en de ontwikkelde markten ×0,80. Dat is 0 van 3, en de regel kost 3,2-4,2pp per jaar.
   - **(c) Vasthouden is de verkeerde maatstaf; een vaste mix met dezelfde blootstelling is de juiste.** De regel zit 68-83% van de tijd in de markt.
     - Met 2008 wint de regel: buiten de VS 2007-2026 een daling van 25% tegen 42%.
     - In 2010-2026 wint de mix op alle vier de markten, met 1,6-2,9pp per jaar meer rendement en een gelijke of kleinere daling.
   - **(d) In euro's zakt de regel door op criterium 1:** IWDA ×0,65, bij 3,4pp kosten per jaar.
   - Nodig: het eerlijk opschrijven ("verzekering tegen trage dalingen, 1929/2000/2008; zonder zo'n daling duurder dan een vaste mix"). Op 03-11 beslissen tegen de vaste mix, niet tegen vasthouden.
3. **[belangrijk, vóór 03-11] Stilte ziet eruit als "blijf in".**
   - Mist yfinance de laatste maand, dan wordt er niets vastgelegd en niets gemeld.
   - Een crash van het script wordt verborgen door `continue-on-error`.
   - Nodig: ontbreekt de vorige maand na enkele werkdagen nog, dan luid melden.
4. **[klein]** De poorteis "koers binnen 1% van DeGiro" is ruimer dan de marges rond een omslag (+0,1% in 2026-03, −0,1% in 2025-06). De eis moet zijn: dezelfde stand.
5. **[klein]** Komen er meerdere nieuwe maanden tegelijk binnen, dan blijft alleen de laatste melding over. Een te laat binnengekomen maand komt in de verkeerde volgorde. `Rubbr` heeft een gat; het oordeel verandert daardoor niet.
6. **[klein]** De grens voor september is €11,96, dat is −6,9%, niet ">8%".

**Zonder bevinding:**
- Er wordt niet vooruitgekeken.
- 56→25, 59→33, 10/40 en 27/49 zijn gereproduceerd.
- Crypto "nee" is terecht.
- Het signaal staat op IN en klopt. De teruggerekende maanden zijn gemarkeerd, de 7 mutaties zijn gedekt, de toetsen staan op 20/20.

**Pre-mortem:**
- Een V-herstel na een verkoop: het grootboek laat al april 2025 UIT op €9,29 zien, weer IN op €10,47. Dat is +12,7% gemist, ~€220.
- Een omslag die rond de lijn heen en weer gaat.
- Een stille storing.
- Verkopen vóór de poort.

**Gemiste kans:** een vaste mix van ~75% WEBN en 25% geldmarkt, zonder omslagen.

**Open vragen:**
- Zat EAFE 1973-2005 in de steekproef van Faber?
- Komt de vaste mix mee in het besluit van 03-11?


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

## Reactie bouwer (21-09, ronde 2)
| # | Reactie |
|---|---|
| 1 | **Opgelost.** `ADVIES = False` in `uitstapsignaal.py`. Tot de poort en een besluit van Bart staat in elke omslagmelding "SCHADUW — GEEN ACTIE", zonder koop- of verkoopinstructie. Toets: `test_schaduwmelding_geeft_geen_opdracht`. Die toets controleert ook dat de instructie er wél in staat bij `ADVIES = True`. |
| 2 | **Nagerekend en overgenomen.** Mijn eigen herberekening (vaste mix met dezelfde blootstelling, 2007 tegen 2010) geeft dezelfde getallen. Aangepast: de docstring van `uitstapsignaal.py`, `config/experimenten.json` ("verzekering tegen trage crashes, geen beter beleggen"), de memory en `uitstapregel_wereld.py`. Dat laatste script heeft een blok `na_de_audit()` gekregen, gemarkeerd als *toegevoegd na de audit*. Het vooraf vastgelegde oordeel blijft ongewijzigd staan. Poort 03-11: Bart beslist tussen de regel (verzekering, kost ~1,5-3pp per jaar in gewone jaren) en een vaste mix van ~75/25, niet tegen 100% vasthouden. |
| 3 | **Opgelost.** Mist het maandslot van vorige maand op dag 5 nog, dan volgt één melding: `controleer_volledigheid`, ook zonder enige data. Een crash wordt niet meer verborgen: de workflow stuurt nu ook een Telegram-bericht bij `steps.uitstap.outcome == 'failure'`. Toets: `test_ontbrekend_maandslot_na_de_vijfde_meldt_een_keer`. |
| 4 | **Overgenomen.** De poorteis is nu "dezelfde stand als de DeGiro-koers zou geven", niet "koers binnen 1%". |
| 5 | **Opgelost.** Alle omslagen in één run worden samen gemeld, en het grootboek wordt na elke toevoeging op maand gesorteerd. Toetsen: `test_twee_omslagen_in_een_run_geven_twee_meldingen` en `test_te_laat_binnengekomen_maand_komt_op_volgorde`. Het gat bij Rubbr: aanvaard, het oordeel verandert niet. |
| 6 | **Gecorrigeerd:** de grens voor september is €11,96, 6,9% onder het slot van augustus. |
| Vraag EAFE | **Ja.** Fabers GTAA-toets (2007) gebruikte vijf klassen voor 1973-2005, waaronder MSCI EAFE. Buiten de VS is 1991-2006 dus binnen zijn steekproef; nieuw is alleen 2007+. Zo staat het nu in de docstring en het register. |
| Vraag mix | **Ja**, zie punt 2. |

**Mutaties ronde 2:** 6 van 6 rood. Eén mutatie bleef eerst groen: de dagdrempel. Mijn toets "te vroeg" keek naar een maand die er al was. Na het aanpassen wordt ook die mutatie rood.

### Controle-agent, ronde 2 (21-09): **GO-mits**, de schaduwmeting mag lopen
*(De bouwer heeft dit oordeel letterlijk overgenomen.)*

**Opgelost:**
- Er gaat geen opdracht meer uit (`ADVIES = False`).
- "1,4-2,9pp" klopt. "Gelijke daling" klopt op 3 van de 4 markten; in de VS is de mix 2,7pp dieper.
- VS: NIET GESLAAGD (−1,8pp) klopt.
- Dat EAFE in de steekproef zat, klopt.
- De stilte-melding werkt: de mutaties op de dagdrempel, de herhaalrem en de vorige maand worden alle drie rood.
- Punt 4, 5 en 6 zijn opgelost.

**Nog te doen:**
- **a. [belangrijk, vóór 03-11]** De enige toets in euro's ontbreekt in het register en in de docstring: IWDA 2010-2026, rendement 9,0% tegen 12,4%, daling ×0,65. Daarmee wordt criterium 1 niet gehaald.
- **b.** "Halveert, ook tegen de mix" is te sterk. De werkelijke factor 2007-2026 ligt tussen ×0,44 en ×0,74.
- **c.** "Altijd lagere daling" voor de mix geldt tegen 100% WEBN, niet tegen de regel. Met 2008 erin was de mix 41-44% diep en de regel 18-33%.
- **d.** `besluiten.md` motiveert nog met de vergelijking tegen vasthouden.
- **e.** Een onterechte ONMEETBAAR-melding als yfinance leeg terugkomt terwijl de maand al in het grootboek staat.
- **f.** Drie onderdelen zijn niet getoetst: `controleer_volledigheid` in beide takken van `main`, en het `nieuw`-filter.
- **g.** Faalt een eerdere stap in de workflow, dan wordt de uitstapstap overgeslagen.
- **h.** Een laat binnengekomen maand tussen twee bekende maanden. Dat is een randgeval.
