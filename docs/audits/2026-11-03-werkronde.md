# Claimblad — werkronde 03-11 (gepland): poort uitstapregel, twee ideeën gestopt, één nieuw

*Datum: 2026-11-03 · Poort: A2 poortbesluit (uitstapregel_crash, advies aan Bart) + A4 wekelijks · Mijlpaal: —*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.
> Eerste geplande ronde zonder mens (Taakplanner). Gisteren (02-11) was er een volledige A4.

## Wat er verandert
- `config/experimenten.json` (in de image; raakt geen VM-gedrag, geen van deze ideeën heeft een `sleeve`):
  - `uitstapregel_crash`: poortuitkomst 03-11 in `volgende_stap`, `herzien` 03-11 → 10-11, kaart `wanneer: open`. `ADVIES` in `research/uitstapsignaal.py` blijft **False**.
  - `basis_aandelen_degiro`: idee → **gestopt**, trede 1 (papierstap 1, 2 en 4 gedaan).
  - `basis_hype_khype`: idee → **gestopt**, trede 0 (op omvang).
  - `basis_aandelen_token`: **nieuw idee**, trede 0, geen potje.
  - `hlp_vault`: stand 03-11 in `volgende_stap` (geen statuswijziging).
- `research/aandelen_basis.py` (nieuw, papier; gebruikt `scripts/funding_historie.py` + de Yahoo-chart-API).
- `docs/besluiten.md`: drie regels. Geen productiecode, geen deploy, geen geld.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Productie is gezond: container 21 u up, RestartCount 0, dashboard 200, 326 MiB | stap-1-commando werkronde, 03-11 ~08:05 UTC |
| 2 | KPI 03-11 00:07: H1 −$36,79 (78 d, voorlopig; opbrengst −$0,46, kosten $36,33) · H2 −0,31pp (2,64% vs 2,95%) · H3 $0 · H4 2,77 min, alles gevonden · H5 0 gaten, 0 onmeetbaar | `data/kpi.json` › `laatste` |
| 3 | H1 Q4 tot nu toe (01-10 t/m 03-11, 33 dagen): **−$31,35** (rente +$6,20, basis +$0,49, dip-koper gerealiseerd −$24,54, kosten −$13,51). Het eerste gemiste kwartaal (31-12) is vrijwel zeker | `kpi.bereken` in de container op `sleeve_nav`-historie vanaf 2026-10-01, `venster=400`, dezelfde stromen/kosten/dip-reeks |
| 4 | De H1-sprong van −$24,83 (02-11) naar −$36,79 komt van één softwarestop: XYZ-ORCL gesloten 02-11 17:38 UTC op 122,375 tegen een instap van 163,275 (−25,05%), `realized_pnl_usd` −$11,70. Cumulatief gerealiseerd $22,89 → $11,19 | `thematic_exposure_positions.json` › `positions.XYZ-ORCL`; `docker logs` 17:38:13 "Signing sell order 0.286 XYZ-ORCL"; `kpi.json` historie |
| 5 | Na de wissel ORCL → CRCL (17:39) staan er 6 beursstops op 6 posities, elk reduceOnly Stop Market met sz = positie; de stop van CRCL op 51,961 (= 0,70 × 74,23) | `frontendOpenOrders` + `clearinghouseState`, `dex: "xyz"`, wallet uit `get_secret("HL_THEMATIC_WALLET_ADDRESS")`; log 17:50:41 "Beursstop geplaatst" |
| 6 | Verliesbewaking draait (`laatste_ronde` 3 min oud), `onmeetbaar` leeg, experimentverlies $0; geen nieuwe `gemeld` sinds de vorige ronde (de twee aanwezige zijn van 12-10 en 23-10) | `data/verliesbewaking_state.json` |
| 7 | NAV $5.361,85 (02-11: $5.379,70) | `python -m utils.nav` in de container, 08:05 UTC |
| 8 | **Poort uitstapregel, criterium 1 gehaald:** 2026-09 en 2026-10 staan met `teruggerekend: false`, stand `in` (controle IWDA ook `in`); slot 13,074 / 13,02 tegen gem10 12,0676 / 12,2478 = +8,3% / +6,3%. Een andere DeGiro-notering (centen) kan de stand niet omdraaien | `research/uitstap_signaal.json`; commits `0447eea`, `a522911` |
| 9 | **Criterium 2 is Barts keuze.** Advies: de vaste mix, en die bestaat al op het niveau van het geheel. Van de NAV is ~50% risicodragend (kern $1.984 + GRID $231 + dip-koper $242 + crypto $209 = $2.666 = 49,7%), de rest USDC/kas en de marktneutrale basis. Een 2008-daling van ~55-59% op het risicodeel (afgeleid uit 41-44% voor de 75/25-mix in het register) kost het geheel ~28%, binnen de 18-33% van de regel, zonder de 1,5-3pp per jaar die de regel kost. Daarnaast is de regel een timingsignaal, en het mandaat van 12-10 zegt "nooit richting voorspellen" | NAV (bewering 7); `experimenten.json` › `uitstapregel_crash` (papiergetallen 21-09); `besluiten.md` 12-10 |
| 10 | **HLP-poort 07-11 wordt vrijwel zeker niet gehaald:** 30 dagen +0,045% (~0,5%/jr), 7 dagen −0,21%, vault-APR −0,09%, tegen een lat van Aave + 3pp ≈ 5,7%. Formeel gemeten op 10-11 (dan is het venster dicht) | HL `vaultDetails` HLP `0xdfc2…f303`, `portfolio` month/week (`pnlHistory` / gemiddelde `accountValueHistory`) |
| 11 | **Aandelen-basis gestopt:** funding 6,6-10,7%/jr op de positie (AAPL 2,2%), 83-91% van de uren positief; TSM 04-2026 −19%. Op kapitaal, lat 4,95%: bij 1x hooguit de lat (AVGO/GOOGL 5,0% op $5.000), bij 2x zes van de tien erboven (5,1-6,7%). Doorslaggevend: de grootste 3-maandsstijging sinds 2010 is 46-218% (12 maanden: 82-1122%); de short liquideert rond +45% (2x) of +90% (1x). De winst staat dan bij DeGiro en het verlies bij HL, en onder "nooit geld uit DeGiro" kan aanvullen alleen uit Aave ($2.500), wat bij een NVDA-achtige stijging niet volstaat | `python research/aandelen_basis.py` (twee runs, gelijke uitkomst); `scripts/funding_historie.py` |
| 12 | **kHYPE gestopt op omvang:** +1,4pp op $115 is ~$1,60 per jaar; heropenen als de HYPE-basis zijn evaluatie haalt en +1,4pp ≥ $25 per jaar oplevert (~$1.800). Precedent: Fluid (+$13/jaar) gestopt door Bart 05-10 | `experimenten.json` › `basis_hype`, `fluid_rente` |
| 13 | De gewijzigde JSON is geldig; de toetsen die het register lezen zijn groen (81). De hele suite lokaal: 594 groen, 8 fout + 8 collectiefouten, allemaal `ModuleNotFoundError: eth_account` (venv onvolledig) en niet in bestanden die ik wijzigde. CI draait de volledige suite bij de push | `venv/Scripts/python.exe -m pytest tests/test_experimenten.py tests/test_kpi.py tests/test_motor.py tests/test_rendement.py tests/test_verliesbewaking.py` |
| 14 | Motor: na deze ronde nog één signaal (fusie_arbitrage 22 d op trede 0). Deze week bewogen er vier ideeën (02-11 twee gestopt, 03-11 twee gestopt + een poort) | `python -m utils.motor` |

## Raakt deze KPI's / poorten
- Poort `uitstapregel_crash` (03-11): criterium 1 gehaald, criterium 2 bij Bart. Geen poort opgerekt.
- `hlp_vault` poort 07-11: voorgemeten, besluit 10-11.
- H1 per kwartaal (besluit 12-10): Q4 wordt waarschijnlijk het eerste gemiste kwartaal → bij twee gemiste kwartalen het VM-besluit.

## Risico en terugdraaien
- Geen geld beweegt, geen code op de VM. Het advies in bewering 9 is de enige uitkomst die later geld raakt (Bart beslist; de regel blijft schaduw).
- Terugdraaien: `git revert`.

## Wat ik zelf niet heb gecontroleerd
- Of DeGiro WEBN op Xetra of Euronext noteert; mijn bewering 8 rust op de marge (+6,3%), niet op de notering.
- De 2008-daling van 55-59% heb ik niet opnieuw gemeten, maar teruggerekend uit de mixgetallen in het register. De dip-koper heeft stops (−25%/−30%), dus zijn deel valt in een crash waarschijnlijk minder diep.
- Dividend op de long en de HL-kosten van de xyz-dex (mogelijk hoger dan 0,045%) zitten niet in `research/aandelen_basis.py`.
- Het nieuwe idee `basis_aandelen_token` noemt xStocks/Ondo als voorbeeld. Of die in 2026 voor een NL-particulier in een eigen wallet beschikbaar zijn, is precies papiervraag 1; ik heb het niet gecontroleerd.
- LDOS (agenda 03-11): de kwartaalcijfers verschijnen vandaag na deze ronde; niet beoordeeld.

---

## Audit
*(De geplande run werd om 09:56 afgebroken doordat de pc in slaap ging, midden in de review. Herstart in de sessie van 03-11. De controle-agent leest alleen; de bouwer heeft deze tekst letterlijk uit zijn rapport overgenomen.)*

**r1 (2026-11-03): A2 poort uitstapregel criterium 1 GO · advies (bew. 9) GO-mits · stop aandelen-basis GO · stop kHYPE GO · nieuw idee GO · A4 GO.**

Zelf nagerekend: `kpi.json` › `laatste` (H1 −36,79, H2 −0,31pp, H3 0, H4 2,77, H5 0). Q4 via `kpi.bereken` op de VM vanaf 01-10, `venster=400`: −31,35 (rente 6,20, basis 0,49, dip-koper −24,54, kosten 13,51); met de rest van Q4 (59 d × $0,503) en −$22 ongerealiseerd is "vrijwel zeker gemist" terecht. ORCL: HL-fill 122,26 (geboekt 122,375), `closedPnl` −11,67, fee $0,0065. Zes beursstops reduceOnly Stop Market, `sz` = positie, trigger 0,700-0,701 × instap, CRCL 51,961. Verliesbewaking: `gemeld` 12-10 en 23-10, `onmeetbaar` leeg. Container gestart 02-11 10:50 UTC, RestartCount 0, dashboard 200. NAV $5.360 (19:00); de −$25 tussen 08:05 en 08:56 is de Xetra-opening (WEBN 13,06 → 12,90 × 136). HLP maand +0,052%, week −0,21%, APR −0,087%. `research/aandelen_basis.py` opnieuw gedraaid, zelfde uitkomst. Volledige suite 616 groen (systeem-Python), syntax 289/289. Uitstapsignaal: 2026-09 in `0447eea`, 2026-10 in `a522911`, beide `teruggerekend: false`, stand `in`, IWDA ook `in`.

Bevindingen:
1. **[belangrijk]** Bewering 9 vergelijkt twee niveaus: de 18-33% is de kern mét regel, de ~28% het geheel zonder regel. Op één niveau: zonder regel ~28-30%, met regel op de kern ~15-20% → ~$500-750 per 2008-crash tegen ~$30-60/jaar. De veilige helft is USDC in DeFi (SVB-depeg $0,87, opnamestop bij 100% benutting, geen fiat volgens 18-08). Bij kern 40% + risicodeel 20% kan het risicodeel ~60% worden. Het mandaat van 12-10 ging over premies, niet over de kern. Voorwaarde: advies herschrijven met beide getallen op het geheel, het USDC-voorbehoud, de geldigheidsgrens (risicodeel ≤ ~55%) en het sterkere argument (IWDA haalde criterium 1 niet). "Geen regel" mag blijven.
2. [klein] De drie regels voor `docs/besluiten.md` ontbreken in de werkboom.
3. [klein] Sept-slot 13,074 is van 29-09, niet 30-09 (13,094): `maandsloten` neemt de laatste beschikbare dag. gem10 okt (12,2478) is niet uit de eigen reeks te herleiden (12,2458). Zonder gevolg voor de poort; controleren vóór `ADVIES` True wordt.
4. [klein] `hlp_vault` heeft `benchmark: null`; lat (Aave + 3 of Aave + 2 + 3) en venster vóór 10-11 vastleggen. Uitkomst nu: ruim niet gehaald.
5. [klein] "5,1-6,7% bij zes van de tien" geldt bij $5.000-posities met DeGiro-kosten; `basis_aandelen_token` neemt dat over zonder voorbehoud en zonder het precedent `basis_xyz_goud` (token + brug + 0,3% swap gaf 3,7-4,5%). Goud viel op rendement (4,6% op $500 bij 2x), niet op margerisico.
6. [klein, bestond al] H1 telt de dip-koper bruto: `realized_pnl_usd` zonder fees en funding, en `cost_tracker.py:133` laat fees weg. `cumFunding` op de zes open posities is al $1,85 (~$1/maand). Verandert de Q4-conclusie niet, maar de noordster eist "na funding".
7. [klein] Logboekregel voor de audit van 02-11 ontbreekt.

Buiten scope: `PerformanceAuditor` (`utils/auditor.py:175-226`) heeft geen guard voor potjes (auditte ORCL op 02-11 17:40; sloeg de gewichten alleen over door ontbrekende `analyst_signals`). Instap ORCL geboekt op 163,275 tegen 163,06 bij HL.

Pre-mortem: een trage crash binnen drie maanden, Bart houdt vast op "die mix heb je al", de kern verliest ~$600 terwijl de USDC-helft onder druk staat → voorwaarde 1 en een vaste grens op kern/veilig. Gemiste kansen: (1) divergentie-stempel dip-koper: de drie `ok=False`-posities (CRWV −$11,99, ORCL −$11,70, BABA open −$6,63) zijn alle drie verliezers, ~$30, meer dan het Q4-tekort; n=3, niemand meet het; (2) de knop kern/veilig formaliseren (kern + risicodeel ≤ 55%). Open vragen: is de bijstorting van de kern (agenda 17-10, ~16 WEBN) gedaan? Waarom "gestopt" voor kHYPE en niet "wacht"?

## Reactie bouwer
1. **Verwerkt.** `uitstapregel_crash` › `volgende_stap` en `kaart.volgende` herschreven: beide getallen op het geheel (~28-30% tegen ~15-20%, ~$500-750 per crash tegen ~$30-60/jaar), het USDC-voorbehoud, de grens risicodeel ≤ ~55%, IWDA als doorslag; het mandaat-argument geschrapt. Advies blijft "geen regel". Bart kreeg in de sessie eerst de ongecorrigeerde versie en daarna de correctie.
2. **Verwerkt.** Drie regels in `docs/besluiten.md` (03-11).
3. **Open, vastgelegd** in `uitstapregel_crash` › `volgende_stap`: repareren vóór `ADVIES` True wordt.
4. **Verwerkt.** `hlp_vault` › `volgende_stap`: lat = gemiddelde Aave-APY over het venster + 3pp (hypothese 19-09), venster 10-10 00:00 t/m 07-11 00:00 UTC uit `pnlHistory`/`accountValueHistory`.
5. **Verwerkt.** `basis_aandelen_token`: voorbehoud $5.000 vs $500 in de hypothese, precedent `basis_xyz_goud` als papierstap 6.
6. **Open.** Meetcode (A1-plichtig); naar de volgende werkronde, met een toets die rood wordt zonder funding.
7. **Verwerkt.** Logboekregel 02-11 achteraf toegevoegd.
- Gemiste kans 1: opgenomen in `dip_koper` › `volgende_stap` (evaluatie bij de herziening van 22-12). Gemiste kans 2: aan Bart voorgelegd als deel van het advies.
- kHYPE "gestopt" i.p.v. "wacht": bewust, met een harde heropen-voorwaarde; "wacht" zonder datum werd eerder 21 dagen stil (motor-signaal).
- Open vraag bijstorting kern: aan Bart gevraagd.
