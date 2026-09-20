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

*Controle-agent, 2026-09-20 (overgenomen door de bouwer; alleen leestools).*

**Oordeel: GO-mits.** De maat mag worden gecorrigeerd, maar niet zoals voorgesteld. Het niveau van 600 MB wordt geweigerd, de twee nieuwe uitkomstmaten kunnen aantoonbaar nooit rood worden, en geen van de nieuwe criteria wordt door iets of iemand gemeten.

**1. [blokkerend] Swapvolume is op deze machine juist de enige nazorgmaat die omhoog gaat als het slechter wordt.** `docker stats` en `free -m` tellen uitgeplaatste pagina's niet mee. Gemeten: container `memory.current` 261 MiB **plus** `memory.swap.current` 141,5 MiB — die 141,5 MiB zit in geen enkel nazorgcijfer. In de data:

| dag | container min/gem/max (MiB) | VM gem/max (MB) | swap |
|---|---|---|---|
| 18-09 (e2-small) | 230,6 / 279,5 / 329,6 | 550 / 648 | 0 |
| 19-09 (e2-micro) | 200,5 / 270,8 / 359,8 | 481 / 666 | 91 → 160 MB |
| 20-09 tot 08:45 | 203,5 / 240,8 / 258,5 | 419 / 463 | 242 MB |

De daling van 359,8 naar 258,5 MiB is geen verbetering maar het swapsignaal zelf. Een langzaam lek is daardoor voor alle vier overgebleven criteria onzichtbaar. Dat scenario bestaat hier aantoonbaar: het container-dagminimum steeg van 281,8 MiB (26-08) naar 331,6 MiB (14-09), dus **+2,6 MiB/dag over 19 dagen**; sinds de pijplijn uit staat is het vlak.

**2. [belangrijk] De definitiefout zit elders.** `free` telt **swapcache** mee: pagina's die in RAM én swap staan en gratis terug te lezen zijn. Gemeten: Swap used 247 MB, som van alle `VmSwap` 147 MiB, `SwapCached` 103 MiB (147 + 103 ≈ 247). Van de 247 MB is 103 MiB dus geen tekort. Corrigeer de grootheid (`Swap used − SwapCached`), niet het niveau: 600 MB rauw is een verdubbeling, geen correctie.

**3. [belangrijk] Het nieuwe niveau wordt binnen dit nazorgvenster geraakt.** 160 MB (19-09 18:42) → 242 (20-09 08:57) → 247 (09:20) = 5,9 MB/u. Lineair: 300 MB vanavond ~18:20 UTC, 600 MB op 22-09, vol op ~25-09. Een grens verhogen op een trend die de bouwer zelf niet heeft gemeten, 9–18 uur voordat de oude grens raakt, is oprekken.

**4. [belangrijk] De twee nieuwe criteria kunnen niet rood worden.** Cyclusduur over vier vensters (n=106–107): p50 61,0–61,1 s, p90 121,4–121,6 s, minimum overal 60,4 s — er zit een vaste `sleep(60)` in. De mediaan boven 90 s krijgen vraagt een factor 30 in het variabele werk; de verkleining verschoof de mediaan met −0,1 s. Monitorinterval over 24 u (n=284): min 302, p50 302, p90 304, max 305 s, tegen een grens van 420. **Gebruik p90-cyclus > 150 s en p90-monitorinterval > 330 s, of laat ze weg.**

**5. [belangrijk] Niemand meet de nieuwe criteria.** `mem_sample.sh` logt alleen `docker stats` en `free` "used" — geen swap, geen swapcache, geen PSI, geen si. De monitor kijkt nergens naar VM-geheugen (0 treffers op `swap|pressure/memory|meminfo`). De waakhond vuurt pas bij stilte > 15 min. Ook `avg60` is de verkeerde grootheid om elk kwartier af te lezen; gebruik de cumulatieve `total=`-teller (gemeten stall-rate 0,093% sinds boot).

**6. [belangrijk] De criterialijst in het claimblad is niet de vastgelegde lijst** (`PLAN:52` plus het blad van 17-09): container-dagpiek < 450 MiB, VM-piek < 700 MB, CYCLE_FROZEN en "monitorcheck faalt door traagheid" ontbreken, en bij de 300 MB is "langer dan een uur" weggelaten.

**7. [belangrijk] `memory.peak` staat op 428,6 MiB — 95% van de poort** (host-side gelezen). De M4-poort meet `memory.peak`, het nazorgcriterium meet de dagpiek uit `docker stats`: twee verschillende getallen onder dezelfde grens.

**8. [klein] S2 klopt van conclusie, niet van bewijs.** Vijf samples over 10 s tonen niets aan; de cumulatieve tellers wel: sinds boot 408 MB uitgeplaatst en 207 MB teruggelezen, in bursts. Over 10 aaneengesloten minuten: pswpin +60 kB, pswpout 0 — de conclusie klopt dus, met dit bewijs. Let op: een SSH-sessie veroorzaakte zelf si-pieken van 12–44 kB/s, dus de grens van 50 kB/s is ruisgevoelig. S8 citeert de auditor van 17-09 bovendien verkeerd: die vroeg juist om **meer** zorg om swap (traag medium), met `vmstat si` als toegestane maat.

**9. [klein] Het meetapparaat staat niet in git.** `mem_sample.sh` en de cronregel bestaan alleen op de VM, buiten `STATE_FILES` en buiten de backup-lus — precies wat `docs/statebestanden.md` verbiedt.

**10. [klein] Het terugvalpad verloopt precies wanneer het besluit valt.** De snapshot staat tot 26-09; de nazorg loopt tot 26-09 en de nieuwe grens zou op 22–25-09 raken.

**Pre-mortem:** (1) de eerstvolgende full deploy — 1,35 GB image op 958 MB RAM met 247 MB in swap, en `deploy_update.sh` wacht maar 90 s op het dashboard zonder te falen; (2) de maandelijkse apt-piek — op e2-small 1084 MB (07-09) en 885 MB (11-09), die passen niet in 958 MB en moeten volledig uit swap komen; kans binnen het venster ~1 op 3; (3) een subsysteem dat weer aangaat en het lek van +2,6 MiB/dag terugbrengt. **In alle drie is een swap-maat de vroegste, en in geen van de drie helpen cyclusduur of monitorinterval.**

**Gemiste kansen:** ~66 MB vrij te maken door `multipathd`, `snapd`, `packagekitd`, `polkitd` en `networkd-dispatcher`; zram in plaats van een swapfile op pd-standard; 1,355 GB aan ongebruikte images; en de nazorgmetingen in de waakhond zetten in plaats van in een sessie.

**Voorwaarden voor GO:** (1) grens op `Swap used − SwapCached` > 200 MiB of `SwapFree` < 400 MB, 600 MB geweigerd; (2) trendcriterium: geparkeerd volume groeit > 50 MiB/dag over 3 dagen; (3) `mem_sample.sh` logt swap, swapcache, container-swap, pswpin/out en PSI-total, en staat in git; (4) p90-maten in plaats van mediaan en 7 minuten; (5) criterialijst gelijktrekken met `PLAN:52`; (6) vastleggen welk getal de dagpiek is en dat swap wordt meegeteld; (7) vastleggen dat een geraakt criterium terugdraaien betekent — geen derde herziening — en de snapshot bewaren tot ≥ 7 dagen na de nazorg.

## Reactie bouwer

*2026-09-20, alles uitgevoerd vóór de oude grens van 300 MB geraakt wordt.*

| # | Status | Wat |
|---|---|---|
| 1 | **overgenomen, en scherper** | Het nazorgcriterium meet voortaan de **werkelijke voetafdruk**: `memory.current + memory.swap.current` van de container. Dat cijfer stijgt juist als swap zich vult. Stand nu: 263 + 138 = **401 MB** van de 450. |
| 2 | **overgenomen** | Grens op geparkeerd volume (`Swap used − SwapCached`) > 200 MiB, plus `SwapFree` < 400 MB. De 600 MB is geschrapt. Stand nu: geparkeerd **138 MB**, vrij **793 MB**. |
| 3 | **overgenomen** | Geen niveauverhoging op een ongemeten trend. De meter legt de trend nu elke 15 minuten vast; het trendcriterium (> 50 MiB/dag over 3 dagen) is toegevoegd. |
| 4 | **overgenomen** | p90-cyclusduur > 150 s en p90-monitorinterval > 330 s. De mediaan en de 7 minuten zijn geschrapt. |
| 5 | **opgelost** | `scripts/vm/mem_sample.sh` logt nu swap_used, swap_cached, swap_parked, swap_free, ctr_mem, ctr_swap, ctr_peak, pswpin/pswpout en de PSI-`total`-tellers — en staat in git. Geïnstalleerd en gedraaid op de VM. |
| 6 | **opgelost** | De criterialijst in PLAN M4 is compleet gemaakt: voetafdruk, VM-piek, swap (3 maten), PSI-total, OOM, RestartCount, dashboard, CYCLE_FROZEN, p90-cyclus en p90-monitorinterval. |
| 7 | **opgelost** | De nazorg meet dezelfde grootheid als de poort (`memory.peak`) **plus** swap; het onderscheid staat in PLAN M4. |
| 8 | **erkend** | Het bewijs voor "geen verkeer" is vervangen door de cumulatieve tellers; die staan nu elke 15 minuten in de log. De si-grens van 50 kB/s is geschrapt (te ruisgevoelig). |
| 9 | **opgelost** | Script in `scripts/vm/`, de cronregel staat in het PLAN. |
| 10 | **opgelost** | De snapshot blijft tot ≥ 03-10 staan; verwijderen is uit de dagelijkse nazorgtaak gehaald. |

**Gemiste kansen uitgevoerd:** `multipathd`, `packagekit` en `networkd-dispatcher` uitgezet (~39 MB; geheugen 463 → 437 MB, swap 243 → 230 MB). `snapd` blijft, want `google-cloud-cli` op de VM hangt eraan. De ongebruikte images n8n en caddy zijn verwijderd. zram blijft genoteerd.

**Antwoord op de open vragen:**
- **De swaptrend** wordt vanaf nu elke 15 minuten vastgelegd op geparkeerd volume; ik beoordeel hem over 3 dagen.
- **De eerstvolgende full deploy** wordt binnen de nazorgweek vermeden tenzij nodig; gebeurt het toch, dan eerst `docker pull` los, daarna pas recreate, met het geheugen erbij gemeten.
- **Het gat tussen boot (07:21) en containerstart (08:44)** is geen raadsel: de container startte bij de boot en is om 08:44 door mijn eigen deploy opnieuw aangemaakt. Dat verklaart ook de 408 MB uitgeplaatst sinds boot.
- **Poort versus nazorg** was drift, nu rechtgetrokken (zie 7).
