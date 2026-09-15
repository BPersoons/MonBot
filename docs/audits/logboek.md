# Auditlogboek — controle-agent

Eén regel per review. Bron voor de KPI's van de controle-agent zelf (plan 2026-09-15, §3b):

- **Waarde:** aandeel reviews met ≥1 bevinding die tot een wijziging leidde.
- **Escape rate:** fouten die ná een GO opdoken. Doel bij code die geld raakt: **0**.
- **Doorlooptijd:** doel < 1 uur per poort.
- **Evaluatie bij M5:** drie reviews op rij zonder waarde en zonder escapes → terug naar alleen A1/A2.

| Datum | Poort | Onderwerp | Oordeel | Bevindingen (blok/belangrijk/klein) | Leidde tot wijziging | Doorlooptijd | Escape later? |
|---|---|---|---|---|---|---|---|
| 2026-09-15 | A1 | Mutatietoets — [open posities waarde](2026-09-15-open-posities-waarde.md) (bewust foute code) | STOP | 3 / 3 / 2 | n.v.t. (toets) — beide ingebouwde fouten gevonden → agent telt mee | 3,7 min | — |
