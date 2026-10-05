# Claimblad — werkronde 05-10: KPI-stand en motorbesluiten

*Datum: 2026-10-05 · Poort: A4 wekelijks (+ stopbesluiten op trede 0) · Mijlpaal: M3, M4*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
- Commits / bestanden: `40067e9` (Fluid gestopt), `3c1faba` (nav-stempel + LDOS), deze ronde: `config/experimenten.json`, `docs/besluiten.md`, `docs/PLAN_2026-08.md` (M3)
- Productie-impact: `utils/nav.py` is als hot-patch live gezet. Het verandert alleen de detailtekst van de brokerpotjes, geen bedrag. `config/experimenten.json` zit in de image en komt pas mee bij de volgende full deploy. Er wordt geen geld verplaatst.

## Beweringen
| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| 1 | Productie is gezond: 0 onverwachte herstarts (één herstart door mij voor de hot-patch), dashboard 200, geen alarmen | `docker ps`, curl 8080, `data/verliesbewaking_state.json` (`gemeld: {}`, `experimentverlies_usd: 0.0`) |
| 2 | KPI's: H1 netto −$6,59 over 49 dagen (niet gehaald); H2 −0,79pp t.o.v. Aave (niet gehaald); H3 $0 (gehaald); H4 2,77 min (gehaald); H5 0 gaten (gehaald) | `python -m utils.kpi` in de container, 05-10 13:37 UTC |
| 3 | De nav-tekstwijziging verandert geen enkel bedrag: de koersen kwamen al live uit yfinance | `utils/nav.py:233` (`_koers`); NAV na de patch $5.496,10 (WEBN 13,32) tegen $5.491,28 ervoor (WEBN 13,30) |
| 4 | Beursstops voor de dip-koper kunnen stoppen: de VM draait 24/7 sinds het venster op 21-09 stopte | commit "VM-venster gestopt" (21-09); container "Up 2 weeks" vóór mijn herstart; `mem_history.log` heeft elke 15 min een meting zonder gaten |
| 5 | De geheugengroei (~90 MiB/dag) die de e2-micro-terugdraaiing verklaarde, is niet teruggekomen: de dagpiek van de container (mem + swap) lag van 24-09 t/m 04-10 tussen 310 en 343 MiB, vlak | `/home/bartpersoons_gmail_com/mem_history.log`, dagmaximum van `ctr_mem + ctr_swap` |
| 6 | Gains-TVL $4,82 mln (< $5 mln), HLP-APR 3,74% (< 6,22%), basis-funding 6,27% (< 7,38%): geen van de drie triggers is geraakt | `scripts/overzicht.py --vm`, 05-10 14:06 UTC |
| 7 | Thema-radar en uitschieterpotje worden al vooruit gemeten via de drie schaduwpotjes, vastgelegd op 22-09 vóór de uitkomst | `research/schaduwpotjes.json` (`start: 2026-09-22`, reeks t/m 02-10) |

## Raakt deze KPI's / poorten
- H1 (een e2-micro bespaart $81/jaar, meer dan het huidige tekort van ~$49/jaar), M3 (gestopt), M4 (een nieuwe poging hangt af van Bart)

## Risico en terugdraaien
- Er staat geen geld op het spel. Het grootste risico is een te snel stopbesluit (beursstops) of een te optimistische lezing van het geheugen (bewering 5).
- Terugdraaien: velden in `config/experimenten.json` terugzetten.

## Wat ik zelf niet heb gecontroleerd
- Of een e2-micro onder geheugendruk anders reageert dan een e2-small met ruimte. De e2-small-cijfers laten de natuurlijke voetafdruk zien, niet het gedrag onder druk.
- Of `ctr_peak` (555 MiB, vastgezet rond 21/22-09) docker-exec-sessies meetelt. Ik heb dagmaxima van mem + swap gebruikt, niet `ctr_peak`.

---

## Audit

**A4, controle-agent, 2026-10-05: GO-mits.** Er beweegt geen geld en het stopbesluit over de beursstops is terecht. De voorwaarden:
- (1) De e2-micro-tekst moet eerlijk zijn. Er is geen lek, maar een meting op de e2-small bewijst niets voor de e2-micro: daar kwam 150–210 MiB swap plus dubbel getelde swapcache bovenop. Ook de uitleg voor 22 en 23-09 klopte niet: dat was op de e2-small en zonder deploy.
- (2) Het uitschieterpotje gaat terug naar trede 0. De schaduwpotjes zijn geen uitschieters en meten geen UCITS-radar. De sprong van de thema-radar naar trede 2 moet expliciet in het register staan.

Kleine punten:
- de beursstops heropenen vóór een e2-micro-poging of VM-venster;
- H1 ook tonen zonder de dip-koper (~−$124/jaar);
- een leeftijdsgrens in de broker-stempel;
- een datum bij H4 (de brandoefening was op 15-09).

Volledig rapport: in de sessie van 05-10, samengevat in de reactie hieronder.

## Reactie bouwer
- (1) Opgelost. De registertekst van e2_micro_poging_2 is herschreven: geen lek, gedrag onder druk onbewezen, eerst de exec-piek weg, de poort vooraf op anon+swap−swapcache plus PSI, de beursstops eerst heropenen.
- (2) Opgelost. Het uitschieterpotje staat weer op trede 0, met een eigen schaduwontwerp als volgende stap. Bij thema_radar_keten staat nu dat trede 1 is overgeslagen en dat de meting alleen de ketenkeuze dekt.
- Kleine punten:
  - Heropen-trigger van de beursstops: verwerkt in register en besluiten.
  - Broker-stempel: waarschuwt weer na 45 dagen.
  - H1 zonder dip-koper en de datum bij H4: gemeld aan Bart.
- Open vraag 22-09 09:15 (ctr_peak 555 zonder herstart): niet uitgezocht. Dat gebeurt pas bij een nieuwe e2-micro-poging.
