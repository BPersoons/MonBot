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
| 2026-09-15 | A2 | [Fluid fUSDC](2026-09-15-fluid-rente.md) | STOP | 4 / 3 / 2 | **Ja** — Fluid op `automated: false`; bestaande kasbeheer-bugs gevonden (diversificatie vanuit Aave neemt HELE saldo op; afronding boven saldo → revert die de dry-run inslikt) | 11,5 min | — |
