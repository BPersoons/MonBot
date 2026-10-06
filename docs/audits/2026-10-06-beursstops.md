# Claimblad — beursstops voor de dip-koper

*Datum: 2026-10-06 · Poort: A1 deploy geld-code · Mijlpaal: M4 (voorwaarde voor e2-micro-poging 2)*

> Voor de controle-agent (`.claude/agents/auditor.md`). Beschrijf **wat** en **welk bewijs**,
> niet hoe je tot je conclusie kwam. De auditor gaat zelf naar de bron.

## Wat er verandert
- Commit `6d989c4`: `utils/exchange_client.py` (nieuw: `create_stop_order`, `cancel_order`), `utils/thematic_exposure_lab.py` (nieuw: `_sync_beursstops`, `_reconcilieer_beursstops`, `_boek_verkoop` uit `_close_or_trim` gehaald, overslaan van `hl_positie_weg` in `_manage_exits`, volgorde in `run_cycle`), `tests/test_thematic_exposure_lab.py` (+15 toetsen).
- Productie-impact:
  - De dip-koper-wallet `0xBd6c…` krijgt per open xyz-long één **reduceOnly stop-market**, op 30% onder de gemiddelde aankoopprijs. Nu zijn dat 6 posities van ~$45, samen ~$287.
  - Statebestand `thematic_exposure_positions.json`: nieuw veld `hl_positie_weg`; sluitingen via `_boek_verkoop`.
  - Uitzetten kan zonder deploy: `subsystem_beursstops_enabled=false` in `config/auto_params.json`. De stops die er al liggen blijven dan staan (reduceOnly, dus onschadelijk).

## Beweringen
| # | Bewering | Bewijs (bron, commando, meting) |
|---|---|---|
| 1 | Elke beursstop is reduceOnly, zonder parameter om dat uit te zetten | `utils/exchange_client.py` `create_stop_order`; toets `TestCreateStopOrderIsAltijdReduceOnly`; mutatie reduceOnly→False maakt hem rood |
| 2 | De beursstop ligt altijd onder de software-stop (−30% tegen −25%), dus normaal sluit de software eerst | `BEURSSTOP_PCT`, `SLEEVE_MAX_DRAWDOWN_STOP_PCT`; toets `test_zet_een_stop_op_dertig_procent…`; mutatie 30→20 rood |
| 3 | De grootte volgt wat HL ziet (szi), niet ons boek; een afwijkende of dubbele stop wordt vervangen; een stop zonder positie wordt geannuleerd | `_sync_beursstops`; toetsen `verkeerde_grootte`, `twee_stops`, `stop_zonder_positie`; mutatie annuleren-weg rood |
| 4 | Een positie die HL sloot terwijl de software niet keek, wordt geboekt tegen de echte fillprijs (userFillsByTime, `Close Long`, nieuwste eerst), nooit tegen een markprijs | `_reconcilieer_beursstops`; toets `gevulde_beursstop…`; mutatie fillprijs→vast getal rood |
| 5 | Zonder vindbare fills wordt er niets verzonnen: de positie krijgt `hl_positie_weg`, er komen geen verkooppogingen meer, en hij wordt alsnog geboekt zodra de fills er zijn | toetsen `zonder_fills…`, `fills_later_gevonden…`; mutatie skip-weg rood |
| 6 | Kan HL niet gelezen worden, dan gebeurt er niets; na 3 cycli op rij volgt één Telegram-melding | `_beursstop_fout`; toetsen `leesfout…`, `mislukte_stop…` |
| 7 | Stops op de xyz-dex (HIP-3) worden door HL ondersteund en ccxt 4.5.56 bouwt ze voor hip3 op dezelfde manier als voor gewone perps | ccxt `hyperliquid.py:2078-2124` (`create_order_request`, `trigger: {isMarket, triggerPx, tpsl: sl}`, `a` = baseId incl. hip3-offset); HL-documentatie order-types; gids xyz ("Stop-loss and take-profit can be attached… on XYZ stock perps") |
| 8 | De refactor van `_close_or_trim` verandert het gedrag van software-exits niet | de bestaande 69 toetsen zijn ongewijzigd groen (`TestWinstbescherming` e.a.); `predeploy.py --snel` GROEN |

## Raakt deze KPI's / poorten
- H3 (verlies per experiment, via `realized_pnl_usd`), M4 (voorwaarde voor een kleinere server)

## Risico en terugdraaien
- Wat kan misgaan, en hoeveel staat er maximaal op het spel:
  - (a) Een stop vuurt bij een koersgat op een slechtere prijs dan −30%. Dat gebeurt ook zonder stop, en de slippagegrens is 10%.
  - (b) Een stop wordt geweigerd. Dan geldt de huidige toestand (alleen de software-stop), plus een melding.
  - (c) Een fout in de reconciliatie boekt een positie verkeerd. Begrensd tot het boek; HL-geld beweegt daardoor niet.
  - (d) Annuleren of plaatsen kost een paar API-aanroepen per cyclus (rate limit).
  - Maximaal op het spel: de ~$287 van de dip-koper, die ook nu al openstaat.
- Terugdraaien: `subsystem_beursstops_enabled=false`, of een hot-patch terug naar `501eb44`. Openstaande stops annuleren via HL.

## Wat ik zelf niet heb gecontroleerd
- **Live:** een echte testorder (een stop op 50%, direct weer annuleren) werd door mijn toestemmingslaag geblokkeerd. Of HL de order op xyz accepteert en wat `frontendOpenOrders` dan precies teruggeeft (`side`, `isTrigger`, `reduceOnly`, `sz` als string), komt uit de documentatie, niet uit een meting. De eerste cyclus na de deploy is dus de eerste echte meting. Die verifieer ik direct (open orders lezen), met de schakelaar als noodrem.
- Of `userFillsByTime` fills van de xyz-dex bevat met `dir: "Close Long"`: `scripts/dipkoper_resultaat.py` leest dezelfde bron en vindt de xyz-fills (zo werd het resultaat per naam op 21-09 bepaald), maar het veld `dir` heb ik niet live gezien.
- Isolated margin: geen invloed verwacht op een reduceOnly-trigger, niet gemeten.

---

## Audit

**A1 r1, controle-agent, 2026-10-06: GO-mits.** De code kan geen positie openen of vergroten, en dubbel sluiten kost geen geld. De voorwaarden:
- (1) De vlag `hl_positie_weg` bleef staan, ook als HL de positie weer toonde. Daarmee stonden de software-stops voorgoed uit, bijvoorbeeld bij een terugval naar de hoofdwallet.
- (2) Fills van een eerdere ronde in dezelfde naam konden in de boeking terechtkomen. Live gezien bij ORCL: een sluiting 23 minuten vóór de huidige opening.
- (3) Een mislukte annulering telde niet als fout, en er werd toch een nieuwe stop gezet.
- (4) Een fout in de reconciliatie sloeg het software-beheer over.
- (5) Het claimblad noemde 15 nieuwe toetsen, het waren er 14; de schakelaar dekt alleen de sync.

Veldnamen live gemeten: `clearinghouseState` (dex xyz) geeft `coin "xyz:..."`, en `userFillsByTime` zonder dex bevat de xyz-fills met `dir` "Close Long". De velden van een trigger-order in `frontendOpenOrders` zijn nog niet gemeten.

Na de deploy controleren: 6 stops (side A, isTrigger, reduceOnly, sz = szi, triggerPx ≈ 0,70 × aankoopprijs), en de tweede cyclus mag niets vervangen.

## Reactie bouwer
- (1) Opgelost. De vlag gaat pas aan na **twee** uitlezingen op rij zonder positie. Hij verdwijnt (met een melding) zodra HL de positie weer toont. Daarnaast werkt alles alleen nog op een self-custody-wallet (`_hl_account`), zodat de terugval naar de hoofdwallet niets doet. Toetsen: `vlag_verdwijnt…` (inclusief een software-verkoop bij −27,8% daarna) en `niet_op_de_hoofdwallet`.
- (2) Opgelost. `_sluitkoers` telt alleen fills met `time ≥ opened_at` van die positie. Is `opened_at` onleesbaar, dan wordt er niet geboekt. Toetsen: `sluiting_van_een_eerdere_ronde…` (ORCL-geval) en `onleesbare_opening…`.
- (3) Opgelost. Een nieuwe stop komt er alleen als alle annuleringen gelukt zijn; anders telt het als fout. Toets: `mislukte_annulering…`.
- (4) Opgelost. Reconciliatie en sync draaien in `run_cycle` elk in een eigen try/except. Toets: `fout_in_reconciliatie…`.
- (5) Gecorrigeerd. Er zijn nu 20 beursstop-toetsen. De reconciliatie heeft **bewust geen schakelaar**: ze boekt alleen wat HL echt sloot (ook bij handwerk) en zet zelf nooit een order.
- Mutatietoets: 6 van de 7 fixes maken de toetsen rood als je ze terugdraait. De zevende (`geopend is not None`) blijft groen, omdat het startmoment dan ook ontbreekt en er dus geen fill is. De uitkomst is getoetst; het pad zelf is dubbel gedekt.

**A1 r2, 2026-10-06: GO.** Alle vijf de punten zijn opgelost en hebben een toets. Klein punt 1 (beursstops vielen stil uit zonder eigen wallet) is verwerkt: er wordt nu geteld en gemeld. Klein punt 2 (gemengde prijs bij scheefgroei tussen boek en HL) staat genoteerd en raakt alleen het boek.
