# Claimblad — werkronde 19-10: KPI-stand, motor, e2-micro uitvoeren op maandagavond

*Datum: 2026-10-19 · Poort: A4 wekelijks + A2-aanvulling (uitvoering e2-micro, poortbesluit van 06-10) · Mijlpaal: M4*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
- Ongecommit, deze ronde: `config/experimenten.json` (basis_scan_hl → trede 2, uitschieterpotje gestopt, e2_micro_poging_2 → nazorg), `config/agenda.json` (regel 17-10 "werkronde + verkleinen" weg, regel 27-10 "eindoordeel kleine server" erbij), nieuw `scripts/basis_scan.py` (alleen papier, draait lokaal tegen de publieke HL info-API).
- Al gecommit maar **niet** in de image: `111c6c9` (12-10, 11:04 UTC): alleen idee-entries in `config/experimenten.json` (felix/goud gestopt, vijf ideeën op trede 0) en `scripts/overzicht.py`. De container startte op 12-10 09:30 UTC, vóór die commit; de motor op de VM toont felix en goud nog als "idee".
- **Full deploy** van bovenstaande (config zit in de image), daarna de **e2-micro-wissel** volgens `docs/audits/2026-10-06-e2micro.md` § Uitvoering, maar op **maandag 19-10 na 20:00 UTC** (slot VS-beurzen) in plaats van op een zaterdag.
- Productie-impact: geen geldcode. De deploy herstart de container (~1 min); de wissel geeft ~3–5 min stilstand. Er wordt geen geld verplaatst.

## Beweringen
| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| 1 | Productie gezond: container Up 7 days, `RestartCount=0`, dashboard 200, VM e2-small, container 321 MiB (incl. mijn exec), `ctr_werkelijk` 279–287 MiB | `docker ps`/`inspect`, curl 8080, `free -m`, `~/mem_history.log` 19-10 17:45–18:45 UTC |
| 2 | KPI's 19-10: H1 −$31,85 over 63 dagen (niet gehaald; opbrengst rente $10,93 + basis $0,17, dip-koper gerealiseerd −$11,07, kosten ~$31,88); zonder dip-koper −$20,78. H2 −0,51pp (verwacht niet gehaald, zie PLAN). H3 $0 (gehaald). H4 2,77 min (brandoefening 15-09; gehaald). H5 0 gaten, 0 onmeetbaar (gehaald) | `data/kpi.json`, laatste regel; `python -m utils.kpi` 19-10 18:40 UTC |
| 3 | Verliesbewaking: geen nieuwe meldingen sinds de vorige ronde (enige `gemeld` is `meting_kpi:alarm` van 12-10 ~19:30, de opgeloste valse H5); `laatste_ronde` vers; `experimentverlies_usd` 0,0 | `data/verliesbewaking_state.json` |
| 4 | De HYPE-basis draaide 11 dagen zonder incident in de zin van de voorwaarde van 12-10: één handelende cyclus (openen 08-10 07:06), geen bijsturing, geen rem, geen kill, geen afbouw; hefboom 1,21 (band 1,0–2,0); short 0,79 ≈ spot 0,789; waarde $115,14 op inleg $115. Eén cyclus op 10-10 08:18 kon de toestand niet lezen (`laatst_fout`), de volgende wel; `fouten` staat op 0 en de Telegram-drempel (`FOUTEN_MELDEN`) is niet geraakt | `data/basis_hype_state.json`; `utils/basis_hype.py:355-378` |
| 5 | Kasbeheer heeft niets onderweg: `pending_count` 0, alle 16 proposals DEPLOYED/COMPLETED, geen brugveld in `treasury_state.json` | `treasury_state.json` |
| 6 | Maandagavond na 20:00 UTC is gelijkwaardig aan de zaterdag voor wat de zaterdag beschermde (stilstand van ~5 min terwijl de beurzen dicht zijn): de VS-aandelenmarkt is dicht tot 13:30 UTC; de dip-koper heeft daarnaast de beursstops op −30% bij HL. Wat NIET gelijk is: de eerste nazorgdagen zijn handelsdagen i.p.v. weekenddagen | eigen redenering; `docs/audits/2026-10-06-e2micro.md` r57, r88 |
| 7 | De HYPE-basis (live sinds 08-10, na de A2 van 06-10) verandert het risico van de wissel nauwelijks: bij hefboom 1,21 op de short ligt liquidatie ver weg (> +60% HYPE); de software stuurt alleen bij buiten 1,0–2,0, en het afbouwen hoeft niet binnen minuten | `data/basis_hype_state.json`; `config/experimenten.json` basis_hype |
| 8 | Deploy raakt geen geldcode: diff `1127550..HEAD` buiten docs/research = `config/experimenten.json` (alleen idee-entries, live entries basis_hype/dip_koper ongewijzigd) + `scripts/overzicht.py` (+4 regels) | `git diff 1127550 HEAD --stat`; vergelijking per entry 111c6c9^ vs 111c6c9 |
| 9 | basis_scan_hl, papier: geen canonieke munt haalt de lat (≥ 5,2% in elk halfjaar ≥ 120 dagen, geen verliesmaand, niet gedragen door één maand). XMR haalt alle criteria (19,7%/jr, 15-01 t/m 19-10), maar de spotpoot XMR1 is een niet-canoniek, custodiaal token van Wagyu.xyz zonder gevonden reservebewijs; de premie wordt daarom geboekt als bewaarrisico, niet marktneutraal. Volgende trede = schaduw (gratis), geen geld zonder reservebewijs + akkoord Bart | `python scripts/basis_scan.py`; `spotMeta` token 404 (`isCanonical: false`, `fullName: "XMR - Wagyu.xyz"`); spot @260 vs perp XMR dagslot 306 dagen p5 −0,64% p95 +0,42%; zoekresultaat (yellow.com/xmr1, verwijst naar xmr.club over een gepauzeerde terugweg in juli 2026) |
| 10 | Uitschieterpotje gestopt: botst met het mandaat van 12-10 (nooit richting voorspellen) en kopers van loterij-achtige aandelen betalen gemiddeld een premie (MAX-effect); stond 14 dagen op trede 0 zonder schaduwontwerp | `docs/besluiten.md` 12-10; register-entry |

## Raakt deze KPI's / poorten
- H1 (e2-micro −$81/jaar), H4 (waakhond tijdens de wissel), M4 (poort `scripts/e2micro_poort.py`, ongewijzigd, niet opgerekt; nazorg 19-10 → 26-10).
- Motor: één idee een trede verder (basis_scan_hl → 2), één gestopt (uitschieterpotje), e2-micro van papier naar uitvoering.

## Risico en terugdraaien
- Wissel: geheugendruk op 1 GB → trage cycli of OOM; dan staan kasbeheer, de software-stops van de dip-koper (~$257) en het bijsturen van de HYPE-basis ($115) stil tot de terugdraaiing. Beursstops −30% begrenzen de dip-koper. Kasbeheer ($2.497 in Aave) heeft de swarm niet nodig om veilig te blijven.
- Terugdraaien wissel: `stop` → `set-machine-type e2-small` → `start` (~5 min, 21-09 bewezen); snapshot vooraf (`voor-e2-micro-20261019`), bewaren tot ≥ 02-11.
- Terugdraaien config: vorige versie van `config/experimenten.json`/`config/agenda.json` en opnieuw deployen (pas na de nazorg, of de nazorg begint opnieuw).
- Nazorg: niemand draait dagelijks het poortscript (geen sessies verwacht vóór za 24-10). Wat dan wel vangt: waakhond (hartslag weg → e-mail + Telegram), Check CYCLE_FROZEN (> 25 min), Check 24. Het eindoordeel meet het hele venster achteraf met `--vanaf/--tot`; agenda 27-10 + zaterdagbericht 24-10 dwingen de sessie af.

## Wat ik zelf niet heb gecontroleerd
- Of een e2-micro onder druk het houdt: dat meet de nazorg.
- Of de ballon de poort weer beslist (A2 06-10 verwachtte dat de kans fors is).
- De reservering van Wagyu zelf: geen reservebewijs gevonden is niet hetzelfde als "geen reserves"; ik heb docs.wagyu.xyz niet gelezen.
- Of de vijf ideeën van 12-10 deze week een trede verder hadden gekund; alleen basis_scan_hl is opgepakt.

---

## Audit

**A4 + A2-aanvulling, controle-agent, 2026-10-19: GO-mits** (0 blokkerend / 4 belangrijk / 7 klein). Deployen en wisselen vanavond mag, nadat V1–V5 zijn afgehandeld. (De auditor leest alleen; de bouwer heeft deze tekst overgenomen uit zijn rapport.)

**Antwoorden op de zes vragen**
1. **Voorwaarde HYPE-basis gehaald.** HL `userFillsByTime` 0xa059 sinds 05-10: alleen twee fills, 08-10 07:07 (spot + short). Cloud Logging sinds 08-10: één fout, 10-10 08:18:37 `HTTP Error 502: Bad Gateway (fout 1 op rij)`. Docker-logs sinds 12-10: 0 BasisHype-fouten. Liquidatie 135,996 (+74,8% boven 77,82), spot 0,7895 tegen short 0,79, funding +$0,198, geen melding. Een eenmalige 502 zonder gevolg is geen incident.
2. **Geen oprekking van de poort**: criteria en drempels zijn ongewijzigd. Wel een afwijking van Barts gedateerde besluit. "Gelijkwaardig" klopt niet: de twee laatste stops van de dip-koper vuurden juist in dit venster (zie bevinding 4). In dollars is het verschil klein (beursstop −30% tegen software −25%, ~5% van een positie die in die 5 minuten zou vuren). Mag zonder vooraf vragen, mits vastgelegd en gemeld (V2). Wissel vroeg (20:05 tot ~21:30 UTC), niet tegen 00:00 UTC (opening Tokio, KIOXIA).
3. **Voor het geld verantwoord, onder V3.** Waakhond-policy "Swarm stil - geen hartslag" staat aan (afwezigheid 900 s, 2 kanalen). CYCLE_FROZEN 0 sinds 12-10. Beursstops 6/6. Kasbeheer in Aave. Ingeleverd: de reactietijd op een geraakt criterium; h wordt alleen begin + eind.
4. **Geen geldcode, geen A1.** Md5 container tegen werkboom: alle 133 `.py` gelijk behalve `scripts/overzicht.py`; nieuw alleen `scripts/basis_scan.py`, nergens geïmporteerd. Van de niet-gemounte config verschillen alleen `agenda.json` en `experimenten.json`; `globaal`, `benchmark`, `controles`, `_motor` en alle live- en potjes-entries gelijk aan de image (9542f14), alleen negen niet-live entries wijzigen. pytest 612 groen, check_syntax 287 ok.
5. **XMR eerlijk als bewaarrisico, maar de scanconclusie klopt niet** (bevinding 1). Uitschieterpotje stoppen terecht op grond van het mandaat; formulering aanpassen en Bart informeren (bevinding 10).
6. **Getallen kloppen** met `data/kpi.json` (−31,85 / −20,78 / −0,51pp / $0 / 2,77 min / 0+0); H1 per kwartaal en de twee stops van 14-10 ontbreken (bevinding 4).

**Bevindingen**
1. **[belangrijk] Definitiefout in de scan.** `basis_scan.py` simuleerde met `lev_max=3.0`, buiten het kader van 2x. Met de live-parameters (1,5; band 1,0–2,0) haalt **NEAR alle criteria** (halfjaren 28,2 / 11,5 / 5,4 / 5,4 / 5,3, geen verliesmaand, zonder beste maand 11,0%, geen liquidatie; ONEAR $3,65 mln/dag, perp-OI ~$290 mln). `isCanonical: false` is geen bewijs van bewaarrisico: het geldt ook voor HYPE (de spotpoot van het live potje), UBTC/UETH/USOL/UPUMP en ONEAR; alleen PURR is canoniek. → V1; NEAR ook in de schaduw; bewaarargument via de uitgever.
2. **[belangrijk] PSI op de e2-small ligt al tegen de poort.** `e2micro_poort.py` op 12-10 10:00 – 19-10 10:00 (e2-small): "gehaald", maar het hoogste interval was **0,863%** (19-10 01:00, zonder ballon); sinds 06-10 **0,976%** (07-10, met ballon); op 7 dagen ≥ 1 interval ≥ 0,37%. Piek `ctr_werkelijk` 269 → 331 MiB (69 MiB marge tot 400). Op 1 GB raakt b waarschijnlijk. Geen reden om te verruimen; leg de verwachting vast en spreek af: raakt b, dan geen derde poging.
3. **[belangrijk] Twee afwijkingen van het A2-plan van 06-10 staan niet in `besluiten.md`**: de weekdag en het vervallen van de dagelijkse controle (stap 6). Een melding van de waakhond of CYCLE_FROZEN heeft geen afgesproken actie. → V2 + V3.
4. **[belangrijk] A4 onvolledig.** H1 staat over 63 dagen; het besluit van 12-10 rekent per kwartaal. Q4 tot nu toe: **−$26,72** (rente +3,86, basis +0,17, dip-koper gerealiseerd −21,19, kosten −9,56). Prognose 31-12: ≈ −$34 met e2-micro, ≈ −$50 op e2-small; het eerste gemiste kwartaal is waarschijnlijk. Oorzaak ontbreekt: twee software-stops op 14-10 (CRWV −$12,01 21:47 UTC, SKHX −$12,09 23:10 UTC) plus CRCL +$3,03 op 16-10. De stoptijden weerleggen ook bewering 6.
5. [klein] Bewering 5: 21 proposals, niet 16 (10 DEPLOYED, 6 COMPLETED, 3 FAILED, 2 REJECTED, alle uit juli). "Niets onderweg" klopt.
6. [klein] `gcloud builds submit .` bouwt de werkboom, geen commit; zwevende `python:3.11-slim` + apt worden opnieuw opgehaald. Eerst committen (V4).
7. [klein] "UITGEVOERD 19-10" (register) en "draait sinds 19-10 als e2-micro" (agenda) gaan vóór de wissel de image in; gaat de wissel niet door, dan staan ze een week fout.
8. [klein] Nulmeting en verificatie van 06-10 kennen de HYPE-basis niet. Nu: spot 0,7895, short 0,79, perp-AV $51,34, liquidatie ~$136. Na de herstart: `laatst` in `basis_hype_state.json` vers, `fouten` 0. Beursstops nu 6/6 (TSLA, ORCL, GOOGL, BABA, KIOXIA, AVGO), reduceOnly, grootte = positie, trigger ≈ −30%.
9. [klein] Oude snapshot `voor-e2-micro-20260919` (5,46 GB) staat er nog; moest volgens stap 3 van 06-10 weg.
10. [klein] Uitschieterpotje: "Barts wens blijft gediend door de schaduwpotjes" spreekt de A4 van 05-10 tegen. Eerlijk opschrijven en Bart informeren. MAX-effect-verwijzing klopt.
11. [klein] XMR-schaduw mist een vooraf vastgelegd door-criterium (MOTOR trede 2), de live-parameters (dan nog door: 17,3%, 2026-H1 15,2%) en de looptijd 2–4 weken.

**Voorwaarden:** V1 registertekst basis_scan_hl corrigeren (NEAR, isCanonical, parameters). V2 rij in `besluiten.md` (maandag, geen dagcontrole, h begin + eind, PSI-basislijn als verwachting), Bart informeren. V3 afgesproken actie bij een melding: waakhond/CYCLE_FROZEN = sessie starten en terugdraaien zonder diagnose; het venster eindigt op 26-10. V4 committen, predeploy groen, wissel dezelfde avond (anders teksten uit 7 corrigeren). V5 nulmeting en verificatie uitbreiden met HYPE-basis en de 6 beursstops.

**Zonder bevinding gecontroleerd:** container Up 7 dagen, RestartCount 0, OOM false, dashboard 200, e2-small via metadata; verliesbewaking; basis-scan herhaald (getallen bewering 9 komen terug); waakhond-policy; motor zonder signalen.

**Pre-mortem:** b raakt op dag 1–2, er komt geen sessie, en de bevriezing van deploys loopt door (10-10 en 17-10 vielen allebei weg). **Gemiste kans:** NEAR als tweede basis met een veel ruimere perp-markt dan XMR. **Open vragen:** welke brug geeft ONEAR uit, met reservebewijs? Wat gaf PSI 0,86% op 19-10 01:00 zonder ballon (rond 01:00:43 draaide `gce-workload-cert-refresh`)?

## Reactie bouwer
- **V1 / bevinding 1, 11** — opgelost. `scripts/basis_scan.py` draait nu met de live-parameters (`LIVE`, hefboom 1,5, band 1,0–2,0). Herhaald: NEAR en XMR door, HYPE zelf 2026-H1 4,5%. Registertekst: bewaarrisico via de uitgever (HYPE native, XMR1 Wagyu, ONEAR uit te zoeken), niet via `isCanonical`. Schaduw 19-10 t/m 16-11, met de live-parameters en een vooraf vastgelegd door/stop-criterium.
- **V2 / bevinding 2, 3** — opgelost: rij 19-10 in `besluiten.md` met de weekdag, geen dagcontrole, h begin + eind, PSI-verwachting en "raakt b → geen derde poging". Bart wordt geïnformeerd in de afsluitende melding.
- **V3** — opgelost in register (`e2_micro_poging_2`), besluitenrij en agenda (27-10): melding = sessie starten en "terugdraaien", zonder diagnose; het venster eindigt op 26-10.
- **V4 / bevinding 6, 7** — commit vóór de deploy, predeploy opnieuw groen, wissel dezelfde avond.
- **V5 / bevinding 8** — nulmeting en verificatie uitgebreid met de HYPE-basis (`laatst`, `fouten`, spot/short) en de 6 beursstops.
- **Bevinding 4** — H1 per kwartaal (Q4 −$26,72, prognose ≈ −$34) en de twee stops van 14-10 gaan naar Bart als KPI-melding: het eerste gemiste kwartaal is waarschijnlijk.
- **Bevinding 5** — erkend; conclusie ongewijzigd.
- **Bevinding 9** — de oude snapshot gaat weg na het maken van de nieuwe.
- **Bevinding 10** — registertekst eerlijk gemaakt; Bart wordt geïnformeerd.
- **Open vragen** — ONEAR-uitgever is een stap in de schaduw; de PSI van 19-10 01:00 is niet uitgezocht.

## Uitvoering 19-10
- **Deploy** `f210667`: 19:51:21 UTC containerstart, 10/10 live-checks, dashboard 200, md5 `config/experimenten.json` en `config/agenda.json` container = repo, motor op de VM toont de nieuwe stand.
- **Nulmeting** (19:55–20:01): NAV $5.419,77; HYPE-basis `laatst` 20:00:05, `fouten` 0, spot 0,7895 / short 0,79, perp-AV $51,46, hefboom 1,19, waarde $115,11; 6/6 beursstops reduceOnly (KIOXIA, GOOGL, AVGO, BABA, ORCL, TSLA), grootte = positie; kasbeheer niets onderweg.
- **Snapshot** `voor-e2-micro-20261019` READY om 20:00 (bewaren tot ≥ 02-11); oude `voor-e2-micro-20260919` verwijderd (bevinding 9).
- **Wissel**: `stop` 20:05:10 → `set-machine-type e2-micro` → `start` 20:06:44. Nieuwe boot `c249c179…` om 20:06:55, precies één nieuwe boot. Container start 20:07:29, alle agents 20:08:52, dashboard 200 om 20:09:47 (opstart 84 s). `RestartCount` 0, OOMKilled false, 0 OOM in dmesg, cron `mem_sample.sh` actief. Extern IP gewijzigd 34.34.188.126 → 34.156.42.122 (efemeer, zoals op 21-09).
- **Na de wissel**: NAV $5.420,57 (koersverschil); 6/6 beursstops; 70 JSON-bestanden gelezen, twee leeg (`polymarket_shadow_log.json`, `treasury_harvest.json`, 0 bytes sinds 16-07, geseed en ongebruikt: geen gevolg van de wissel).
- **Opstartdruk**: PSI-memory `some` avg10 4,34% / avg60 2,77% om 20:09:47, tijdens het laden. **Venster voor het eindoordeel: `--vanaf 2026-10-19T20:07:30Z --tot 2026-10-26T20:07:30Z`.** Het script rekent intervallen pas vanaf de eerste meting in het venster (20:15), dus de opstartpiek valt buiten criterium b. Dat is een keuze, hier open vastgelegd: de A2 van 06-10 liet de nazorg "van de herstart" lopen, en een opstart is een eenmalige gebeurtenis. Niet gemeten: hoe zwaar dezelfde opstart op de e2-small was.
- **Eerste tussenstand 20:40 UTC** (host-side, zonder exec): 2 metingen, piek `ctr_werkelijk` 232 MiB, hoogste PSI-interval 0,203%, swap 64 → 88 MB. Zonder `--tot` meldt het script "GERAAKT" op de volledigheidstoets (`scripts/e2micro_poort.py:136-138`): 2 metingen tegen ~2,2 verwacht, omdat het venster op een tijdstip tussen twee metingen eindigt en de eerste meting pas 7,5 min na `--vanaf` valt. Met `--tot 2026-10-19T20:30:06Z` (laatste meting): "POORT: gehaald". **Regel voor tussentijdse controles: altijd `--tot` = tijd van de laatste meting.** Voor het eindoordeel geldt dit niet: 19-10 20:15 t/m 26-10 20:00 = 672 metingen tegen 672 verwacht. Het poortscript is tijdens de nazorg niet gewijzigd.
