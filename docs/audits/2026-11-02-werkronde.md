# Claimblad — werkronde 02-11: eindoordeel e2-micro, terugdraaien, twee meetfixes

*Datum: 2026-11-02 · Poort: A2 poortbesluit (M4) + A1 deploy meetcode + A4 wekelijks · Mijlpaal: M4*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
1. **Poortbesluit M4 (A2):** eindoordeel e2-micro poging 2 = **GERAAKT** → terug naar e2-small, geen derde poging (vooraf vastgelegd: `besluiten.md` r73, claimblad `2026-10-06-e2micro.md`, `experimenten.json` › `e2_micro_poging_2`). Daarna de snapshot `voor-e2-micro-20261019` opruimen ("bewaren tot >= 02-11").
2. **Fix A — vals alarm dip-koper (A1):** `utils/verliesbewaking.py` › `_lees_dip_koper` leest het positiebestand bij een onleesbare eerste lezing één keer opnieuw na `HERLEES_PAUZE_S` = 2 s. Pas als het dan nog kapot is: `onleesbaar=True` → alarm.
3. **Fix B — potjesreeks niet wissen (A1, PLAN punt 6, gevonden in A1 12-10):** `utils/sleeve_nav.py` › `_load_state` geeft bij een bestaand maar onleesbaar of ongeldig `data/sleeve_nav.json` `None`; `snapshot_if_new_day` schrijft dan niets. Alleen een ontbrekend bestand begint een lege reeks.
4. `config/agenda.json`: regel 27-10 ("eindoordeel kleine server") weg.
- Toetsen: `tests/test_verliesbewaking.py` (+2, 2 aangepast met `pauze_s=0` / `HERLEES_PAUZE_S=0`), `tests/test_onleesbaar_en_reduce_only.py` (+2).
- Productie-impact: VM ~5 min stil (kasbeheer, dip-koper-softwarestops, vasthouden, monitor). Geen geld beweegt. Daarna een full deploy (agenda zit in de image) op de e2-small: container-recreate, statebestanden gemount.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | De poort is geraakt op criterium b: 8 intervallen > 1% PSI-stall in het venster 19-10 20:07:30 → 26-10 20:07:30, hoogste 4,53% (25-10 10:00). Alle andere scriptcriteria gehaald: 672 metingen, 0 exec, piek `ctr_werkelijk` 332 MiB | `python3 e2micro_poort.py --vanaf 2026-10-19T20:07:30Z --tot 2026-10-26T20:07:30Z < ~/mem_history.log` op de VM (02-11 ~10:17 UTC), exit 1 |
| 2 | Ook na het venster raakt b nog 7× (t/m 02-11 05:00, max 2,86%). Het is dus geen eenmalige uitschieter | zelfde script zonder `--tot` |
| 3 | g en h zijn gehaald: 1 boot sinds 19-10 20:06, 0 OOM in de kernellog (boot 0), `RestartCount`=0, `OOMKilled`=false, 0× CYCLE_FROZEN in `docker logs`, dashboard 200 | `journalctl --list-boots`, `journalctl -k -b 0 \| grep -c oom`, `docker inspect`, `docker logs \| grep -c CYCLE_FROZEN`, `curl` |
| 4 | Er is niets onderweg in kasbeheer: geen proposal in een actieve status, `pending_count` 0 | `treasury_state.json`: statussen DEPLOYED 10, COMPLETED 6, FAILED 3, REJECTED 2 |
| 5 | Het alarm `dip_koper_onleesbaar` van 23-10 23:15:43 was vals: de dip-koper schreef zijn bestand in-place op dat moment; de log toont om 23:15:44 een normale ronde met 6 open posities. Eén keer in 14 dagen log | `docker logs --since 2026-10-23T23:00 --until 23:40`; `grep -c onleesbaar` = 2 (de andere is een RPC-saldo van kasbeheer) |
| 6 | Fix A houdt de echte detectie intact: kapot bij de herlezing = alarm, precies één herlezing (geen lus), ontbrekend bestand = geen alarm. De ronde wordt hooguit 2 s langer, alleen als de eerste lezing faalt | `test_lees_dip_koper_blijft_kapot_is_alarm_na_een_herlezing`, `..._herleest_na_een_halve_schrijfactie`, bestaande toetsen |
| 7 | Fix B: bij een onleesbaar/ongeldig bestand blijft het byte-voor-byte staan; bij een ontbrekend bestand komt er een snapshot. De verliesbewaking meldt daarna "geen NAV-snapshot" (bestaande check, `max_leeftijd`) en de KPI faalt luid (`kpi._lees` vangt geen JSONDecodeError) | `test_sleeve_nav_overschrijft_een_onleesbare_reeks_niet` (5 vormen), `test_sleeve_nav_begint_een_reeks_als_het_bestand_ontbreekt` |
| 8 | Elke fix heeft een toets die rood wordt als je hem terugdraait: 5 mutanten (geen herlezing; pauze 0; onleesbaar → lege reeks; ongeldige vorm → lege reeks; `state is None`-guard weg), elk 1 rood | mutatierun 02-11 lokaal |
| 9 | `_load_state` heeft maar één aanroeper (`snapshot_if_new_day`) | `grep -n "_load_state" utils/sleeve_nav.py` |

## KPI-stand (A4, `data/kpi.json` 02-11 00:02)
| KPI | Waarde | Doel | Gehaald |
|---|---|---|---|
| H1 netto (77 d, voorlopig) | −$24,83 (opbrengst $10,99, kosten $35,82) | > $0 | nee |
| H2 verschil vs Aave | −0,33pp (2,63% vs 2,95%) | ≥ +2pp | nee (was −0,66 half sep) |
| H3 experimentverlies | $0 | < $250 | ja |
| H4 detectie | 2,77 min, alles gevonden | ≤ 10 min | ja |
| H5 gaten | 0 | 0 | ja |

Verliesbewaking: `laatste_ronde` 02-11 10:13 (5 min oud), `onmeetbaar` leeg, experimentverlies $0. NAV $5.380.

## Raakt deze KPI's / poorten
- M4 (kosten): niet gehaald, geen derde poging. H1: e2-small kost $0,503/dag i.p.v. $0,282 → H1 blijft structureel negatief op deze omvang (`PLAN` r76).
- H4/H5: fix A haalt een vals alarm weg, fix B voorkomt verlies van de reeks onder H1/H3.

## Risico en terugdraaien
- Terugdraaien VM: `gcloud compute instances stop` → `set-machine-type --machine-type=e2-small` → `start` (21-09 ~5 min). Komt hij niet op: serial-port-output, dan herstel uit snapshot `voor-e2-micro-20261019` — daarom die snapshot pas na verificatie weg. De waakhond kan tijdens de stop een afwezigheidsmelding sturen; die verwacht ik en ik noteer hem.
- Op het spel: dip-koper ~$254 (beursstops −30% bij HL blijven staan), HYPE-basis $115 (aan HL), kasbeheer staat in protocollen.
- Fixes terugdraaien: `git revert` + deploy.

## Wat ik zelf niet heb gecontroleerd
- De beursstops (6 stuks?) heb ik vóór de stop nog niet opnieuw geteld; dat doe ik als nulmeting vlak voor `stop`.
- Of de waakhond tijdens de nazorg iets gemeld heeft: geen bericht van Bart, maar ik zie Telegram niet.
- Hetzelfde patroon (onleesbaar → `{}` → wegschrijven) zit in `verliesbewaking.run_check` voor zijn eigen `data/verliesbewaking_state.json` (r497 → r525): een kapotte state zou `rendement_reeks` en `share_prices` wissen. Bewust buiten deze ronde (ontwerpkeuze: dan stopt de bewaking, of hij draait door zonder te schrijven); komt in PLAN punt 6.

---

## Audit
**r1 (2026-11-02): A2 GO (terug naar e2-small, geen derde poging) · A1 fix A GO · A1 fix B GO · A4 GO.** Poortscript zelf opnieuw gedraaid (git-versie, ongewijzigd sinds 8323b7c): 672 metingen, 8× PSI > 1%, max 4,53%, exit 1; daarna nog 7×. 1 boot, 0 OOM, RestartCount 0, CYCLE_FROZEN 0 (log compleet vanaf 19-10 19:51); 8× `virtio_balloon Out of puff` 28-10..02-11. Volledige suite 616 groen; 8 eigen mutanten rood, één onschuldig groen (drie lezingen met één pauze). KPI's narekend (H1 13,28 + 0,43 − 2,72 = 10,99; kosten 63 × 0,503 + 14 × 0,282).

Bevindingen:
1. [belangrijk] `voor-e2-micro-20261019` is de **enige** reservekopie van de schijf (geen snapshotschema). Voorwaarde: vervangen, niet verwijderen — eerst een verse snapshot (of een wekelijks schema), dan pas de oude weg.
2. [belangrijk] Terugdraaiplan mist "geen capaciteit" (ZONE_RESOURCE_POOL_EXHAUSTED). Voorwaarde: weigert `start` op e2-small, dan direct terug naar e2-micro en starten; later opnieuw.
3. [belangrijk] Nulmeting (kasbeheer actieve sets, 6 beursstops; om ~10:30 in orde) vlak vóór `stop` herhalen.
4. [klein] Bewering 7 deels onjuist: `update_kpi` draait alleen na een gemaakte snapshot (`main.py:624`), dus de KPI faalt niet luid maar blijft staan; de melding komt van de verliesbewaking ("geen NAV-snapshot"). Bij `{"history": "x"}` of `[1]` valt de hele bewakingsronde uit op r301 (bestond al, onwaarschijnlijk) → PLAN punt 6.
5. [klein] Zelfde half-geschreven-risico: de verliesbewaking leest `data/sleeve_nav.json` in de monitor-thread terwijl de hoofdthread schrijft (1×/dag, ms) — verwaarloosbaar, wel dezelfde fout op een tweede plek.
6. [klein] Agenda-regel 27-10 nog niet weg; wijziging `experimenten.json` (optiepremie gestopt) staat niet op het claimblad.

Pre-mortem: ook de e2-small zat al op 0,86–0,98% PSI en kent de ballon; de grote kostenhefboom is het VM-besluit na twee gemiste kwartalen (12-10), niet nog een kleinere machine.

## Reactie bouwer
1. Uitgevoerd: verse snapshot na de terugschakeling + wekelijks schema (2 bewaard); de oude pas daarna weg.
2. Opgenomen in de uitvoering.
3. Herhaald vlak vóór `stop` (zie uitvoering).
4. Bewering 7 gecorrigeerd zoals de auditor schrijft; r301-vormen en het `run_check`-patroon in PLAN punt 6.
5. In PLAN punt 6 bij hetzelfde punt.
6. Agenda-regel weg. `optiepremie_crypto` → gestopt (idee op trede 0, geen geld): papierstap 1 en 4 gedaan op Deribit-data (premie BTC 2026 +3,1 vol-pt, ETH 2025 −3,4; spread 0,7–0,8 vol-pt; kleinste contract 0,1 BTC / 1 ETH tegen ~$230 vrij risicodeel), met heropen-voorwaarde. Geen geldcode.
