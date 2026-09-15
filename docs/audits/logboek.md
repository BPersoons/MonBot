# Auditlogboek — controle-agent

Eén regel per review. Bron voor de KPI's van de controle-agent zelf (plan 2026-09-15, §3b):

- **Waarde:** aandeel reviews met ≥1 bevinding die tot een wijziging leidde.
- **Escape rate:** fouten die ná een GO opdoken. Doel bij code die geld raakt: **0**.
- **Doorlooptijd:** doel < 1 uur per poort.
- **Evaluatie bij M5:** drie reviews op rij zonder waarde en zonder escapes → terug naar alleen A1/A2.

| Datum | Poort | Onderwerp | Oordeel | Bevindingen (blok/belangrijk/klein) | Leidde tot wijziging | Doorlooptijd | Escape later? |
|---|---|---|---|---|---|---|---|
| 2026-09-15 | A1 | Mutatietoets — [open posities waarde](2026-09-15-open-posities-waarde.md) (bewust foute code) | STOP | 3 / 3 / 2 | n.v.t. (toets) — beide ingebouwde fouten gevonden → agent telt mee | 3,7 min | — |
| 2026-09-15 | A1 | [Fase 0 + meetfundament](2026-09-15-meetfundament.md) | GO-mits | 0 / 7 / 4 | **Ja** — NaN-guard `nav._koers`, valse KILL na DEPLOY_YIELD-race, transit-statussen + FUND_TRADING, stille nul bij RPC-fout, Morpho-share-price dood (18 decimalen), niet-flow-gecorrigeerde DD-limieten teruggedraaid, HLP-niet-gevonden, kosten na 30 dagen; plus Fluid geparkeerd vóór de M2-deploy | 13,2 min | — |
| 2026-09-15 | A1 r2 | [Meetfundament](2026-09-15-meetfundament.md), open punten | GO-mits | 0 / 3 / 2 | **Ja** — mijn ronde-1-fix introduceerde drie nieuwe gaten (leeggetrokken protocol nooit kill, blind na switch, verlies tijdens transit verdwijnt) → saldi on-chain, basislijn blijft staan tijdens transit, transit alleen voor yield_core-types, kosten bij gat, M5-voorwaarde vastgelegd (`9a6fbce`) | 8,7 min | — |
| 2026-09-15 | A1 | [Kasbeheer-fixes](2026-09-15-kasbeheer-fixes.md) | STOP | 2 / 4 / 2 | **Ja** — revert verdrongen door ankr-JSON-fout; dry-run vóór approve (schijnveiligheid); cap niet in run_fast / HL-excess; rem niet voor switches; cap op stille nullen; gasmarge; aansluiting ongetoetst (`5c636a8`) | 10,0 min | — |
| 2026-09-15 | A1 r2 | [Kasbeheer-fixes](2026-09-15-kasbeheer-fixes.md), open punten | GO-mits | 0 / 1 / 4 | **Ja** — aansluitingstoets rem in `run()`; geen gelijktijdige bewegingen naar yield (cap zag geld onderweg niet); erc4626-volgordetoetsen; dode `_check_treasury_wallet_usdc` weg | 9,2 min | — |
| 2026-09-15 | H4 | Brandoefening in productie (geen review, meting) | — | 6/6 gevonden | detectie **2,77 min** (doel ≤ 10), vlag opgeruimd, echte basislijn intact, Telegram 200 | — | — |
| 2026-09-15 | A2 | [Fluid fUSDC](2026-09-15-fluid-rente.md) | STOP | 4 / 3 / 2 | **Ja** — Fluid op `automated: false`; bestaande kasbeheer-bugs gevonden (diversificatie vanuit Aave neemt HELE saldo op; afronding boven saldo → revert die de dry-run inslikt) | 11,5 min | — |
