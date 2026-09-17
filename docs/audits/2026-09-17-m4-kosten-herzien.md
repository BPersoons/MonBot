# Claimblad — M4 herzien: kosten opnieuw gemeten, verkleinen ter plekke in plaats van verhuizen

*Datum: 2026-09-17 · Poort: A2 (poortbesluit M4 + infrawijziging onder draaiend geld) en A1-achtig voor meetcode van H1 · Mijlpaal: M4*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert

**1. Correctie op commit `e4d82e8`.** Die commit stelde twee dingen:
- de VM kost $0,60 per dag;
- alleen de gratis e2-micro in de VS haalt M4, dus M4 wordt een verhuizing.

Beide beweringen worden ingetrokken:
- **Kosten:** de listprijzen zijn zonder staffels gelezen. De schijf en het IP-adres hebben een gratis staffel. Registry, secrets en verkeer ontbraken.
- **Verhuizing:** Hyperliquid sluit de VS uit. Zie B1.

**2. Meetcode voor H1.** Gewijzigd: `utils/cost_tracker.py`. Nieuwe toets: `tests/test_infra_kosten.py`.
- De infrakosten volgen nu het machinetype dat de metadataserver opgeeft. Daarbij komen vaste bijkosten van $0,083/dag.
- Bij een onleesbaar of onbekend machinetype wordt de duurste bekende prijs gerekend.
- De env-var `INFRA_COST_USD_DAILY` gaat voor. Een ongeldige waarde (NaN, inf, negatief of tekst) wordt genegeerd.
- `cost_log.json` krijgt het veld `machine_type`.

**3. M4 uitvoeren ter plekke, in europe-west1.** De stappen staan in de procedure verderop.
- Swap van 1 GB.
- stop → `set-machine-type e2-micro` → toegangsconfig naar **Standard Tier** → start.
- **Na 20:00 UTC** (Amerikaanse beurs dicht) en pas als de full deploy van 18:17 UTC geverifieerd is.

**4. Secrets opruimen (onomkeerbaar).**
- Vernietigen: 6 vervangen secretversies (niet-`latest`).
- Verwijderen: de twee n8n-secrets, samen 4 versies.

**5. Documentatie en scripts.**
- `docs/PLAN_2026-08.md` (M4);
- de GCP-tabel in `CLAUDE.md`;
- `deploy.ps1`: `$MACHINE_TYPE` stond nog op `e2-medium` en wordt alleen gebruikt bij het aanmaken van een VM.

**Productie-impact.**
- Stap 2 wijzigt alleen de kostenteller: `cost_log.json`, en via `kpi.json` ook H1. Er gaat geen geld om.
- Stap 3 geeft 3–5 minuten stilstand van de hele swarm. In die tijd:
  - zijn er geen software-stops voor de dip-koper;
  - draait er geen monitor;
  - handelt kasbeheer niets af.
- Stap 3 geeft daarna 1 GB RAM in plaats van 2 GB, 0,25 vCPU blijvend in plaats van 0,5, en een nieuw publiek IP-adres.

## Beweringen

| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| B1 | Een VM in de VS is voor ons geen optie. Hyperliquid sluit de VS uit in zijn voorwaarden (§1.5). Volgens tenminste één API-client blokkeert Hyperliquid ook verbindingen vanuit zo'n regio. | Tealstreet-docs (docs.tealstreet.io/docs/connect/hyperliquid): *"You will not be able to connect to Hyperliquid if you are connecting from a geo-restricted region"*, met de VS als voorbeeld. Tegengeluid: hyperliquidguide.com zegt dat alleen de frontend op IP controleert. Ook dan blijft het een schending van de voorwaarden. Op HL staat het swarm-potje, de dip-koper (xyz) en de kern-crypto. |
| B2 | De prijscatalogus rekent staffels per SKU. **Schijf:** SKU `D973-5D65-BAB2` "Storage PD Capacity" geldt voor us-central1, us-east1, us-west1, asia-east1 **en europe-west1**, met 0–30 GB/maand gratis en daarna $0,04. **Extern IP:** SKU `C054-7F72-A02E` "External IP Charge on a Standard VM" (global) heeft 0–720 u/maand gratis en daarna $0,005/u. | Cloud Billing Catalog API, `services/6F81-5844-456A/skus`. Script: `prijzen.py`/`prijzen2.py` in de scratchpad; nabouwen met `gcloud auth print-access-token` + de REST-aanroep. |
| B3 | **Rekenkracht:** e2-small = 0,5 × 0,02399337 + 2 × 0,00321609 = $0,01843/u = **$0,442/dag**. e2-micro = 0,25 × 0,02399337 + 1 × 0,00321609 = $0,00921/u = **$0,221/dag**. | Zelfde catalogus: "E2 Instance Core running in EMEA" (`9FE0-8F60-A9F0`, alleen europe-west1) en "E2 Instance Ram running in EMEA". |
| B4 | **Bijkosten per dag (conservatief):** schijf 0,039, IP 0,004, registry 0,008, secrets 0,012 na opruimen (0,032 ervoor), uitgaand verkeer 0,020. Totaal **$0,083** na opruimen. | **Schijf:** 30 GB pd-standard (`gcloud compute disks list`). Telt mee tot de factuur de staffel bevestigt. **IP:** 24 u × $0,005 in maanden van 31 dagen. **Registry:** `repositories describe` = 2.924,7 MB; SKU "Artifact Registry Storage" 0,5 GB gratis, dan $0,10/GB-mnd. **Secrets:** 22 actieve versies, na opruimen 12; SKU "Secret version replica storage" 6 gratis, dan $0,06/mnd. **Verkeer:** zie B6. |
| B5 | **Totaal per dag.** Nu (e2-small, vóór opruimen) ~$0,51–0,55; de teller rekende $0,44. Na M4 met opruimen en Standard Tier: **$0,245** als de schijf en het verkeer echt gratis zijn, **$0,304** conservatief. | Optelling van B3 en B4. De kostenteller rekent na M4 **$0,304**, met opzet de bovengrens. |
| B6 | **Uitgaand verkeer:** ~0,15–0,2 GB/dag sinds de pijplijn uit staat (15-09), daarvoor 0,33–0,37 GB/dag. **Prijs:** Premium $0,12/GB. Standard Tier geeft 200 GB/maand gratis per regio. | Cloud Monitoring `instance/network/sent_bytes_count`, per dag over 7 dagen: 16-09 156 MB, 15-09 328 MB, 11–14/09 324–368 MB. Meting op de VM (`ens4` tx_bytes, 17-09 09:08–09:38 UTC): **2,31 MB in 30 min ≈ 110 MB/dag ≈ $0,013/dag** op Premium; de teller rekent voorzichtig $0,020. Standard Tier: Google Cloud-blog "Announcing 200 GB free Standard Tier internet data transfer per month" en network-tiers-docs: *"Standard Tier is available … in all regions"* en *"If you change the tier of an instance with an ephemeral IP address, the IP address of the instance changes as well."* |
| B7 | Een e2-micro heeft genoeg rekenkracht. Gebruik over 7 dagen: p50 **0,037 kern**, hoogste uurgemiddelde **0,121 kern** (limiet 0,25). Per minuut lag het gebruik 22 keer in 3 dagen boven 0,25 (0,5%); dat vangt de burst van shared-core op. | Cloud Monitoring `instance/cpu/usage_time`, ALIGN_RATE, vensters van 60 s, 300 s en 3600 s (`cpu2.py`). `reserved_cores` = 0,5 (e2-small). |
| B8 | Het wordt krap in het geheugen maar het past. Container 243–258 MiB. VM 540–558 MB "used" op e2-small. Een e2-micro heeft ~970 MiB bruikbaar, plus 1 GB swap als buffer. **De poort (container-piek < 450 MiB, VM < 700 MB) wordt vanavond om 18:17 UTC gemeten**, na ≥ 24 u zonder herstart. | `docker stats`/`free -m` van 16- en 17-09 (PLAN M4). `memory.peak` volgt vanavond. |
| B9 | Oude secretversies en de n8n-secrets worden nergens gelezen. De code leest alleen `versions/latest`, op 3 plekken. | `utils/gcp_secrets.py:58`, `utils/treasury_executor.py:1650`, `agents/swarm_monitor.py:2595`. `grep N8N_` in .py/.yml/.sh/.ps1 (zonder venv) geeft 0 treffers. Het n8n-image staat op de VM maar draait niet (`docker system df`: 1 actieve container). |
| B10 | De overige Google-diensten blijven binnen hun gratis staffel. | `serviceruntime.googleapis.com/api/request_count` over 7 d: **Secret Manager** 229 aanroepen (10.000/mnd gratis). **Logging:** `billing/bytes_ingested` 1,25 GiB/30 d (50 GiB gratis). **Cloud Build:** 5 builds in september. |
| B11 | Het publieke IP-adres staat nergens vast: niet in de code en niet op een allowlist. Dashboard en SSH lopen via `gcloud` op naam. | Grep op `34.38.71` in de repo: 0 treffers. De firewallregels voor 8080 zijn op 16-09 verwijderd (`project_dashboard_niet_publiek`). |
| B12 | De kostenteller is getoetst: 12 toetsen groen, en **10 van de 10 mutaties** worden gevangen. De gevangen mutaties: onbekend → 0, geen timeout, geen Metadata-Flavor-kop, altijd opnieuw vragen, mislukking eeuwig bewaren, geen cache, inf toegestaan, geen bijkosten, vaste 0,44 in de dagstaat, env-var genegeerd. | `python -m pytest tests/test_infra_kosten.py`; plugin `mut_infra.py` in de scratchpad. |

## Procedure M4 (stap 3)

**Voorwaarden.** Alle vijf moeten waar zijn, anders niet uitvoeren.
1. De geheugenpoort van vanavond is gehaald: piek < 450 MiB en VM < 700 MB.
2. De full deploy van 18:17 is geverifieerd: verify_live 10/10 en dashboard 200.
3. Er loopt geen kasbeheer-voorstel. Controle: `_yield_beweging_onderweg` is onwaar en er staat geen APPROVED-voorstel van welk type ook.
4. Het is ≥ 20:00 UTC.
5. Er is geen alarm van de monitor in het laatste uur.

**Stappen.**
1. **Swap aanmaken** (terwijl e2-small nog draait):
   - `fallocate -l 1G /swapfile`, `chmod 600`, `mkswap`, `swapon`;
   - regel toevoegen aan `/etc/fstab`;
   - `vm.swappiness=10` in `/etc/sysctl.d/99-swap.conf`;
   - controleren met `swapon --show`.
2. **Nulmeting noteren:**
   - NAV (`python -m utils.nav`);
   - open posities;
   - `memory.peak`;
   - het oude IP-adres.
3. **Stoppen en verkleinen:**
   - `gcloud compute instances stop agent-trader-swarm-vm --zone=europe-west1-b`;
   - `gcloud compute instances set-machine-type … --machine-type=e2-micro`.
4. **Netwerk naar Standard Tier:**
   - `gcloud compute instances delete-access-config … --access-config-name=external-nat`;
   - `gcloud compute instances add-access-config … --access-config-name=external-nat --network-tier=STANDARD`.
5. **Starten:** `gcloud compute instances start …`. Docker start bij het opstarten en de container heeft `restart: always`.
6. **Verifiëren (binnen 10 minuten):**
   - de container draait;
   - dashboard 200 (`curl localhost:8080` op de VM);
   - `verify_live` 10/10;
   - de volgende ronde van de monitor zonder fouten;
   - uitgaande verbindingen: HL `/info`, Tenderly-RPC en Supabase, zichtbaar in de logs;
   - `free -m` en `swapon --show`;
   - de NAV gelijk aan de nulmeting, op koersbewegingen na;
   - `curl metadata …/machine-type` geeft e2-micro.
7. **Nazorg:**
   - na 1 u en 3 u `memory.peak`, swapgebruik en `dmesg | grep -i oom` controleren;
   - na 24 u de M4-poort opnieuw meten.

**Terugdraaien.** Commando's: `stop` → `set-machine-type e2-small` → `start`, in ~5 min. Standard Tier mag blijven staan.

Terugdraaien bij één van deze signalen:
- een OOM-kill;
- de container herstart (RestartCount > 0);
- meer dan 300 MB swap, langer dan een uur;
- CYCLE_FROZEN;
- het dashboard reageert niet;
- een monitorcheck die door traagheid faalt.

**Secrets opruimen (stap 4).**
- Per secret: `gcloud secrets versions destroy <versie> --secret=<naam>` voor elke ENABLED-versie behalve de nieuwste. Dat zijn GOOGLE_API_KEY 3, SUPABASE_KEY 1, SUPABASE_URL 1 en TELEGRAM_CHAT_ID 1. De twee n8n-secrets worden in hun geheel verwijderd: `gcloud secrets delete N8N_SECRET_TOKEN` en `gcloud secrets delete N8N_WEBHOOK_URL`.
- **Eerst controleren:**
  - dat "latest" dezelfde waarde geeft als vóór het opruimen (hash vergelijken, waarde niet tonen);
  - dat de container na afloop nog secrets kan lezen (volgende herstart).

## Raakt deze KPI's / poorten

- **M4:** "e2-micro (poort: 24 u container < 450 MiB); kosten ≤ $0,25/dag".
  - Na uitvoering is de rekenkracht-kant gehaald.
  - Het kostendoel is gehaald **als** de schijf onder de gratis staffel valt. Dat laat alleen de factuur zien (K6).
  - Tot dan: **M4 = DEELS** (regel: onmeetbaar ≠ gehaald). De poort wordt **niet** opgerekt.
- **H1:** de kostenbasis stijgt van 0,44 naar 0,525 (e2-small) en daalt daarna naar 0,304 (e2-micro, conservatief).
  - Historische dagen in `kpi.json` (16-09) houden 0,44 en zijn dus ~$0,08 te gunstig.
  - `cost_log.json` bewaart alleen de dag van vandaag opnieuw.
- **H4 en H5:** 3–5 minuten stilstand van de monitor. Het risico op geheugennood neemt toe (zie pre-mortem).

## Risico en terugdraaien

**Geld dat maximaal op het spel staat.**
- Tijdens de stilstand: de open posities van de dip-koper zonder software-stop. De stop staat op −25% per positie, dus een beweging van die orde in 5 minuten is nodig om schade te geven.
- Kasbeheer: er loopt niets (voorwaarde 3).

**Pre-mortem: wat maakt dit waardeloos of gevaarlijk?**

1. **Geheugennood 's nachts, zonder dat iemand het ziet.**
   - De monitor draait in de container zelf. Er is **geen externe waakhond**: geen workflow of dienst merkt het als de hele VM of container stilvalt. Grep in `.github/workflows` op swarm_health, heartbeat of 8080 geeft niets.
   - Swap maakt een OOM-kill minder waarschijnlijk, maar een trage swarm meldt dat ook niet zelf.
   - **Mitigatie nu:** mijn sessie meet na 1 u en 3 u.
   - **Structureel (vervolg, buiten dit blad):** een dode-mansknop buiten de VM, bijvoorbeeld een GitHub Actions-cron die de leeftijd van `swarm_health` in Supabase controleert.
2. **De schijf blijkt tóch niet gratis.** Dan kost M4 $0,26/dag en is het doel niet gehaald. Een kleinere schijf (10 GB) vraagt een nieuwe schijf plus een migratie; niet voor $0,03/dag.
3. **Het nieuwe IP-adres staat ergens op een allowlist** die niet in de repo staat, bijvoorbeeld bij Tenderly of Supabase. Dan faalt het uitgaande verkeer, wat stap 6 binnen 10 minuten laat zien. Terugdraaien kan niet naar het oude IP-adres (ephemeral), wel naar Premium met een nieuw adres.
4. **Een volgende full deploy** (docker pull van 1,4 GB) is op e2-micro trager, en de CPU-burst raakt uitgeput. `deploy_update.sh` wacht nu 18 × 5 s op het dashboard; dat kan te kort blijken.

**Gemiste kansen.**
- Een 1-jarige committed use discount op e2-micro kost $0,139/dag in plaats van $0,221. Dat is een betalingsverplichting van ~$51 → besluit van Bart, niet van mij.
- Een opschoonbeleid op Artifact Registry (automatisch de laatste 5 houden).

## Wat ik zelf niet heb gecontroleerd

- **De echte factuur.** Er is geen BigQuery-export, de browser-extensie was niet verbonden en in Gmail staan geen GCP-facturen. Of de schijf- en IP-staffels in europe-west1 echt €0 opleveren, is dus een aanname op basis van de catalogus.
- **Of de HL-API een IP-adres uit de VS echt weigert.** Ik heb dat niet getest, want een verbinding vanuit de VS is al in strijd met de voorwaarden.
- **Of disabled secretversies ook betaald worden.** Daarom wordt er vernietigd en niet uitgeschakeld.
- **Of Standard Tier werkt voor Google-API's en Artifact Registry.** Die gaan via Google's eigen netwerk; ik verwacht geen verschil, maar heb het niet gemeten.

---

## Audit

*Controle-agent, 2026-09-17 (overgenomen door de bouwer; de agent heeft geen schrijftools).*

**Oordeel per onderdeel**
- **Meetcode H1:** GO-mits.
- **M4-procedure:** **STOP voor vanavond**, daarna GO-mits.
- **Secrets opruimen:** GO-mits.

**Blokkerend**
1. **De geheugenpoort meet een andere image dan die op de e2-micro gaat draaien.** De full deploy van 18:17 zet de 24-uursklok terug (PLAN:52) en brengt nieuwe code mee. M4 om 20:00 zou dan leunen op minder dan 2 uur geheugendata, en dat is de poort oprekken.
   - **Voorwaarde, kies één:**
     - (a) vanavond deployen, op 18-09 vanaf ~18:20 opnieuw 24 uur meten, en M4 op 18-09 vanaf 20:00 (advies);
     - (b) M4 zonder deploy.
2. **Welk getal de poort meet, ligt niet vast.**
   - `memory.peak` = **419,6 MiB** (93% van de poort), inclusief 75,7 MiB paginacache en `docker exec`-sessies.
   - `docker stats` sinds de herstart: 249,7–305,0 MiB. VM maximaal 561 MB.
   - **Leg vóór 18:10 vast welk getal telt.** Advies: `memory.peak`.

**Belangrijk**
3. **Secrets verkeerd geteld.**
   - Er zijn 22 enabled en **6 disabled** versies (HL_PRIVATE_KEY v1–3, HL_WALLET_ADDRESS v1–3). Volgens de prijspagina zijn ook disabled versies "active".
   - Dat geeft nu **28** actieve versies, en na het plan **18**.
   - Secrets kosten nu $0,043/dag en na het plan $0,024. De bijkosten worden 0,114 nu en 0,095 na het plan.
   - **M4 optimistisch = 0,221 + 0,004 + 0,008 + 0,024 = $0,257, dus > 0,25.** Alleen als ook de 6 disabled versies weg zijn, kom je op 0,245. "DEELS" is daarom te gunstig.
4. **Het IP-adres wordt anders behandeld dan de schijf.**
   - De catalogus (C054) geeft 0–720 u gratis, maar de VPC-prijspagina zegt: *"This free usage is limited to one hour per month per account"*.
   - Ook bij de schijf spreken bronnen elkaar tegen: de free-tier-pagina zegt *"Usage calculations are combined across the supported regions"*.
   - **Voorwaarde:** tel het IP ook conservatief mee, of vraag Bart het Billing-rapport per SKU over september. Dat beantwoordt beide vragen, want er draaiden tot 16-09 twee VM's met elk een schijf en een IP.
5. **Een venster van 24 uur mist bekende geheugenpatronen.**
   - Tussen 26-08 en 14-09 steeg het dagminimum van de container van 281,8 naar 331,6 MiB.
   - Pieken:
     - VM 709/727 MB om 06:45 (apt-daily-upgrade);
     - **VM 1084 MB op 07-09 om 04:00**;
     - VM 885 MB op 11-09;
     - container 470,9 MiB op 20-08.
   - **Voorwaarde:** 7 dagen nazorg met een dagelijkse trendcontrole (`mem_history.log`).
6. **Swap op pd-standard** haalt ~22 IOPS. **Voorwaarde:** een drukmaat meenemen (`/proc/pressure/memory` of `vmstat si`).
7. **De herstart doet meer dan alleen het machinetype wijzigen.**
   - Uptime 109 dagen, en `reboot-required` staat aan (nieuwe kernel en libc6).
   - Het startup-script draait apt bij elke boot.
   - De statebestanden staan alleen op deze schijf, en er is geen SIGTERM-afhandeling.
   - **Voorwaarden:**
     - vooraf een snapshot;
     - `get-serial-port-output` in het terugdraaiplan;
     - de statebestanden na de start op geldige JSON controleren.
   - Overweeg eerst een losse herstart op e2-small.
8. **Een externe waakhond hoort vóór M4 live te zijn**, of het risico moet expliciet genomen worden.
9. **De 6 disabled HL-versies zijn oude private keys**, v1/v2 van vóór 13-03. Alleen vernietigen na controle dat die adressen leeg zijn, en na een besluit van Bart.

**Klein**
10. Drie mutaties blijven groen. **Voorstel:** URL en 3600 letterlijk in de toets pinnen, en e2-small gebruiken in de dagstaat-toets.
11. `INFRA_COST_USD_DAILY=0` wordt geaccepteerd.
12. **Kostenregistratie te gunstig:**
    - op de M4-dag telt de hele dag tegen de e2-micro-prijs;
    - in `kpi.json` staat 16-09 op 0,44.
13. `scripts/overzicht.py:567,598` noemt nog "$160 per jaar".
14. De regelnummers in B9 zijn verouderd (`treasury_executor.py:1712`, `swarm_monitor.py:2680`).
15. **B1: de conclusie klopt, maar de bron niet.**
    - In de HL-voorwaarden staat het in **§1.6** (personen in de VS). §3.1.5 verbiedt VPN of proxy.
    - De frontend kent `userIpBlocked` → `deposits.and.withdrawals.not.allowed`.
16. **CUD:** het minimum is 1 vCPU. 1 vCPU + 1 GB voor een jaar kost $150/jaar, meer dan e2-micro on-demand. **Niet aan Bart voorleggen.**
17. **Firewall:** `allow-n8n-ingress` (tcp:5678 vanaf 0.0.0.0/0), `default-allow-rdp` en 80/443 staan open. Alleen 22 en 8080 luisteren echt.
18. De gratis 200 GiB van Standard Tier geldt per account, niet per regio.
19. Voorwaarde 3 is te smal. Gebruik de `active`-set (`treasury_agent.py:2060-2064`) plus FUND_SLEEVE/SLEEVE_REBALANCE.
20. Stap 5 (documentatie) is nog niet gedaan: PLAN, CLAUDE.md en `deploy.ps1:13`.

**Zonder bevinding gecontroleerd**
- **Prijzen** uit de catalogus (33.395 SKU's): core en RAM, D973, Artifact Registry, Premium en Standard.
- **Verkeer:** 94–369 MB/dag.
- **CPU:** 0,51% van de minuten boven 0,25 kern, hoogste uurgemiddelde 0,107.
- **Container en VM:**
  - de container bereikt de metadataserver (e2-small in 0,011 s; zonder header 403);
  - `INFRA_COST_USD_DAILY` is leeg in de container;
  - de toegangsconfig heet `external-nat`;
  - er zijn geen snapshots en geen statische IP's;
  - e2-micro is beschikbaar in europe-west1-b;
  - de container heeft `restart=always`;
  - nergens staat een vast IP-adres.
- **Meetcode:** hooguit elk uur een momentopname; `kpi.py` leest met `isfinite`; 10/10 mutaties van de bouwer gevangen; 400 toetsen groen; de monkeypatch wordt hersteld.
- **Secrets:** n8n heeft 0 treffers in de repo, op de VM en in de container-env. Geen IAM op secretniveau. De code leest alleen `latest`.

**Pre-mortem:** een langzame of pieksgewijze geheugennood, 's nachts, bij een VM-piek als die van 07-09. Die blijft onopgemerkt zonder waakhond en met maar 3 uur nazorg.

**Gemiste kansen:**
- het Billing-rapport per SKU nu opvragen;
- de disabled HL-versies vernietigen;
- een opschoonbeleid voor de registry;
- zram, en snapd/multipathd weghalen;
- het startup-script idempotent maken;
- de firewall opschonen;
- een VPS buiten GCP (besluit van Bart).

**Secrets opruimen:** GO-mits, onder vier voorwaarden:
- een hash-controle plus een leestoets per secret;
- niet in hetzelfde venster als M4;
- aantallen corrigeren (28 → 18);
- de disabled HL-versies alleen na controle en een besluit van Bart.

## Reactie bouwer

*Ronde 2, 2026-09-17.*

| # | Status | Wat |
|---|---|---|
| 1 | **gevolgd (a)** | De verkleining van 17-09 is geschrapt (geplande taak verwijderd). Vanavond: deploy, en daarna **24 u meten op de nieuwe image**. M4 op zijn vroegst 18-09 ≥ 20:00 UTC, en alleen als alle voorwaarden hieronder groen zijn. |
| 2 | **vastgelegd vóór 18:10** | De poort meet **`memory.peak`** van de container (cgroup v2), gelezen ≥ 24 u na de laatste start, **< 450 MiB**. De VM blijft < 700 MB "used" volgens `free -m`, piek uit `mem_history.log`. Vastgelegd in PLAN M4. |
| 3 | **opgelost in de meetcode** | Secrets tellen als 28 actief ($0,043/dag). |
| 4 | **opgelost in de meetcode** | Het IP telt conservatief mee ($0,122/dag). `_BIJKOSTEN_USD_PER_DAG` = **0,232** (schijf 0,039 + IP 0,122 + registry 0,008 + secrets 0,043 + verkeer 0,020). De teller rekent nu **$0,674/dag** voor e2-small en $0,453 voor e2-micro. Bart krijgt het verzoek om het Billing-rapport per SKU over september, dat beide staffelvragen beantwoordt. **Conclusie M4:** het kostendoel (≤ $0,25) is in de EU met dit plan ook in het gunstigste geval niet gehaald ($0,257). Dat wordt aan Bart gemeld als mijlpaal die zo niet haalbaar is; de poort wordt niet opgerekt. |
| 5 | **overgenomen** | Voorwaarde voor M4: 7 dagen nazorg met een dagelijkse trendcontrole (`mem_history.log`). |
| 6 | **overgenomen** | Voorwaarde voor M4: een drukmaat (`/proc/pressure/memory`, avg60) in het terugdraaiplan. |
| 7 | **overgenomen** | Voorwaarden voor M4: vooraf een schijfsnapshot, `get-serial-port-output` in het terugdraaiplan, en de statebestanden na de start op geldige JSON controleren. Een losse herstart op e2-small vooraf wordt overwogen. |
| 8 | **overgenomen** | M4 pas als de waakhond live is (claimblad `2026-09-17-waakhond.md`). |
| 9 | **naar Bart** | De disabled HL-versies worden niet vernietigd zonder zijn besluit. |
| 10 | **opgelost** | URL en de klok (3000 s nog niet, 3600 s wel) staan letterlijk in de toetsen, e2-small in de dagstaat. Extra toets op een fout die geen OSError is. De mutaties van de auditor (`aud2_mut.py`, env `MUT2`): 8/8 rood. Mijn eigen set: 10/10. |
| 11 | **opgelost** | `INFRA_COST_USD_DAILY` ≤ 0 wordt genegeerd. Toets met "0" en "0.0". |
| 12 | **genoteerd** | Op de M4-dag telt de hele dag tegen de e2-micro-prijs, en 16-09 staat op 0,44. Terugwerkend corrigeren van `kpi.json` doe ik niet in deze ronde; de fout is ≤ $0,25 en de richting staat in het PLAN. |
| 13 | **open (klein)** | `scripts/overzicht.py` noemt nog $160 per jaar. Aanpassen bij de volgende publicatie van de overzichtspagina. |
| 14 | **genoteerd** | Regelnummers in B9. |
| 15 | **overgenomen** | Bron voor B1: HL-voorwaarden §1.6 en §3.1.5, plus `userIpBlocked` in de frontend. |
| 16 | **overgenomen** | CUD wordt niet voorgelegd. |
| 17 | **open** | Firewall opschonen (n8n 5678, RDP, 80/443): apart, na de n8n-besluit. |
| 18 | **overgenomen** | Standard Tier: de 200 GiB gelden per account. |
| 19 | **overgenomen** | Voorwaarde 3 van de procedure wordt: de `active`-set van kasbeheer plus FUND_SLEEVE/SLEEVE_REBALANCE, niets onderweg. |
| 20 | **bij M4** | Documentatie (deploy.ps1, CLAUDE.md) pas als M4 echt wordt uitgevoerd. Het PLAN wordt nu bijgewerkt. |

**Secrets opruimen:** uitgesteld tot na M4 (niet in hetzelfde venster), met de aantallen 28 → 18. De disabled HL-versies alleen na een besluit van Bart.

## Audit ronde 2 (meetcode + PLAN-regel)

*Controle-agent, 2026-09-17 (overgenomen door de bouwer).*

**Oordeel: meetcode GO · PLAN-regel GO-mits.**

**Belangrijk**
1. **"Ook in het gunstigste geval niet gehaald" is te stellig**; de bewering kwam uit ronde 1 van de auditor zelf. Met het opschonen van de registry (1–2 images) komt het gunstigste geval op ~$0,249–0,251, en alleen europe-west1 is geprijsd. **Mits:** in PLAN en in het bericht aan Bart spreken van een "grensgeval, gunstigst $0,245–0,257, conservatief $0,453, in europe-west1", en een eerder bericht corrigeren.
2. **`memory.peak` telt ook `docker exec`-sessies mee.** De NAV-controle en de bijvulling vallen vanavond in het meetvenster. **Mits:** vooraf vastleggen dat die sessies meetellen, zonder uitzondering achteraf.

**Klein**
3. **De fees in `cost_tracker` staan altijd op 0**: de code leest `size`, en die bestaat niet. Dat is toevallig juist, want de NAV bevat de fees al. Maak dat expliciet.
4. **De VM-poort in het PLAN zegt niet dat het om de piek gaat.** In 37 dagen lag op 6 dagen een meting ≥ 700 MB.
5. **In de PLAN-regel ontbreken drie dingen:**
   - dat een hot-patch de klok terugzet;
   - FUND_SLEEVE/SLEEVE_REBALANCE in voorwaarde 3;
   - een getal voor de nazorg.
6. **"Vastgelegd vóór 18:10" is alleen aan te tonen met een commit.**

**Gecontroleerd:**
- mutaties `mut_infra` 10/10 en `aud2_mut` 8/8 rood;
- `kpi.py` leest alleen `total_cost_usd`;
- de bedragen in het PLAN nagerekend.

## Reactie bouwer ronde 2

| # | Status | Wat |
|---|---|---|
| 1 | **opgelost** | PLAN M4 spreekt nu van een "grensgeval": gunstigst $0,245–0,257, conservatief $0,453, alleen europe-west1 geprijsd. Het bericht aan Bart wordt in de chat gecorrigeerd. |
| 2 | **opgelost** | PLAN M4: `memory.peak` telt paginacache én alle `docker exec`-sessies, zonder uitzondering. Die sessies houden we kort en hun tijdstip loggen we. Niet opnieuw meten tot de meting haalt. |
| 3 | **opgelost** | `total_cost_usd` = LLM + infra. Fees staan alleen nog als informatie in `exchange_fees_usd`, met commentaar. Toets: `test_beursfees_tellen_niet_mee_in_de_totale_kosten`. Mutatie `fees_in_totaal` rood. |
| 4 | **opgelost** | PLAN M4 meet de VM-**piek** uit `mem_history.log`, en een apt-piek telt mee. |
| 5 | **opgelost** | In PLAN M4 staat nu: een hot-patch zet de klok terug; voorwaarde 3 omvat FUND_SLEEVE/SLEEVE_REBALANCE; de nazorg eist elke dag een container-dagpiek < 450 MiB, PSI some avg60 < 5, 0 OOM-kills en RestartCount 0. |
| 6 | **opgelost** | De commit van deze PLAN-regel valt vóór 18:10 UTC. |
