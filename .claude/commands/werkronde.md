# Werkronde — vaste volgorde voor autonoom doorwerken

Eén ronde langs doelen, KPI's, alarmen en poorten. Zo is autonoom doorwerken herhaalbaar en
controleerbaar (plan 2026-09-15, S5). **Voert alleen uit wat binnen het plan en de kaders valt;
alles daarbuiten wordt een vraag aan Bart.**

## Arguments
`$ARGUMENTS` — optioneel: `kort` (stap 1–4, geen audit), default = volledig.

---

## Stap 1 — Is productie gezond?
```bash
gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker ps --format "{{.Names}} {{.Status}}"; sudo docker inspect -f "restarts={{.RestartCount}}" agent_trader_swarm; curl -s -o /dev/null -w "dashboard=%{http_code}\n" http://localhost:8080/; free -m | head -2; sudo docker stats --no-stream --format "{{.MemUsage}}" agent_trader_swarm'
```
Dashboard ≠ 200 of een onverwachte herstart → eerst dat oplossen (`/logs`), de rest wacht.

## Stap 2 — KPI's lezen
Laatste regel uit `data/kpi.json` (via `docker exec ... python3 -c`). Per doel: waarde, doelwaarde, gehaald?

| KPI | Doel |
|---|---|
| H1 netto 90d | > $0 |
| H2 verschil vs Aave | ≥ +2pp |
| H3 experimentverlies | < $250 (alarm $125) |
| H4 detectietijd | ≤ 10 min, alles gevonden |
| H5 gaten / onmeetbaar | 0 |

**Onmeetbaar is niet gehaald.** Een KPI zonder waarde is een bevinding, geen "nog even afwachten".

## Stap 3 — Wat heeft de verliesbewaking gemeld?
`data/verliesbewaking_state.json`: `gemeld` sinds de vorige ronde, `experimentverlies_usd`, `onmeetbaar`-tellers, `laatste_ronde` (ouder dan 15 min → Check 24 draait niet).

Een kill of een budgetalarm gaat vóór alles: uitvoeren wat het register zegt en Bart melden.

## Stap 4 — Welke poorten zijn aan de beurt?
- Mijlpalen in `docs/PLAN_2026-08.md` § "Plan 2026-09-15".
- Poortdatums en -drempels in `config/experimenten.json`.
- Herzien-wanneer in `docs/besluiten.md`.

Per poort: meet het criterium uit de bron, noteer de uitkomst. **Nooit oprekken.** Haalt hij het niet, dan geldt de kill of de afgesproken terugval.

## Stap 4b — De motor: beweegt er genoeg? (`docs/MOTOR.md`)
`python -m utils.motor` toont wat op welke trede staat (idee → papier → schaduw → proeftuin → schalen) en meldt stilstand: een idee dat langer dan een week niet verschoof, een lege trede 0 of 1, of meer dan drie experimenten op de proeftuin.

- Elke week gaat **minstens één idee een trede verder, of het stopt** (met reden in `docs/besluiten.md`).
- Werk `trede`, `sinds` en `volgende_stap` bij in `config/experimenten.json` zodra er iets verschuift.
- Een nieuw idee (een tweak of een nieuwe opbrengstbron) komt op trede 0, **zonder potje**.

## Stap 5 — Tegenspraak (A4, wekelijks; A2 bij elk poortbesluit)
Schrijf een claimblad (`docs/audits/_sjabloon.md`) met de KPI-stand en de voorgenomen acties. Laat de controle-agent reviewen (`.claude/agents/auditor.md`). Bij A2: geen kapitaalbeweging zonder GO. Noteer de review in `docs/audits/logboek.md`.

## Stap 6 — Handelen en vastleggen
- Werk binnen het plan: bouwen → toetsen → `python scripts/predeploy.py` → (A1-GO bij code die geld raakt) → deploy → verifiëren.
- Elk besluit: een regel in `docs/besluiten.md`.
- Een les die een volgende sessie niet uit de code kan halen: memory.

## Stap 7 — Melden aan Bart
**Alleen** bij: een mijlpaal gehaald of gemist · een poort genomen · een kill uitgevoerd · budget ≥ $125 · een KPI onbetrouwbaar · iets dat zijn toestemming vraagt (nieuw kapitaal, geld uit DeGiro of de Ethereum-wallet, nieuwe venue, hefboom > 2x, drempel verruimen).

Kort: conclusie en aanbeveling. De onderbouwing staat in commit en audit.

---

## Hoe je dit verkeerd doet
- Een statusupdate sturen zonder dat er iets te besluiten is.
- Een poort "bijna gehaald" noemen en doorgaan.
- Een KPI die niet te meten was overslaan in plaats van hem als bevinding te melden.
- Geld verplaatsen omdat de ronde "af moet".
