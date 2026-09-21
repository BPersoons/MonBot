# Claimblad: dip-koper bewaart gesloten rondes en stopt luid bij een onleesbaar positiebestand

*Datum: 2026-09-21 · Poort: A1 (deploy van code die geld raakt) · Mijlpaal: geen (dip-koper-evaluatie 25-09)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijft **wat** er verandert en
> **welk bewijs** er is, niet hoe ik tot de conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
- Commit: `3f4b965`. Bestanden: `utils/thematic_exposure_lab.py` en `tests/test_thematic_exposure_lab.py` (klasse `TestPositiebestandVeiligheid`, 6 toetsen).
- Meetcontext uit de voorgaande commit `f37c28d`: `scripts/dipkoper_resultaat.py` en `docs/dipkoper_evaluatie_2026-09-25.md` §4.2.
- Productie-impact: de dip-koper (ThematicExposureLab, wallet 0xBd6c…), met ~$255 budget, 6 open posities en ~$12,70 kas. Het statebestand is `thematic_exposure_positions.json`: een bind mount die in `STATE_FILES` staat.

## Beweringen
| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| 1 | Een tweede ronde in dezelfde naam overschreef de eerste. CRCL, ORCL en TSLA misten daardoor samen $13,34 in de som per positie; CRWV (−$3,17) sloot vóór het veld per positie bestond. Samen verklaart dat het verschil met de HL-fills op $0,07 na. | `python scripts/dipkoper_resultaat.py --adres <0xBd6c…>`: gerealiseerd +$29,67, fees $0,16, funding −$1,79. Positiebestand: som per positie $19,57, totaalveld $27,68. |
| 2 | Een gesloten ronde gaat vóór het overschrijven naar `positions["gesloten_rondes"]` (lijst, met `ticker`). Bijkopen in een OPEN positie archiveert niets. | `_record_open_or_add`, else-tak. Toetsen `test_tweede_ronde_bewaart_de_eerste` en `test_bijkopen_in_een_open_positie_archiveert_niets`. |
| 3 | Alle lezers van het positiebestand lopen alleen over `positions["positions"]`. Een extra lijst bovenin breekt geen lezer. | grep `thematic_exposure_positions` → 11 bestanden: swarm_monitor, blootstelling, sleeve_benchmark, dashboard_home, dashboard_thematic_exposure, divergence_filter, kpi, nav, sleeve_nav, verliesbewaking, lab. Controleer zelf op `.items()`/`.values()` op het topniveau. |
| 4 | Vroeger gaf `_load_positions` bij elke fout stil een leeg potje terug ($255 kas, nul posities). Nu: bestaat het bestand niet, dan een leeg potje. Bestaat het wel maar is het onleesbaar (kapotte of lege JSON, geen dict, `positions` geen dict, een map), dan `PositiesOnleesbaar`. | `_load_positions`. Toets `test_half_geschreven_leeg_of_map_is_onleesbaar`. |
| 5 | Bij een onleesbaar bestand slaat `run_cycle` alles over: scan, beheer, sweep en aankoop. De order-client wordt niet aangeroepen en het bestand niet overschreven. Telegram gaat één keer per herstart. | `run_cycle`. Toets `test_cyclus_op_onleesbaar_bestand_doet_niets_en_meldt_een_keer`. |
| 6 | Zes mutaties maken elk een toets rood: archivering weg, `lexists` wordt altijd waar, de raise wordt een leeg potje, de meldvlag weg, de return in `run_cycle` weg, de dict-check weg. | Eigen mutatierun, 21-09. |
| 7 | De pre-deploy-poort is groen. | `python scripts/predeploy.py`: state-audit, syntax, pytest en pipeline ok. |

## Bewuste afwijking (graag beoordelen)
`scripts/deploy_update.sh:109-130` behandelt een bestand van 0 bytes als "ontbreekt": het seedt
met `touch`, en de lezers vallen dan terug op leeg. Mijn wijziging behandelt een **leeg**
positiebestand juist als onleesbaar, en dus als stilstand. Twee redenen:
1. Een SIGKILL tussen `open("w")` (die afkapt) en `json.dump` laat precies 0 bytes achter. Bij
   geld is stilstaan met een melding beter dan doen alsof er geen posities zijn.
2. Het deployscript seedt met `touch` alleen als het bestand ontbreekt én er geen backup is. Dat
   logt het script al als "any prior data is lost". In productie bestaat het bestand.

Het gevolg bij een echt verse installatie: de dip-koper staat stil tot iemand `{}` schrijft.

## Raakt deze KPI's en poorten
- H3 (verlies binnen kader), H5 (meting betrouwbaar), de dip-koper-evaluatie van 25-09.

## Risico en terugdraaien
- **Wat kan misgaan:**
  - een vals positief. Een geldig bestand wordt als onleesbaar gezien en de dip-koper staat stil;
    open posities worden dan niet beheerd. Check 20 (thema-wallet −20%) blijft wel kijken.
  - een schrijffout in de archivering, waardoor een aankoop wel op HL staat maar niet in het
    bestand. De archivering gebeurt vóór het nieuwe vak, in dezelfde save.
- **Maximaal op het spel:** het budget van ~$255.
- **Terugdraaien:** `git revert 3f4b965`, dan een hot-patch van `utils/thematic_exposure_lab.py`.

## Wat ik zelf niet heb gecontroleerd
- Of het productiebestand nu door de nieuwe `_load_positions` komt. Het is JSON met een
  `positions`-dict (vandaag gelezen), maar ik heb de nieuwe functie er niet op gedraaid.
- Of `_divergence_stempel` in `_record_open_or_add` netwerk raakt in de toets. De toets was snel.
- Of de dashboards `gesloten_rondes` zouden willen tonen. Dat doen ze nu niet.

---

## Audit

### Controle-agent, ronde 1 (21-09): **GO-mits**, voorwaarde 1 hoort in dezelfde deploy
*(De bouwer heeft dit oordeel letterlijk overgenomen: de controle-agent heeft alleen leesrechten.)*

1. **[belangrijk, vóór deploy] De verkooporders van de dip-koper zijn niet `reduceOnly`.**
   - `thematic_exposure_lab.py:1403-1406` roept `create_order(..., "SELL")` aan zonder `reduce_only`. De standaardwaarde is `False` (`exchange_client.py:282, 310`) en er is geen toets voor.
   - De nieuwe melding verwijst naar "herstel uit de backup". Die backup is van 19-09. Staat daarin een positie OPEN die op HL al dicht is, dan verkoopt een stop die positie en opent daarmee een short.
   - Nodig: `reduce_only=True`, een toets die daarop controleert, en in de melding het advies om eerst met `clearinghouseState` (dex xyz) te vergelijken.
2. **[belangrijk, vóór 25-09] Verliesbewaking en sleeve_nav zien een onleesbaar bestand niet.**
   - Verliesbewaking (`:261-265`) leest `{}`: nul posities, dus geen stilstandmelding.
   - Sleeve_nav (`:246-250`) geeft 0,0 terug: een valse daling van ~$255.
   - De dip-koper meldt het zelf maar één keer.
   - Nodig: in beide een "onmeetbaar"-waarde en een alarm.
3. **[klein]** `gesloten_rondes` wordt niet als lijst gecontroleerd. Een `.append` kan daardoor falen *na* een geslaagde BUY, met een dubbele aankoop als gevolg.
4. **[klein]** Nog geen enkele lezer gebruikt `gesloten_rondes`: `divergence_filter:199` en `sleeve_benchmark:91` niet.
5. **[klein]** `scripts/blootstelling.py:7-10` gaf al voorbeeldcode over het topniveau die niet werkt. Deze wijziging maakt dat niet erger.
6. **[klein]** Er wordt niet "één keer per herstart" gemeld maar één keer per onleesbare periode.
7. **[klein]** De toetsklasse staat onder `if __name__ == "__main__"`.
8. **[klein]** Ontbreekt het bestand in de container, bijvoorbeeld doordat de mount weg is, dan ontstaat nog steeds een leeg potje. De state-audit in predeploy vangt dat af.

**Zonder bevinding:**
- Het productiebestand komt door de nieuwe loader (md5 host = container, 14 posities, kas $12,70).
- Alle 11 lezers gebruiken `.get("positions")`.
- Een fout halverwege de cyclus wordt opgevangen door de try/except in `main.py:553-556`.
- **De afwijking "leeg = onleesbaar" is terecht.**
- Er wordt in-place geschreven, en het bestand staat in de mount én in `STATE_FILES`.
- De toetsen zijn groen: 86 voor de dip-koper, 480 in totaal.

**Open vraag:** welke backup is het herstelpad, en wie vergelijkt die met HL?


## Reactie bouwer (21-09, ronde 2)
| # | Reactie |
|---|---|
| 1 | **Opgelost.** Ik heb `reduce_only=True` toegevoegd in `_close_or_trim`. Dezelfde fout zat ook in het kasbeheer: het sluiten van de harvest-short (BUY, `treasury_agent.py`) ging zonder `reduce_only`. Die is nu ook `reduce_only=True`. Toetsen: `test_elke_verkoop_is_reduce_only` (deelexit én volledige sluiting), `test_aankoop_is_niet_reduce_only` en `test_harvest_sluiten_is_reduce_only`. De Telegram-melding zegt nu dat je elke OPEN-positie vóór de herstart vergelijkt met `clearinghouseState` (dex xyz). |
| 2 | **Opgelost in dezelfde deploy.** Verliesbewaking: de nieuwe helper `_lees_dip_koper()` maakt onderscheid tussen een ontbrekend en een onleesbaar bestand, met een alarm `dip_koper_onleesbaar` (herhaalrem via `gemeld`). Sleeve_nav: bij een onleesbaar bestand of een waarderingsfout volgt `None` en wordt de snapshot uitgesteld, net als bij Conviction Core en de broker; alleen een ontbrekend bestand geeft 0,0. Toetsen: `test_dip_koper_onleesbaar_geeft_alarm`, `test_lees_dip_koper_onderscheidt_ontbrekend_van_onleesbaar`, `test_sleeve_nav_dip_koper_ontbrekend_nul_onleesbaar_none` en `test_sleeve_nav_stelt_snapshot_uit_bij_onleesbare_dip_koper` (met een controle-opzet die eerst een tuple geeft). |
| 3 | **Opgelost.** `_load_positions` gooit `PositiesOnleesbaar` als `gesloten_rondes` geen lijst is. Toets: `test_gesloten_rondes_geen_lijst_is_onleesbaar`. |
| 4 | **Bewust open.** Het doel van deze wijziging was de data bewaren. Voor de evaluatie per naam is `scripts/dipkoper_resultaat.py` (HL-fills) de bron. De lezers volgen als de dip-koper na 25-09 blijft. |
| 5 | Klopt; bestond al en valt buiten deze wijziging. |
| 6 | **Tekst gecorrigeerd:** de dip-koper meldt één keer per periode waarin het bestand onleesbaar is. Wordt het weer leesbaar en daarna opnieuw onleesbaar, dan meldt hij opnieuw. Daarnaast is er nu het alarm van de verliesbewaking. |
| 7 | **Opgelost.** De toetsklasse staat nu boven het `__main__`-blok. |
| 8 | Aanvaard. De state-audit in `predeploy.py` vangt een ontbrekende mount. |
| Open vraag | **Herstelpad:** `state_backups/<nieuwste>/thematic_exposure_positions.json` op de VM. Vóór de herstart vergelijk ik (de bouwer) elke OPEN-positie met `clearinghouseState` (dex xyz) en de fills (`scripts/dipkoper_resultaat.py`). Zo staat het ook in de melding. |

**Mutaties ronde 2:** 8 van 8 rood. Eén mutatie bleef eerst groen: in sleeve_nav liet ik een `None` naar 0,0 gaan. Mijn toets stopte toen al eerder, bij een ontbrekende `treasury_state`. Na het aanscherpen wordt die mutatie ook rood.

