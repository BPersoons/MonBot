# Claimblad — werkronde 17-11 (gepland): KPI-stand, deploy H1-meetfix, aandelen-basis, nieuw idee

*Datum: 2026-11-17 · Poort: A4 wekelijks + bevestiging deploy (A1 van 10-11) · Mijlpaal: M5/M7*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.
> Geplande ronde zonder mens; niets gecommit of gedeployed vóór deze review.

## Wat er verandert
- **Deploy (nog niet uitgevoerd):** de H1-meetfix van 10-11 (`utils/dip_netto.py`, `utils/kpi.py`, monitor-cooldown, overzicht) staat sinds 10-11 in git maar niet op de VM (md5 container ≠ werkboom voor `utils/kpi.py`, `utils/agenda.py`, `config/agenda.json`; `utils/dip_netto.py` ontbreekt in de container). A1 r2 van 10-11: GO-mits, voorwaarden verwerkt, "een derde ronde is niet nodig". Sindsdien alleen tekst in `config/experimenten.json` en `CLAUDE.md` gewijzigd (`git diff --stat 7d5e1f2 HEAD -- . ':!docs' ':!research' ':!data'`).
- `config/experimenten.json`: `basis_aandelen_token` › `volgende_stap` (meting 5,5%), `dip_koper` › `volgende_stap` (stops 5 en 6), nieuw idee `mm_aandelentoken_spot` (trede 0, status `idee`, zonder potje).
- `config/agenda.json`: regel 17-11 "herbeoordeling naar voren halen?" vervangen door de twee open vragen van 16-11 (dip-koper stoppen; nieuwe HLP-poort).
- `docs/besluiten.md`: twee regels. Lokale venv: vier pakketten op de pin gezet (geen repo-wijziging).
- Productie-impact van de deploy: H1 wordt vanaf de eerstvolgende KPI-run (00:0x UTC) netto uit HL berekend; de agenda-melding op de VM stuurt de nieuwe regels. Geen orders, geen geld, geen statebestanden.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Productie gezond: container 2 weken up, RestartCount 0, dashboard 200, 275 MiB, host 1.323 MB beschikbaar. 7 dagen logs: 0 CYCLE_FROZEN/OOM; 18 tracebackregels = 6 incidenten Cloud Logging 504 (RetryError + InactiveRpcError) | stap-1-commando ~08:00 UTC; `docker logs --since 168h` |
| 2 | KPI 17-11 00:04 (oude definitie, eigen boek): H1 −$58,61 (88 d, voorlopig; opbrengst −$19,24, kosten $39,37, dip-koper −$36,00) · H2 −0,17pp (2,78% vs 2,953%) · H3 $0 · H4 2,77 min, alles gevonden · H5 0 gaten, 0 onmeetbaar | `data/kpi.json` › `history[-1]` |
| 3 | Top-level `aave_apy_pct` is vandaag `null`; H2 rekent met het gemiddelde over de beschikbare dagen (`kpi.py:284`), dus één ontbrekende dag is geen gat. Niet als onbetrouwbare KPI gemeld | `kpi.json` › `history[-8:]`; `utils/kpi.py:281-286` |
| 4 | Verliesbewaking draait (`laatste_ronde` 2 min oud), `onmeetbaar` leeg, experimentverlies $0; geen nieuwe `gemeld` (de twee zijn van 12-10 en 23-10) | `data/verliesbewaking_state.json` |
| 5 | Dip-koper: **zesde stop in Q4**. CRCL −$10,44 (14-11 22:57), BABA −$11,05 (17-11 01:41, 88,04 tegen 119,09 = −26%). HL accountValue $219,05 = 25,1% onder de top $292,39. 5 posities, 5 beursstops, alle Stop Market, reduceOnly, sz = szi | `trade_log.json`; HL `clearinghouseState` + `frontendOpenOrders` dex xyz, ~08:30 UTC |
| 6 | Kleine afwijking: CRWV staat in het boek op 0,75, bij HL op 0,74 (~$0,50) | idem |
| 7 | HYPE-basis: $115,73 op $115 inleg, hefboom 1,33, spot 0,949 vs short 0,95; laatste fout 14-11 (geen bijsturing nodig gebleken). Kill (50%) ver weg; evaluatie 08-12 | `data/basis_hype_state.json` |
| 8 | NAV $5.277,71 (10-11: $5.309,84) | `python -m utils.nav`, ~08:30 UTC |
| 9 | Geen poort vandaag aan de beurt: eerstvolgende `rente_ladder` 24-11, `basis_scan_hl`/HYPE-basis 08-12, dip-koper en thema-radar 22-12, schaduwpotjes 22-03 | `config/experimenten.json` › `herzien`; `docs/besluiten.md` |
| 10 | **5,5%/jr is de vaste rentecomponent van de xyz-dex**: 0,000625%/uur = 5,475%/jr. *(Gecorrigeerd na r1, gepagineerd:)* laatste 500 uur (27-10 → 17-11) NVDA 41 / GOLD 54 / TSLA 70% van de uren exact op die waarde, gemiddeld 9,41 / 7,09 / 4,72%/jr; 180 dagen 54 / 63 / 58%, 9,15 / 7,81 / 5,90%/jr. Op kapitaal bij 2x zonder onderpandwerking: vloer 3,65%, met de gemiddelden 3,1-6,3%, rond de lat | HL info `fundingHistory` (coin `xyz:NVDA` enz.) en `metaAndAssetCtxs` dex xyz, 17-11 |
| 11 | Motor: geen signalen; deze week bewogen `basis_scan_hl` (schaduw af, 16-11), `rente_ladder`, `hlp_vault`, `basis_aandelen_token` (16-11) en nu één nieuw idee op trede 0 (afspraak PLAN 16-11: elke werkronde tot M7 één nieuw idee) | `python -m utils.motor` |
| 12 | Deploy-poort groen: `venv/Scripts/python.exe scripts/predeploy.py` (state-audit, syntax, 645 passed, pipeline) en `tests.pre_flight.check_connections` slaagt nadat de venv op de pins is gezet (ccxt 4.5.35 brak in `fetch_spot_markets`) | lokaal 09:08 en 09:13 |

## Raakt deze KPI's / poorten
- H1 (definitie wordt live met de deploy; verwachte sprong door de netto-telling uit HL). H5 kan "onmeetbaar" tonen als HL faalt — dat is het ontwerp.
- Geen poortbesluit, geen kapitaalbeweging. Open bij Bart: dip-koper stoppen (A2 bij akkoord), nieuwe HLP-poort.

## Risico en terugdraaien
- Deploy: geen geldcode gewijzigd sinds A1 10-11; een full deploy recreëert de container (hot-patches weg — er staan er geen buiten git voor zover gemeten). Max op het spel: geen geld, wel een dag KPI-meting.
- Terugdraaien: vorige image-digest via `deploy.ps1` op de vorige commit, of `git revert` + deploy.

## Wat ik zelf niet heb gecontroleerd
- (Wel gecontroleerd, na het schrijven: alle 134 `.py` in de container, zonder `\r`, tegen git. Geen onbekende inhoud; alleen oudere git-versies van `agents/swarm_monitor.py` (096584f), `scripts/overzicht.py` (111c6c9), `utils/kpi.py` (eb8e758), `utils/agenda.py` (9542f14) en `research/uitstapsignaal.py` (36a8cc4). Dus geen hot-patch die de deploy wist.)
- H2 vergelijkt nog met Aave Arbitrum, de meetlat sinds 16-11 is de T-bill-rente + 2pp; de KPI beantwoordt dus de oude vraag. Niet aangepast in deze ronde (meetcode → eigen A1).
- De funding-meting dekt ~21 dagen (API-limiet 500 rijen), geen 180 dagen.

---

## Audit
**r1 (2026-11-17), ingekort uit het rapport: GO-mits. Deploy mag na V1 en V2. Ronde: `MELDEN: ja`.**

1. **[belangrijk]** De twee vragen met datum 17-11 bereiken Bart niet: de VM stuurt de agenda één keer per dag rond 00:04 UTC, vanmorgen nog met de oude image. Na de deploy pas zaterdag, als "achterstallig" en zonder uitleg. **V1:** datum 18-11.
2. **[klein, definitie]** "Laatste 500 uur" was het venster 18-10 → 08-11 (`startTime` = nu − 30 d geeft de oudste 500 rijen). Echt laatste 500 uur: NVDA 41% / 9,41%, GOLD 54% / 7,09%, TSLA 70% / 4,72%. Conclusie (vaste component 5,475%/jr) blijft.
3. **[klein]** 3,65% op kapitaal is een vloer, geen verwachting; met de gemeten gemiddelden 3,1-6,3%.
4. **[klein, procedure]** De image wordt uit de werkboom gebouwd: niet-gecommitte config en de ongetrackte `.agents/` en `skills-lock.json` gaan mee. **V2:** eerst committen, beide buiten de build.
5. **[belangrijk, bestond al]** `.env.adk` (met o.a. `HL_PRIVATE_KEY`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`) zit in de image (`/app/.env.adk`, rw-rw-rw-) en in elke Cloud Build-upload; niet in `.gcloudignore`. Eigen A1; eerst de terugval `load_dotenv(".env.adk")` in `agents/swarm_monitor.py:3211` nagaan.
6. **[klein]** Agendatekst eenzijdig: ~$68 is bruto, netto Q4 uit HL −$56,90 (drie winnaars +$11,25); WEBN is wereld, geen Nasdaq; eigen funding 19-10 → 11-11 ~8,2%/jr.
7. **[klein]** `mm_aandelentoken_spot` binnen het mandaat; funding alleen bij netto long-voorraad, adverse selectie in de papiervragen.
8. **[klein]** CRWV 0,75 vs 0,74: `thematic_exposure_lab.py:1162-1172` boekt gevraagde quantity tegen mark_price. ~$0,50; eigen A1.
9. **[klein]** "Sindsdien alleen tekst" klopt niet letterlijk (status/trede/herzien en nieuwe regels t.o.v. de VM-config); geen regel met `sleeve`, H3 en verliesbewaking ongewijzigd.

Nagerekend zonder bevinding: dip-koper bij HL ($219,13, 25,05% onder top, 5 posities/5 stops reduceOnly), zes verliezende sluitingen, KPI, verliesbewaking, HYPE-basis, deploy-omvang (alleen swarm_monitor, kpi, agenda, overzicht, dip_netto), geen infra-wijziging, 645 passed, 293 syntax OK. Niet nagerekend: NAV.

## Reactie bouwer
1. **Verwerkt:** beide regels op 18-11; Bart krijgt ze ook via de melding van deze ronde.
2. **Verwerkt** gepagineerd in `experimenten.json`, `besluiten.md` en bewering 10. De 180d-tabel van 16-11 klopt (NVDA 9,15% gepagineerd; `scripts/funding_historie.py` pagineert).
3. **Verwerkt** ("vloer", 3,1-6,3%).
4. **Verwerkt:** `.agents/` en `skills-lock.json` in `.gcloudignore`; commit vóór de deploy.
5. **Open, gemeld aan Bart.** Niet in deze ronde: het weghalen kan de terugval van de monitor breken; eigen A1. De sleutels zelf roteren is Barts keuze.
6. **Verwerkt** in de agenda (netto −$57, ~8%, indexfonds) en in `dip_koper`.
7. **Verwerkt** in de papiervragen.
8. **Open**, vastgelegd in `dip_koper`; eigen A1.
9. Erkend; geen gevolg.
- Modern Standby: de geplande ronde startte vandaag om 09:00 en liep door (`logs/werkronde/2026-11-17_0900_gepland.log`). Punt 6 van 10-11 gesloten.
