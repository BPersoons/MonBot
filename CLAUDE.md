# Agent Trader

Een autonoom beheerd vermogen op een GCP-VM (Docker) plus een papieren onderzoekslijn in
GitHub Actions. Begonnen als crypto-handelsswarm; sinds 2026-09-15 is het doel **het project
netto winstgevend maken via structurele bronnen** (rente, market-making, trage basis-trade),
lagere kosten en een kern die meegroeit met inleg. Richting voorspellen is weerlegd.

**Lees eerst, in deze volgorde:**
1. `docs/PLAN_2026-08.md` § **"Plan 2026-09-15"** — doelen H1–H5, KPI's, mijlpalen M1–M7, kaders.
2. `docs/besluiten.md` — wat al besloten is (niet opnieuw bediscussiëren zonder nieuwe data).
3. `docs/NAMEN.md` — cryptische codenamen → gewone taal.
4. `docs/MOTOR.md` — de motor: idee → papier → schaduw → proeftuin → schalen. Stand: `python -m utils.motor`.
5. `/werkronde` — de vaste volgorde voor autonoom doorwerken.

Diepere naslag (letterlijk verplaatst uit deze file op 2026-09-15): `docs/valkuilen.md` ·
`docs/kasbeheer.md` · `docs/statebestanden.md` · `docs/strategie_historie.md`.

## Kaders (Bart, 2026-09-15)

- Verliesbudget experimenten **$250** (alarm $125); proeftuinkapitaal **$500** in totaal, max 50% verlies per potje, geen vast maximum aantal (Bart 22-09, `docs/MOTOR.md`). HLP ≤ **1/3 van het veilige potje**; ≥ 2/3 van veilig direct opneembaar. Hefboom ≤ 2x.
- **Nooit** geld uit DeGiro of de Ethereum-wallet. Nieuw kapitaal, nieuwe venue of een verruimde drempel: eerst vragen.
- **Geen experimentgeld vóór de meter er staat** (KPI's + verliesbewaking).
- Melden aan Bart **alleen** bij mijlpaal, poort, kill, budget ≥ $125 of een onbetrouwbare KPI. Kort: conclusie + aanbeveling.

## Werkwijze: bouwer + controle-agent

- **Controle-agent** `.claude/agents/auditor.md`: leest alleen, krijgt een claimblad (`docs/audits/_sjabloon.md`), oordeelt GO / GO-mits / STOP met bewijs. **STOP = veto** vóór een deploy van code die geld raakt (A1) en vóór elke kapitaalbeweging of poortbesluit (A2). Logboek met zijn eigen KPI's: `docs/audits/logboek.md`. Haalde zijn mutatietoets op 2026-09-15.
- **Pre-deploy-poort:** `python scripts/predeploy.py` — state-audit (compose vs `STATE_FILES`) + syntax + pytest + check_pipeline, faalt luid. `--snel` slaat de pipeline over.
- **Drempels op één plek:** `config/experimenten.json` (in de image, niet gemount).
- Poorten worden **nooit** opgerekt.

## Architectuur

```
main.py (Heartbeat, 60s-cycli)
  -> ProjectLead + ResearchAgent (Scout) + analisten + ExecutionAgent   [handelspijplijn: UIT sinds 2026-09-15]
       -> StrategyManager — beheer open posities (Phase 3.5, blijft AAN; leest trade_log.json)
  -> TreasuryAgent (kasbeheer) — USDC over Aave/Fluid/Morpho + HL; full run elke 60 cycli, fast elke 5
  -> ThematicExposureLab (dip-koper) — eigen wallet 0xBd6c, xyz-perp-dex
  -> ConvictionCore (crypto vasthouden) — BTC/ETH spot op 0x92D4
  -> SleeveNAV — dagelijkse potjes-snapshot (data/sleeve_nav.json), incl. broker
       -> utils/kpi.py — KPI's H1–H5 -> data/kpi.json
  -> SwarmMonitor — watchdog-thread, elke 5 min, 26 checks
       -> Check 24: utils/verliesbewaking.py (share price, saldo, USDC-peg, HLP, budget, meting)
       -> Check 26: ETH voor gas op treasury- en hoofdwallet (< 15 transacties = melding)
  -> DashboardServer — HTTP 8080
```

Uitgeschakeld via `subsystem_<naam>_enabled` in `config/auto_params.json` (gelezen door
`utils.auto_params.subsysteem_aan`, één definitie voor main.py én monitor): `handelspijplijn`,
`shadow_basis`, `shadow_xyz_lab`, `swarm_learner`. De monitor slaat pijplijnchecks over als de
pijplijn uit staat. De pauze van de handelsbot staat daarnaast nog op `score_threshold` 0,40 met
de armed-gate **aan** (`armed_mode_enabled=false` zou de funnel juist openen).

## Namen

De namen (Conviction Barbell, sleeves, EXP-008, F1, Fase A/B/C) zeggen van zichzelf niets —
**`docs/NAMEN.md`** vertaalt ze. Gebruik in gesprek de gewone naam. De drie die het vaakst verward worden:
- **Kopen en vasthouden** (Conviction Barbell) ≠ het **wereldindexfonds** (kern-ETF, WEBN).
- **Kasbeheer** (treasury) kan **geen** aandelen/ETF's kopen — alleen USDC op Arbitrum en Hyperliquid.
- **Handelsbot** (F1 / armed-gate trader): gepauzeerd sinds 2026-08-10, pijplijn uit sinds 2026-09-15.

## Key directories

```
agents/          — agent-klassen (project_lead, execution_agent, treasury_agent, swarm_monitor, …)
core/            — agent_weights.json, circuit_breaker.py, strategy_logic.py, equity_regime.py
config/          — auto_params.json (gemount), experimenten.json (image), treasury_protocols.json (image), sleeves.json (gemount)
utils/           — exchange_client, treasury_executor/risk/yield_oracle, nav, sleeve_nav, flows, kpi, verliesbewaking, thematic_exposure_lab, …
scripts/         — deploy_update.sh, predeploy.py, sleeve_harness.py, basis_backtest.py, …
tests/           — pytest-suite + tests/pre_flight/ (check_syntax, check_imports, check_pipeline, check_treasury)
docs/            — PLAN_2026-08.md, besluiten.md, audits/, NAMEN.md, valkuilen.md, kasbeheer.md, …
research/        — papieren aandelenanalyse; LOS van de swarm, draait in GitHub Actions
.claude/         — commands/ (skills), hooks/, agents/auditor.md
```

## Research-lijn (`research/`)

Papieren analyse van aandelen tegen het wereldindexfonds; draait **niet** op de VM maar in
`.github/workflows/scorekaart.yml` (`ledger.json` staat in git, dus de repo is de bron).
Framework: `research/README.md`. Meting: `research/track.py` (`meet` · `due` · `dashboard` ·
`check` · `fundamentals` · `herstel`). Benchmark: **WEBN in euro's** (namen omgerekend via EURUSD).
`research/test_ledger.py` (525 controles) faalt ook op NaN in `tracking.json`. Poort ~2027-02-10.

Regels die niet vanzelf spreken: **onmeetbaar ≠ gehaald** (`partial` → DEELS) · screen op de
200d-MA, niet op 52 weken · tel kwartaalregels op, vertrouw geen samengevat veld · een
screen-treffer is een kandidaat · **NaN is geen None** (guard op `math.isfinite`).

## Statebestanden — de regels

Volledige tabel: `docs/statebestanden.md`.
- Runtime-state die een redeploy moet overleven: **compose-mount én `STATE_FILES`** in `scripts/deploy_update.sh`. `predeploy.py` controleert dit. Of zet hem onder `data/` (hele map gemount).
- Hand-onderhouden **gemounte** config heeft **vier** plekken: mount, backup-lus, seeding-lus, `chmod 666`.
- Op de VM **altijd in-place schrijven** (`open(p, "w")`), nooit rename/`os.replace` (single-file bind mounts hangen aan een inode). Verifieer met md5 host vs container.
- **Nooit** state-bestanden met `deploy.ps1` meesturen — productie is de bron.
- `docker cp` alleen voor code, nooit voor statebestanden (root-eigendom → Permission denied-lus).
- `trade_log.json`: veld `quantity`; `pnl_net` is het echte resultaat; sleeve-/oogstregels hebben `thematic_exposure`/`harvest` en moeten in elke lus over trades worden uitgesloten (tel de plekken in de code).

## Development commands

```bash
python scripts/predeploy.py                      # DE poort vóór elke deploy (of --snel)
python -m tests.pre_flight.check_syntax          # alle bestanden, ook scripts/ en research/
python -m pytest tests/ -m "not integration" -q  # zoals CI
python -m tests.pre_flight.check_treasury
python -m utils.nav                              # NAV-totaal (in de container)
python -m utils.kpi                              # KPI's H1–H5 (in de container)
python -m utils.verliesbewaking --oefening       # brandoefening (vlag; volgende monitorronde)
python research/track.py check                   # scorekaart-meting
```

## Deployment

1. `python scripts/predeploy.py` moet groen zijn; bij code die geld raakt eerst **A1-GO**.
2. **Hot-patch** (alleen code, seconden): `gcloud compute scp <abs-pad> agent-trader-swarm-vm:/tmp/<naam> --zone=europe-west1-b`, dan `sudo docker cp /tmp/<naam> agent_trader_swarm:/app/<pad> && sudo docker restart agent_trader_swarm`. Een compose-recreate wist alle hot-patches.
3. **Full deploy** (nieuwe bestanden in de image, config in de image, requirements): vanuit Bash
   `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deploy.ps1 > "$TMP/deploy.log" 2>&1`.
   **Niet** met een PowerShell-omleiding (`2>&1`, `*>`) — gcloud-stderr breekt het script dan af.
4. **Altijd verifiëren:** dashboard 200 (`curl http://localhost:8080/` op de VM, ~30-60s na start), relevante logregels, en NAV (`python -m utils.nav` in de container).

Lezen/schrijven op de VM zonder SCP: `B=$(printf '%s' "$SCRIPT" | base64 -w0); gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command="echo $B | base64 -d | sudo docker exec -i -w /app agent_trader_swarm python3 -"`. Nooit stdin náár `gcloud compute ssh` pipen (plink eet stdin).

## GCP

| Key | Value |
|---|---|
| Project ID | `gen-lang-client-0441524375` |
| Region / Zone | `europe-west1` / `europe-west1-b` |
| VM | `agent-trader-swarm-vm` — **e2-small** (0,5 vCPU, 2 GB, plus 1 GB swap). e2-micro geprobeerd 19–21-09 en teruggedraaid: de voetafdruk (RAM + swap) kwam boven 450 MiB tijdens de ochtendlijke apt-run. Zie PLAN M4 |
| Image URI | `europe-west1-docker.pkg.dev/gen-lang-client-0441524375/agent-trader/swarm:latest` |
| Container | `agent_trader_swarm` (canonieke compose-dir `/home/bartpersoons_gmail_com`) |
| Ports | `8080` (dashboard) |

## Required secrets

Via GCP Secret Manager op de VM, of `.env.adk` lokaal. Optioneel: `GEMINI_MODEL`, `GCP_PROJECT_ID`, `GCP_REGION`.

| Secret | Used by |
|---|---|
| `GOOGLE_API_KEY` | LLMClient (Gemini) |
| `HL_WALLET_ADDRESS` / `HL_PRIVATE_KEY` | HL agent-wallet (tekent orders) |
| `HL_VAULT_ADDRESS` | hoofdwallet `0x92D4…` (`walletAddress` in ccxt) |
| `HL_VAULT_PRIVATE_KEY` | master-key 0x92D4 / treasury-wallet `0x4144e0b5…` (Arbitrum-tx, user-signed HL-acties) |
| `HL_THEMATIC_WALLET_ADDRESS` / `_KEY` | dip-koper-wallet `0xBd6c…` (self-custody) |
| `SUPABASE_URL` / `SUPABASE_KEY` | DatabaseClient, swarm_health |
| `TELEGRAM_CHAT_ID` / `TELEGRAM_BOT_TOKEN` | meldingen |

## Conventies

- Imports: stdlib → third-party → local; optionele deps lazy in `try/except`.
- Agents vangen hun eigen fouten; de main loop crasht nooit. Kritieke afhankelijkheid weg: één keer luid falen, subsysteem uit, niet stil overslaan.
- **Onmeetbaar is nooit nul**: een mislukte uitlezing geeft `None`/een gat en een markering, geen getal. Weiger NaN/inf vóór `json.dump`.
- Logging: `logging.getLogger("Naam")` per klasse.
- Health: `SwarmHealthManager.report_health()` accepteert alleen ACTIVE/IDLE/ERROR/STARTING.
- Sluitende orders: **altijd `reduceOnly`**. Geen 'gedaan'-vlag vóór de order slaagt. HL-minimum $10.
- Windows: `sys.stdout.reconfigure(encoding='utf-8')`; lokaal `PYTHONIOENCODING=utf-8` bij scripts met niet-ASCII-uitvoer.

## Valkuilen die steeds terugkomen

Volledige lijst met achtergrond: **`docs/valkuilen.md`** (algemeen) en **`docs/kasbeheer.md`** (treasury).
- **Guard-dekking:** sleeve/oogst-uitsluiting ontbrak al zes keer ergens. Grep op de data (`thematic_exposure`, `harvest`) door de hele repo.
- **De swarm-client ziet de xyz-perp-dex niet.** Elke xyz-uitlezing via `exchange_client` meet 0 → vals alarm. Gebruik de rauwe info-API met `dex: "xyz"`.
- **Stops bestaan alleen in software** (nul trigger-orders op HL). Beheer controleren via `peak_price`/`last_updated`, niet via logs.
- **Unified account:** nooit ccxt perps + spot optellen; `accountValue` + spot.
- **Valse drawdown:** verplaatst kapitaal moet in álle totalen meetellen (RiskManager, kasbeheer, nav, sleeve_nav).
- **Definitiefouten > rekenfouten:** controleer eerst of een maatstaf de juiste vraag beantwoordt (URTH vs WEBN, notional vs waarde).
- **Bij weinig posities is een backtest padafhankelijk** — log welke posities erin zitten voor je een verschil aan een parameter toeschrijft.
- **Twee actieve sets in kasbeheer:** een nieuwe proposal-status hoort in `execute_approved_proposals()` én `run_fast()`.
- **YIELD_SWITCH beslist op risico-gecorrigeerde APY** (1,5pp); diversificatie > 80% → terug naar 65%.
- **`requirements.txt` exact gepind** houden; ongepind brak CI én deploy.
- **Heredoc-escapes** worden echte newlines in weggeschreven code; gebruik `chr(10)`.

## Hooks (`.claude/hooks/`)

Scripts staan in git; de registratie staat in `.claude/settings.local.json` (lokaal).
`check_python_syntax.py` (Edit/Write) · `verify_dashboard.sh` (Bash, na herstart) ·
`remind_dashboard_update.py` (roadmap.json) · `remind_capture_learnings.py` (na git commit —
schrijft niets zelf; "niets vastleggen" is een geldige uitkomst).

## Proactief

- Na een wijziging in productiecode: `predeploy.py`, bij geld-code A1-review, deploy, verifiëren (dashboard + NAV). Niet vragen "zal ik deployen" als het binnen het plan valt.
- Na een mijlpaal: `/kritisch` (A3) en `docs/PLAN_2026-08.md`-stand + `docs/besluiten.md` bijwerken.
- Een les die een volgende sessie niet uit de code kan halen: memory (werk bestaande bij; geen ruis).
