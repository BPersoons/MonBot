# Claimblad — de nazorgpoort van M4 meet het verkeerde: swap-volume in plaats van druk

*Datum: 2026-09-20 · Poort: A2 (poort-/kill-criterium: wanneer draaien we de e2-micro terug?) · Mijlpaal: M4 (nazorg)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert

De nazorg van M4 (7 dagen) heeft nu vijf terugdraai-criteria; één ervan is **swapgebruik > 300 MB**. Dat getal loopt op zonder dat er iets misgaat, en het meet niet waar het criterium voor bedoeld was.

**Voorstel:** vervang dat ene criterium door criteria die de schade zelf meten. De andere vier blijven onveranderd.

| nu | voorstel |
|---|---|
| swapgebruik > 300 MB | **swap-in aanhoudend** > 50 kB/s over 5 min (`vmstat` si), **of** swap > 600 MB van de 1024 (dan raakt de ruimte op) |
| geheugendruk some avg60 > 5 | ongewijzigd |
| OOM-kill | ongewijzigd |
| RestartCount > 0 | ongewijzigd |
| dashboard ≠ 200 | ongewijzigd |
| — | **nieuw:** mediane cyclusduur > 90 s, of interval tussen monitorrondes > 7 min |

## Beweringen

| # | Bewering | Bewijs (gemeten 20-09, 24 u na de verkleining) |
|---|---|---|
| S1 | Het swapgebruik loopt op: 91 → 102 → 160 → **242 MB** in 24 uur. | `free -m` bij elke nazorgcontrole. |
| S2 | **Er wordt niets teruggelezen.** `vmstat 2 5` geeft si=1, 2, 0, 0, 0 en so=2, 0, 0, 0, 0 (kB/s). Geparkeerde koude pagina's, geen verkeer. | `vmstat 2 5` op de VM. |
| S3 | De grootste swapgebruikers zijn de swarm zelf (75 MB), dockerd (11 MB), unattended-upgrades (8 MB) en systeemdiensten. Bij `vm.swappiness=10` parkeert de kernel koude pagina's; dat is het doel van swap. | `/proc/*/status` (`VmSwap`). |
| S4 | **Geheugendruk is vrijwel nul:** `some avg10=2,22 avg60=0,52 avg300=0,11`. Het bestaande criterium (avg60 > 5) is niet in de buurt. | `/proc/pressure/memory`. |
| S5 | **De prestaties zijn identiek aan de grote machine.** Cyclusduur 18-09 op e2-small: n=108, mediaan 61,2 s, 19% boven 100 s. Op e2-micro 19-09: n=107, mediaan 61,0 s, 20% boven 100 s. Het patroon "elke vijfde cyclus ~121 s" bestond dus al vóór de verkleining. | Cloud Logging, logger `Heartbeat`, twee vensters van 4 uur. |
| S6 | **De monitor loopt op tijd:** rondes om 08:29:15, 08:34:17, 08:39:19, 08:44:21, 08:49:24, 08:54:26 — steeds 5 min 2 s. | `docker logs`, "running check". |
| S7 | Verder alles groen: 0 herstarts, 0 OOM-kills, dashboard 200, container-dagpiek 359,8 MiB (19-09) en 258,5 MiB (20-09) tegen een grens van 450, VM-piek 666 MB en 463 MB tegen 700. | Nazorgmetingen 19-09 18:42 UTC en 20-09 08:53 UTC. |
| S8 | Swapgebruik is een **voorraadmaat**: hij zegt hoeveel er ooit is uitgeplaatst, niet of het systeem nu tekortkomt. De auditor van 17-09 wees hier al op ("swap op pd-standard is traag en helpt alleen voor koude pagina's — voeg een drukmaat toe"); de drukmaat is toen toegevoegd, maar de voorraadmaat bleef ernaast staan. | `docs/audits/2026-09-17-m4-kosten-herzien.md`, bevinding 6. |

## Raakt deze KPI's / poorten

- **M4-nazorg:** het terugdraai-besluit. Met het huidige criterium volgt binnen ~1 dag een terugdraaiing naar e2-small op een getal dat geen schade aantoont; dat kost $81/jaar aan besparing.
- **H4:** de nieuwe criteria (cyclusduur, monitorinterval) meten juist wél of de bewaking nog op tijd is.

## Risico en terugdraaien

- **Risico van het voorstel:** als swap tóch een vroege waarschuwing zou zijn die de andere maten missen, verliezen we die. Daarom blijft er een grens staan, maar op 600 MB (bijna 60% van de ruimte), en komt er een directe maat bij (si) plus twee uitkomstmaten (cyclus, monitorinterval).
- **Terugdraaien blijft simpel:** `stop` → `set-machine-type e2-small` → `start`, ~5 minuten, en de snapshot `voor-e2-micro-20260919` staat tot 26-09.
- **Geen geld in beweging.** Dit gaat alleen over de vraag wanneer de VM terug moet.

## Wat ik zelf niet heb gecontroleerd

- **Wat er gebeurt als swap écht vol raakt.** Ik meet nu 242 van 1024 MB; het gedrag bij 900 MB is niet getest, alleen beredeneerd.
- **Of de 121-seconden-cycli ergens anders pijn doen.** Ze bestonden al op e2-small en vallen binnen de cyclus van 60 s sleep + werk, maar ik heb niet uitgezocht wélke stap die minuut kost.
- **De trend voorbij 24 uur.** Het kan zijn dat swap stabiliseert rond ~250 MB; dat weet ik pas over een paar dagen.

---

## Audit
*(in te vullen door de controle-agent)*

## Reactie bouwer
*(per open punt: opgelost in `<hash>` of weerlegd met bewijs)*
