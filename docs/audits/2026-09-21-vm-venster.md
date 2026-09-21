# Claimblad — De VM draait alleen in een dagvenster (optie 1: H1 positief via de kosten)

*Datum: 2026-09-21 · Poort: A2 (infrawijziging onder draaiend geld + wijziging in risicobeheer) en A1 (meetcode voor H1) · Mijlpaal: M4-vervolg / H1*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert

Besluit Bart 21-09 ("het is optie 1"). De VM draait niet meer 24/7 maar **elke dag van 12:30 tot 21:30 UTC**, zeven dagen per week, via een GCP-instance-schedule (resource policy). Daarbuiten staat hij uit; dan betaal je alleen de schijf.

**Voorwaarden die eerst moeten staan (in deze volgorde):**
1. **Opstartscript idempotent.** Nu draait bij elke boot `apt-get update && apt-get install -y docker.io docker-compose`. Voorstel: alleen installeren als `docker` ontbreekt. Bij een dagelijkse boot is apt anders elke ochtend een geheugenpiek op 1 GB en een kans om docker halverwege te upgraden.
2. **Waakhond zonder nachtelijk vals alarm.** De afwezigheidsmelding krijgt een tweede voorwaarde met AND: *hartslag afwezig > 15 min* **én** *de VM draait* (`compute.googleapis.com/instance/uptime` aanwezig). Staat de VM volgens schema uit, dan geen melding. Brandoefening vooraf verplicht.
3. **Kostenteller rekent met draaiuren.** `utils/cost_tracker.py` rekent nu 24 uur rekenkracht per dag. Nieuw: rekenkracht per uur × **gemeten** draaiuren van die dag, plus de vaste bijkosten. Geen vaste constante (die veroudert stil, zie de kostenteller-historie).
4. **Na de M4-nazorg.** De nazorg loopt tot 26-09 en meet "is 1 GB genoeg bij doorlopend draaien". Ingaan op **27-09** of later, tenzij de auditor combineren verantwoord vindt.

## Beweringen

| # | Bewering | Bewijs |
|---|---|---|
| V1 | **Besparing ~$50/jaar.** Rekenkracht e2-micro $0,221/dag × 9/24 = $0,083/dag. Vaste bijkosten $0,061/dag (factuur september). Totaal **$0,144/dag = $52,5/jaar**, nu $0,282/dag = $103/jaar. | `utils/cost_tracker.py` (`_COMPUTE_USD_PER_DAG`, `_BIJKOSTEN_USD_PER_DAG`); factuur per SKU. |
| V2 | **H1 wordt positief:** opbrengst ~$73/jaar (Aave 2,92% op $2.490) min ~$53 kosten = **~+$20/jaar**, zonder extra risico aan de geldkant. | Opbrengst uit `data/kpi.json`; kosten uit V1. |
| V3 | **Alle 14 openingen van de dip-koper vielen tussen 14:00 en 20:00 UTC.** Een venster van 12:30–21:30 mist er geen. | `thematic_exposure_positions.json`, `opened_at`, alle posities. |
| V4 | **Twee van de acht sluitingen vielen buiten dat venster:** CRCL om 09:06 UTC (winstneming) en MRVL op zaterdag 18:23 (binnen het uur, maar in het weekend). Het venster draait daarom ook in het weekend. De CRCL-sluiting was zo'n 4 uur later gebeurd. | Idem, `closed_at`. |
| V5 | **De xyz-markten handelen 24/7.** Uurvolume en -beweging over 7 dagen: GOOGL 's nachts 0,08–0,31% per uur tegen 0,15–0,34% tijdens Amerikaanse uren; TSLA idem. Een stop kan 's nachts dus niet uitgevoerd worden. | HL `candleSnapshot` 1u, `xyz:GOOGL` en `xyz:TSLA`, 7 dagen. |
| V6 | **Het extra verliesrisico van V5 is klein.** De software-stop staat op −25% per positie; posities zijn ~$45 (6 stuks, $269 totaal). Een gat van 30% 's nachts op één positie kost ~$2 méér dan de stop — alleen bij zo'n gat. | `SLEEVE_MAX_DRAWDOWN_STOP_PCT = 25.0` (`utils/thematic_exposure_lab.py:121`); posities uit het positiebestand. |
| V7 | **De dagelijkse meting valt niet weg.** `SleeveNAV.snapshot_if_new_day()` draait bij de eerste cyclus op een nieuwe dag, dus straks rond 12:35 UTC in plaats van 00:03. Elke datum krijgt nog steeds één snapshot; H5 ziet geen gat. De eerste overgangsdag heeft een interval van ~36 uur. | `main.py:563`; `utils/sleeve_nav.py`. |
| V8 | **Kasbeheer merkt het niet.** Na een boot draait de eerste cyclus een volledige kasbeheerronde (`main.py:482`), dus `treasury_state.json` is binnen minuten vers (grens `STALE_HOURS = 3`). | `main.py:482`; `utils/sleeve_nav.py:33`. |
| V9 | **Een dagelijkse herstart dempt een geheugenlek** in plaats van het te verbergen: het geheugen begint elke dag schoon. De nazorgmeter (`mem_sample.sh`, elke 15 min via cron) draait alleen als de VM aan staat; dat is genoeg om de dagpiek te zien. | `scripts/vm/mem_sample.sh`; crontab op de VM. |
| V10 | **Wat 's nachts wegvalt:** (a) sluitingen van de dip-koper (V4, V6); (b) de bewaking van Aave elke 5 minuten door Check 24 — de kill-actie daar is sowieso "melden en handmatig opnemen" (`config/experimenten.json`), dus zonder iemand die 's nachts reageert verandert er weinig; (c) de kern-crypto heeft geen stops en hoeft niet bewaakt. | `config/experimenten.json` `veilig_integriteit.kill_actie`; `config/conviction_core.json`. |

## Raakt deze KPI's / poorten

- **H1:** van ~−$30/jaar naar ~+$20/jaar.
- **H4 (detectie ≤ 10 min):** geldt voortaan alleen binnen het venster. Buiten het venster is detectie de eerstvolgende start (maximaal 15 uur). Dat is een bewuste verzwakking en hoort als zodanig in het PLAN.
- **M4:** de besparing stapelt op de verkleining.

## Risico en terugdraaien

- **Maximaal op het spel:** het gat voorbij −25% op één of meer dip-koperposities tijdens een nacht. Bij 6 posities van ~$45 en een gat van 30% op álle zes (extreem): ~$13 extra.
- **Dagelijkse boot = dagelijkse kans op een mislukte start.** Mitigatie: idempotent opstartscript (voorwaarde 1), waakhond met AND-voorwaarde (voorwaarde 2), en de swap staat in `/etc/fstab`.
- **Deploys** kunnen alleen binnen het venster.
- **Terugdraaien:** de resource policy loskoppelen (`gcloud compute instances remove-resource-policies`); de VM draait dan weer 24/7. Eén commando.

## Wat ik zelf niet heb gecontroleerd

- Of een AND-voorwaarde met een afwezigheidsconditie in Cloud Monitoring zich gedraagt zoals ik verwacht. Daarvoor is de brandoefening.
- Of de xyz-markten bij een gat 's nachts voldoende liquiditeit hebben om de stop bij de start uit te voeren.
- Hoe lang een koude start duurt (boot + docker + container + eerste volledige ronde) op e2-micro.
- Of `RestartCount` bij een VM-herstart op 0 blijft; zo niet, dan moet het nazorgcriterium "RestartCount 0" anders gelezen worden.

---

## Audit
*(in te vullen door de controle-agent)*

## Reactie bouwer
*(per open punt: opgelost in `<hash>` of weerlegd met bewijs)*
