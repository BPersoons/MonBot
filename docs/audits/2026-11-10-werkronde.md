# Claimblad — werkronde 10-11 (gepland): H1 netto uit Hyperliquid, HLP-poort, fusie-arbitrage gestopt

*Datum: 2026-11-10 · Poort: A1 meetcode (KPI) + A2 poortbesluit (`hlp_vault`, stop `fusie_arbitrage`) + A4 wekelijks · Mijlpaal: M5*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.
> Geplande ronde zonder mens; niets gecommit of gedeployed vóór deze review.
> Versie na r1: getallen en beschrijving zijn bijgewerkt; de r1-bevindingen staan onderaan.

## Wat er verandert
- `utils/dip_netto.py` (nieuw) en `utils/kpi.py`: de dip-koper telt in H1 netto (gerealiseerd − fees + funding) uit HL `userFillsByTime` en `userFunding`, elke dag opnieuw opgehaald over de laatste 100 dagen, in plaats van uit `realized_pnl_usd` van het eigen boek. Per meegeteld interval, net als potjes en kosten. Onmeetbaar (H1 `None`, `h5.onmeetbaar`) bij: HL-storing na 3 pogingen, lege respons, open positie zonder fills of met funding ouder dan 26 uur, ontbrekend veld, ontbrekende datum in de reeks. Veld `h1.dip_koper_gerealiseerd_usd` heet nu `dip_koper_netto_usd`; `dip_gerealiseerd_usd` blijft het boek (alleen ter vergelijking).
- `tests/test_kpi.py`, `tests/test_dip_netto.py` (nieuw), `tests/test_overzicht_hlp.py` (nieuw).
- `scripts/overzicht.py`: meter `hlp_apr` meet de 30-dagenreeks zonder grootste en kleinste stap (strenger dan de poort), niet meer het `apr`-veld. `scripts/overzicht_sjabloon.html`: H1 onmeetbaar toont "onbekend". Alleen de pagina.
- `agents/swarm_monitor.py`: drawdown-alarm dip-koper maximaal één keer per dag (was zes).
- `scripts/werkronde_gepland.ps1`: houdt pc en scherm wakker zolang de ronde loopt (`SetThreadExecutionState`).
- `config/experimenten.json`: `hlp_vault` poortuitkomst, `sinds` 10-11, kaart; `fusie_arbitrage` idee → gestopt, trede 1; `dip_koper` alarmstand. `config/agenda.json`: LDOS-regel weg, nieuwe regel dip-koper 17-11.
- `research/fusie_arbitrage.py` (nieuw, papier), `research/cards/LDOS.md`, `docs/besluiten.md`, `docs/PLAN_2026-08.md`.
- Productie-impact: `data/kpi.json` (één veld hernoemd); de KPI-update doet 1× per dag extra HTTP-calls naar HL (doorgaans ~4 s, grens ~80 s, in de hoofdlus, binnen de bestaande `try`). Geen orders, geen geld, geen wijziging aan statebestanden. Volledige deploy nodig (nieuw bestand, config in de image).

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Productie is gezond: container 7 dagen up, RestartCount 0, dashboard 200, 269 MiB, geen CYCLE_FROZEN/OOM in 7 dagen. De 21 tracebacks zijn 7 incidenten × 3 gekoppelde exceptions (Cloud Logging-achtergrondthread, 504) | stap-1-commando 10-11 ~08:00 UTC; `docker logs --since 168h`; A1 r1 |
| 2 | KPI 10-11 00:04: H1 −$49,90 (85 d, voorlopig; opbrengst −$10,05, kosten $39,85) · H2 −0,27pp (2,68% vs 2,946%) · H3 $0 · H4 2,77 min, alles gevonden · H5 0 gaten, 0 onmeetbaar | `data/kpi.json` › `laatste` |
| 3 | De H1-daling sinds 03-11 (−$36,79 → −$49,90) komt van één stop: XYZ-CBRS gesloten 05-11 15:31, −$11,14. Het boek ging van $11,19 naar $0,05. De rest is de dagelijkse kosten min rente | `kpi.json` › `history`; `thematic_exposure_positions.json` › `positions.XYZ-CBRS` |
| 4 | **H1 was fout, twee effecten met tegengesteld teken.** De dip-reeks in `kpi.json` begint op 16-09, rente en kosten tellen vanaf 15-08: HL netto 15-08 → 16-09 is +$29,45 en ontbrak. Over 16-09 → 10-11 rekende het boek zonder fees en funding $2,97 te gunstig | `kpi.json` › `history`; HL `userFillsByTime`/`userFunding`; A1 r1 |
| 5 | Droogloop van de definitieve code op productiedata, zonder iets te schrijven: H1 **−$32,29** (opbrengst $7,56, dip-koper netto −$7,94), H2 en H5 ongewijzigd. Verschil met de oude uitkomst +$17,61 | exec van de lokale modules in de container via stdin, 10-11 |
| 6 | Q4 t/m 10-11 met dezelfde code: **−$46,29** (rente $7,60, basis $0,64, dip-koper −$37,51, kosten $17,03). Met nog 51 dagen × ~$0,50 is het eerste gemiste H1-kwartaal vrijwel zeker | `kpi.bereken` op de VM, `hist` vanaf 2026-10-01, `venster=400` |
| 7 | De fix is getoetst met toetsen die alleen het netwerk (`_post`) vervangen: 41 groen; r1 8 + r2 11 + r3 5 mutanten rood (o.a. fees weg, funding weg, oude bron, verschil eerste-laatste, ontbrekende datum stil, lege respons nul, geen versheidscontrole, None wordt nul, herstart op tijd+1, niet ontdubbelen, geen herhaling) | `venv/Scripts/python.exe -m pytest tests/test_kpi.py tests/test_dip_netto.py`; mutaties via sed, daarna hersteld |
| 8 | Volledige poort groen na `pip install eth-account==0.13.7` in de venv: state-audit, syntax (293), pytest 642 passed, pipeline | `venv/Scripts/python.exe scripts/predeploy.py`, 09:46 lokaal |
| 9 | Zes posities met zes beursstops, alle Stop Market reduceOnly, `sz` = positie; GOOGL 245,33 · AMZN 180,21 · CRCL 51,961 · BABA 83,36 · IBM 172,42 · AVGO 258,33 | `clearinghouseState` + `frontendOpenOrders`, `dex: "xyz"`, 10-11 |
| 10 | Verliesbewaking draait (`laatste_ronde` ~3 min oud), `onmeetbaar` leeg, experimentverlies $0; geen nieuwe `gemeld` sinds de vorige ronde (de twee zijn van 12-10 en 23-10) | `data/verliesbewaking_state.json` |
| 11 | NAV $5.309,84 (03-11: $5.361,85) | `python -m utils.nav`, 08:03 UTC |
| 12 | **Poort HLP niet gehaald.** Venster: de `month`-reeks van 10-11, afgesneden op 10-10 22:56 → 06-11 20:42 UTC (26,9 d, 34 stappen; afwijking van de letter van de afspraak, omdat `allTime` één punt per ~13 dagen heeft): tijdgewogen +0,036% = 0,49%/jr, grootste daling 0,31%. Lat: gemiddelde `aave_apy_pct` over 10-10 t/m 07-11 (n=29) 2,657% + 3pp = 5,66% | HL `vaultDetails` `0xdfc2…f303`, `portfolio.month`; `kpi.json` |
| 13 | Na het venster maakte HLP op 08-11 één stap van +1,51%: 30 dagen nu 17%/jr, `apr`-veld 25,27%. Telt niet voor de poort. Zonder grootste en kleinste stap +2,65%/jr, onder de lat van ~5,9% | `portfolio.month`, A2 r1 |
| 14 | HYPE-basis: $115,64 op $115 inleg (+0,56% in 33 dagen, ~6,1%/jr), hefboom 1,6, spot 0,949 tegen short 0,95. Kill (50%) ver weg, evaluatie 08-12 | `data/basis_hype_state.json` |
| 15 | **Fusie-arbitrage gestopt.** Geen enkel fonds haalt +2 pp boven kas in beide helften (MERFX +1,72/+1,58, ARBFX +2,19/+1,06, MNA +2,57/+0,02); op $500 −5 tot −13 pp, op $5.000 hooguit +1,1 pp | `python research/fusie_arbitrage.py`; proxy voor papierstap 1 |
| 16 | LDOS is geen koopvraag meer: koers $135,76 > $120, operationele marge Q3 11,9% (eis ≥ 12,0% twee kwartalen; Q2 11,7%). Geen these-breuk aangetoond; guidance gemengd (omzet lager, EPS en kasstroom hoger). Volledige herscoring staat open | SEC 8-K Q3 2026; Yahoo-koers 10-11; `research/cards/LDOS.md` |
| 17 | **Dip-koper boven zijn alarmgrens sinds 02-11** (~20% onder de top van $292 op 22-09, grens 15%; 47 berichten). Vier stops in Q4 kostten $46,64, tegen $8,24 rente + basis. Bij Bart gelegd via de agenda (17-11) en de melding | `swarm_monitor` logs; HL-fills; A4 r1 |
| 18 | Motor: na deze ronde geen signalen. Deze week bewogen er twee: `hlp_vault` (poort) en `fusie_arbitrage` (gestopt) | `python -m utils.motor` |
| 19 | Geen poort opgerekt, geen kapitaalbeweging | diff `config/experimenten.json` |

## Raakt deze KPI's / poorten
- H1 (definitie): +$17,61 op 10-11. Half december valt de +$29,45 van aug-sep uit het venster en zakt H1 richting het Q4-niveau; voor het oordeel over de VM telt Q4 (−$46,29), niet het 90-dagencijfer.
- H5: een aanhoudende storing bij HL rond 00:05 UTC maakt H1 die dag onmeetbaar en geeft tot 4 `meting_kpi`-berichten (cooldown 6 uur, vlag tot de volgende nacht).
- M5 (`hlp_vault`, poort 07-11): niet gehaald.

## Risico en terugdraaien
- Maximaal op het spel: geen geld. Een fout in `dip_netto` geeft hooguit een verkeerde of ontbrekende H1.
- Hoofdlus: doorgaans ~4 s, grens ~80 s per dag, binnen `try/except` in `main.py`.
- Terugdraaien: `git revert`, opnieuw deployen. Oude rijen in `kpi.json` blijven geldig.

## Wat ik zelf niet heb gecontroleerd
- Of `fee` in HL-fills de `builderFee` al bevat (afgeleid: vermoedelijk wel, maximaal $0,16).
- Waarom de kosten van 23 en 24-08 ontbreken: `cost_log.json` bewaart 30 dagen.
- Het venster is 23 uur korter aan de voorkant en 3 uur aan de achterkant dan afgesproken; de datapunten van HL vallen zo.
- De criteria van de fusie-arbitrage stonden vóór de eerste run in de docstring, maar het bestand was ongecommit: niet uit git te bewijzen. Criterium C rust op aannames (3 deals per positie per jaar, fondskosten ruw); criterium A faalt daar los van.
- Of `SetThreadExecutionState` met scherm-vlag de pc op Modern Standby echt wakker houdt: `powercfg /a` toont S0, de wijziging draait pas volgende week.
- `scripts/dipkoper_resultaat.py` heeft nog de pagineringsfout van r1-punt 6 (effect $0,0012).

---

## Audit

**r1 (2026-11-10), ingekort uit het rapport: GO-mits. Niet deployen vóór voorwaarden 1, 2 en 5.**

| Onderdeel | Oordeel |
|---|---|
| A1 meetcode H1 | GO-mits (1, 2, 5) |
| A2 poort `hlp_vault` niet gehaald | GO |
| A2 nieuwe HLP-meter | GO-mits (3) |
| A2 stop `fusie_arbitrage` | GO |
| `scripts/werkronde_gepland.ps1` | GO (open vraag: slaapstand) |
| A4 wekelijks | GO-mits (4) |

1. **[belangrijk]** H1 meet de dip-koper niet over hetzelfde venster: dagen zonder kosten (23 en 24-08, +$8,87) tellen niet voor potjes en kosten maar wel voor de dip-koper. Zuiver −$32,29, niet −$23,41. Tel per interval, onmeetbaar bij een ontbrekende datum, toets met kostengat.
2. **[belangrijk]** Lege of afgekapte ophaling en ontbrekende velden geven stil een getal (leeg = $0 met H5 groen; `float(waarde or 0.0)`).
3. **[belangrijk]** HLP-meter is niet "dezelfde maat als de poort" en eenzijdig: alleen de grootste winststap eruit (−1,11%/jr; symmetrisch +2,65%).
4. **[belangrijk, A4]** Dip-koper staat acht dagen boven zijn alarmgrens (47×, 20,4%), niemand heeft beslist.
5. **[belangrijk, procedure]** `predeploy.py` en de volledige suite niet groen aangetoond (venv mist `eth_account`).
6. [klein] Paginering op tijd + 1 verliest regels met dezelfde tijd (9 van 1.749, $0,0012).
7. [klein] Claimblad/docstrings: "één alarm" is tot 4; "max 60 s" is 80 s; venster begint 15-08; `kpi.py:16` noemt fees.
8. [klein] Afwijking van "niet de month-reeks" benoemen; uitkomst verandert niet.
9. [klein] `kaart.wanneer` en `volgende_stap` spreken elkaar tegen.
10. [klein] Fusie: proxy voor papierstap 1; "criteria vooraf" niet uit git te bewijzen; meetperiode 2007+.
11. [klein] Pagina toont bij onmeetbaar "nog niet".

Nagerekend door de auditor: HLP-poort (0,494%/jr, lat 5,657%, besluit klopt), Q4 −$46,29, fusie-arbitrage (zelfde cijfers), aansluiting `main.py` → `update_kpi`, lezers van `kpi.json`, beursstops. Gemiste kans: de dip-koper is de grootste hefboom op H1.

## Reactie bouwer
1. **Verwerkt.** `bereken` telt per interval; ontbrekende datum = `dip_koper_reeks:<datum>` en H1 `None`. Toetsen `test_dag_zonder_kosten_telt_ook_niet_voor_de_dip_koper` en `test_reeks_met_een_ontbrekende_datum_is_onmeetbaar`. Droogloop −$32,29. Cijfers gecorrigeerd in besluiten, PLAN en dit blad.
2. **Verwerkt.** Lege respons en open positie met funding ouder dan 3 uur geven een fout; velden verplicht. Met toetsen en mutanten R4–R6c.
3. **Verwerkt.** Symmetrisch getrimd (grootste én kleinste stap), tekst "strenger dan de poort".
4. **Verwerkt.** Alarm maximaal één per dag; in de melding en de agenda (17-11); advies: herbeoordeling naar voren.
5. **Verwerkt.** `eth-account==0.13.7` (pin uit requirements) in de venv; predeploy GROEN, 642 passed. CI volgt bij de push.
6. **Verwerkt** in `utils/dip_netto.py` (herstart op de laatste tijd, ontdubbelen). `scripts/dipkoper_resultaat.py` **open**: effect $0,0012, vóór de evaluatie meenemen.
7. **Verwerkt.** Herhaling ×3 in `_post`, getallen in dit blad, 15-08, docstring `kpi.py`.
8. **Verwerkt** in `hlp_vault` › `volgende_stap`.
9. **Verwerkt:** `kaart.wanneer` = "als de meter een volle maand groen is".
10. **Verwerkt** (tekst); bewijs "vooraf" staat hierboven als niet te controleren.
11. **Verwerkt** in `overzicht_sjabloon.html`.
- Open vraag slaapstand: `powercfg /a` toont S0 (Modern Standby); het script zet nu ook de scherm-vlag. Niet getest.

**r2 (2026-11-10), ingekort uit het rapport: GO-mits, deployen mag zodra voorwaarden 1 en 2 zijn vervuld; een derde ronde is niet nodig.** (1) GO: −$32,29 twee keer herleid, Q4 −$46,29. (2) GO-mits. (3) GO: 17,01%/jr alle stappen, 2,65% getrimd. (4) GO: top $292,39 klopt, geen stromen sinds 15-09, nu 18,7-18,9% onder de top op de snapshot. (5) GO: predeploy zelf gedraaid, 642 passed. (6) GO, werking op Modern Standby onbewezen tot 17-11.

- **Voorwaarde 1 [belangrijk]:** lege fills met verse funding geven nog stil een getal (~$35 te gunstig op Q4). Fout als er posities open staan en `fills` leeg is, met toets en mutant.
- **Voorwaarde 2 [procedure]:** de drie ongetrackte bestanden samen met `kpi.py` committen.
- Klein: (3) funding is pas sinds 02-11 elk uur (daarvoor één tijdstip per dag); (4) mutant `doel_gehaald` zonder `dip_meetbaar` overleeft; (5) geen toets voor de cooldown, verdieping binnen 24 uur wordt niet gemeld; (6) `delta.get("type")` slaat stil over; (7) `dip_netto_cum_usd` niet vergelijkbaar tussen dagen; (8) NaN in het boek blokkeert de KPI-regel.

## Reactie bouwer op r2
- **V1 verwerkt:** `_controleer_volledigheid` geeft een fout bij open posities zonder fills; toets `test_open_positie_zonder_fills_is_onvolledig`, mutant rood.
- **V2 verwerkt:** alles in één commit.
- 3 verwerkt: de grens is 26 uur, zodat ook een dagritme niet vals alarmeert; een afkapping van minder dan een dag kost ~$0,04.
- 4 verwerkt (delta groter, mutant rood). 6 verwerkt. 7 verwerkt: veld geschrapt. 8 verwerkt, met toets.
- 5 **open:** cooldown ongetoetst en geen doorbraak bij 5pp dieper; de dip-koper heeft zijn stops, het alarm stuurt niets aan.
