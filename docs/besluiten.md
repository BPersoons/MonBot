# Besluitenlog

Alleen toevoegen, nooit herschrijven. Een besluit terugdraaien is een **nieuwe regel** die
naar de oude verwijst. Doel: afgesloten keuzes niet opnieuw bediscussiëren zonder nieuwe
data, en zien wanneer een besluit herzien moet worden.

Details staan in `docs/PLAN_2026-08.md`, de commits en `docs/audits/`. Hier alleen de kern.

| Datum | Besluit | Reden (kort) | Maatstaf / poort | Herzien wanneer |
|---|---|---|---|---|
| 2026-08-10 | **Handelsbot gepauzeerd** — `score_threshold` 0,40, armed-gate AAN | 800/800 NO_GO, −$27 over 170 trades, F1 `edge_ok=false`. `armed_mode=false` zou de funnel juist openen | — | alleen na een gevalideerde her-tune |
| 2026-08-10 | Koers: **onderzoekscadans i.p.v. handelssysteem**; Fase A = 60% veilig / 40% wereldindex | vier families richtingsvoorspelling weerlegd | poort selectie ~10-02-2027: versla WEBN over 6 mnd, ≥20 namen | bij €25k (Fase B) |
| 2026-08-12 | VM **niet** opheffen (alles naar GitHub Actions afgewezen) | hartslag, monitor en reactietijd zijn nodig bij groter kapitaal; $73/jaar verdampt bij schaal | — | — |
| 2026-08-12 | Crypto vasthouden: target $550 → **$130** (5%) | Fase A laat geen crypto-been van $550 toe | — | Fase B |
| 2026-08-17 | Wereldindexfonds = **WEBN** (Amundi Prime All Country World) | 0,07%, ontwikkeld + opkomend, herbeleggend | `docs/KERN_ETF_KEUZE.md` | — |
| 2026-08-18 | **Twee potjes naast elkaar**: crypto/USDC blijft, DeGiro met verse euro's; uitstap-route in de ijskast | geen conversie, geen netwerkrisico | — | alleen met een reden om tussen crypto en fiat te schuiven |
| 2026-08-20 | WEBN gekocht (156); 20 verkocht voor GRID-testpositie | GRID-test financieren — **bewust tegen plan-regel 5** | kern-doel 40% blijft | 2026-09-25 |
| 2026-08-20 | Thema-volgorde volgt de kaarten: **stroom en net** slot 1, halfgeleiders geschrapt; brug XYZ-SMH gesloten | halfgeleiders dupliceren de kern en zijn het drukste thema | opent pas bij €25k | €25k, met verse afweging |
| 2026-08-24 | Scorekaart meet tegen **WEBN in euro's** (niet URTH in USD) | meet tegen wat je bezit, in één valuta | — | — |
| 2026-08-25 | Bijstorten kern (~€220) **uitgesteld**, doel 40% blijft | eerst de swarm operationeel bewezen zien | — | 2026-09-25 |
| 2026-08-25 | Dip-koper: inzet groeit mee met het potje; meelopende winstbescherming live | vaste inzet mat een strategie die nooit herbelegt | — | 2026-09-25 (maand live) |
| 2026-09-15 | Dip-koper **door zonder extra geld** | verlies in bear begrensd (~$50); regime-poort voegde over 16 jaar niets toe | `experimenten.json` alarm DD 15% | 2026-09-25 |
| 2026-09-15 | Aave (veilig) **laten staan**, kern vullen met verse euro's | Fase A zoals besloten | H2 | — |
| 2026-09-15 | **Handelspijplijn uit** (`subsystem_handelspijplijn_enabled=false`) + VM naar **e2-micro** | vijf weken gepauzeerd maar scande nog; kosten > opbrengst | M4-poort: 24u container < 450 MiB | — |
| 2026-09-15 | Doel: **project netto winstgevend** via structurele bronnen; verliesbudget experimenten **$250**; HLP ≤ **1/3 van veilig** | richting voorspellen werkt niet; rente, market-making en funding wel | H1–H5, mijlpalen M1–M7 | 2026-12-31 (M7) |
| 2026-09-15 | Scorekaart: NaN nooit meer stil; 16 meetdagen hersteld | drie weken NaN met een groene CI | `test_ledger.py` faalt op NaN | — |
| 2026-09-15 | **Controle-agent met veto** op deploys van code die geld raakt (A1) en kapitaalbewegingen (A2) | vrijwel elke dure fout werd pas bij een tweede blik gevonden | eigen KPI's in `docs/audits/logboek.md` | M5: drie reviews zonder waarde → alleen A1/A2 |
| 2026-09-15 | Fluid: **geen geforceerde volledige switch** — de risico-gecorrigeerde regel (1,5pp) blijft | het profiel ophogen zou een poort oprekken | M3 | na 14 dagen gemeten APR |
| 2026-09-15 | Trage basis-trade (M6) **nu niet live**; heractiveren op een regime-trigger, niet op een datum | backtest haalt de poort (8,2% over 2023–2026), maar het huidige regime levert 180d 4,4% (2x) / 3,3% (1x) tegen Fluid 5,5% zonder exchange- en liquidatierisico; spot telt op de unified account niet als onderpand | trigger: gerealiseerde portefeuille-funding BTC/ETH/HYPE over 30d ≥ Fluid-APY + 3pp → dan 3 weken shadow | maandelijks in `/werkronde` (trigger meten met `scripts/basis_backtest.py`) |
| 2026-09-15 | Kasbeheer: **geen gelijktijdige bewegingen naar yield** (uitsluiten i.p.v. geld onderweg meetellen in de cap) | twee gecapte bewegingen tegelijk konden samen boven 65% per protocol uitkomen; uitsluiten is eenvoudiger en toetsbaar, en kost alleen wachttijd | cap 65% per niet-benchmark-protocol (`experimenten.json`) | als een DEPLOY_YIELD in NEEDS_MANUAL_WITHDRAWAL switches langdurig blokkeert |
| 2026-09-15 | **Correctie** op de vorige regel: de regel gold niet in `run_fast` (APPROVED-switch telde niet). Nu één definitie `_yield_beweging_onderweg` op alle vijf plekken; een handmatige HL-opname verloopt na **48u** (EXPIRED) | A1-hertoets vond het gat; een blijvende blokkade moet zichtbaar zijn en eindigen | monitor meldt NEEDS_MANUAL_WITHDRAWAL > 6u | als 48u te kort blijkt voor een echte handmatige opname |
| 2026-09-16 | **Dashboard niet meer publiek**: drie firewallregels `tcp:8080` vanaf `0.0.0.0/0` verwijderd; toegang via SSH-tunnel | `POST /api/treasury/approve` keurt zonder wachtwoord een voorstel goed én voert het direct uit on-chain; dashboard gaf extern HTTP 200 met saldi. Besluit Bart 2026-09-16 | extern `curl` moet falen, intern 200 | als het dashboard vaker nodig is: tokencontrole bouwen (dan pas weer openzetten) |
| 2026-09-16 | **Infra opgeruimd**: oude VM `agent-trader-vm` + schijf (20 GB) verwijderd; images teruggebracht van 44 naar de 5 nieuwste | ~$27/jaar op ~$160/jaar totaal. Schijf eerst read-only geïnspecteerd: geen bind mounts, geen state, geen sleutels — alleen containers uit februari. Terugrollen gaat via git + opnieuw bouwen. Besluit Bart 2026-09-16 | M4 (≤ $0,25/dag) | — |
| 2026-09-16 | **Niet vragen voor routinewerk** (pushen, deployen, herstarten, opruimen binnen een genomen besluit) — wél altijd de controle-agent op code die geld of meting raakt | "Laat mij geen blokkade zijn"; kwaliteitsborging loopt via A1/A2, niet via Barts goedkeuring | escape rate controle-agent = 0 | als een A1-GO ooit een fout doorlaat |
| vóór 2026-08-23 | Ethereum-wallet (~$37.800) **bewust buiten het plan** | eigen besluit van Bart | — | niet opnieuw voorstellen |
