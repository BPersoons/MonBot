# Claimblad — passieve detectie van gestrand rebalance-geld (Check 25)

*Datum: 2026-09-16 · Poort: **A1** (code die geld raakt — hier alleen meldend) · Aanleiding: jouw STOP op `3e6f184` en de aanbeveling in dat rapport*

> Voor de controle-agent. Dit is de "melding zonder actie" die je zelf voorstelde als veilige eerste stap, nu het automatische pad is teruggetrokken.

## Wat er verandert
- Bestanden: `agents/swarm_monitor.py` (Check 25 + registratie), `tests/test_treasury_manual_withdrawal.py`.
- **Productie-impact vandaag:** geen melding. De enige kandidaat op de VM is `TRR_20260723_1501` (55 dagen oud) en die valt buiten de leeftijdsgrens; bovendien is de wallet $0,00.

## Waarom passief
De vorige poging stuurde gestrand geld automatisch naar HL en kreeg **STOP**: de detectie had geen tijdsgrens, matchte een dood record van 55 dagen oud, zou daarmee vers geld van een ander potje claimen, en de blokkade die erbij hoorde kon kasbeheer permanent bevriezen. Deze versie doet **niets** met geld: ze meldt, en laat de beslissing aan een mens.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | De check onderneemt geen enkele actie: geen voorstel, geen statuswijziging, geen transactie | `_check_gestrand_rebalance_geld` schrijft niets en roept alleen `_send_telegram` en `logger` aan |
| 2 | Een dood record meldt niet | Leeftijdsgrens `GESTRAND_MAX_DAGEN = 14`; `test_monitor_zwijgt_bij_leeg_wallet_en_bij_een_oud_record` gebruikt precies het echte geval (55 dagen, wallet $1.600) |
| 3 | Onder $100 wordt niet gemeld | `GESTRAND_MIN_USD`; onder dat bedrag kan niets anders het geld wegvegen (`generate_proposals` deployt pas vanaf `_MIN_DEPLOY_USD`) |
| 4 | Geen meldingsregen | Cooldown 12u op `_sent_alerts`, zelfde patroon als Check 14; getoetst met een tweede ronde direct erna |
| 5 | De tekst claimt niet meer dan hij weet | De melding zegt letterlijk dat het saldo ook een andere herkomst kan hebben en dat kasbeheer er zelf niets mee doet; de toets controleert die zinsnede |
| 6 | Een onleesbaar wallet-saldo meldt niet (en crasht niet) | `try/except` rond de RPC-aanroep, `_safe_check` eromheen |
| 7 | De toetsen bijten | Mutaties: leeftijdsgrens uit → oud-record-toets rood; bedragsgrens op 0 → leeg-wallet-toets rood; cooldown op 0 → herhalingstoets rood |

## Raakt deze KPI's / poorten
- Geen KPI direct. Vult het detectiegat dat ontstond door de terugtrekking (H4-gedachte: verlies snel zien), vooruitlopend op de herbouw met de zes voorwaarden.

## Risico en terugdraaien
- **Grootste risico's:**
  - Vals alarm: geld op de wallet kan van een switch of een storting zijn. Daarom de slag om de arm in de tekst — maar een mens kan hem alsnog verkeerd lezen en $267 naar HL bridgen die daar niet hoort.
  - De leeftijdsgrens van 14 dagen is een keuze: strandt er geld en kijkt niemand drie weken, dan zwijgt de check daarna. Hij logt dat wel (debug).
  - De check leest alleen de treasury-wallet, niet het vault-Arb-adres — bekende beperking, staat als voorwaarde 5 voor de herbouw.
- **Terugdraaien:** `git revert` + deploy; de check heeft geen state.

## Wat ik zelf niet heb gecontroleerd (vóór de audit)
- Of de melding in Telegram leesbaar rendert (backticks rond het voorstel-id, underscores in de id).
- Of `_sent_alerts` een herstart overleeft (Check 14 heeft hetzelfde gedrag; bij een herstart kan de melding één keer extra komen).
- Of 14 dagen de juiste grens is — gekozen omdat een rebalance normaal binnen 30 minuten rond is.

---

## Audit
**Oordeel: GO-mits** met vier voorwaarden vóór deploy. De kern van de kritiek was fataal voor mijn ontwerp en volledig terecht.

**Correctie op mijn ontwerp (bevinding 1).** Mijn drempel van $100 op het wallet-saldo maakte de check blind voor precies de faalmodus die hij moest dekken. Bewijs uit productie: op 23-07 stond `TRP_20260723_1447_excess` op DEPLOYED om 15:14:28, **veertien seconden vóór** `aave_withdrawn_at` 15:14:42 van de rebalance die daarna faalde; op 18-07 zat er 4 milliseconden tussen. Het geld was dus al door de concurrerende deploy naar Aave teruggeduwd en de wallet was leeg — de check zou in **beide** echte incidenten hebben gezwegen.

| # | Bevinding | Reactie |
|---|---|---|
| 1 | De check zou geen van beide echte incidenten hebben gezien | **Herontworpen.** Melden gebeurt nu op de **gebeurtenis** (REBALANCE → FAILED mét `aave_withdrawn_at`, binnen 14 dagen), ongeacht het saldo. Het wallet-saldo is een **veld** in de melding geworden. Toets: `test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is` (saldo $0,00 → meldt) |
| 2 | Stille nul: `get_arb_usdc_balance` geeft 0.0 bij een RPC-storing | **Opgelost.** De check doet zijn eigen `_rpc`-aanroep en meldt letterlijk "onmeetbaar" als die faalt. Toets: `test_monitor_onderscheidt_nul_van_onmeetbaar` |
| 3 | Cooldown gestempeld vóór de melding → 12u stilte bij één format-fout | **Opgelost.** Stempelen ná `_send_telegram`, en de logregel gebruikt nu dezelfde defensieve `float(... or 0)` |
| 4 | `max` op leeftijd koos het verkeerde record; bedrag hoorde niet bij het saldo | **Opgelost.** `min` op leeftijd (de verse stranding), het aantal kandidaten in de tekst, en de zin "hoogstens $X hoort bij dít voorstel". Toets met twee kandidaten controleert dat het oude bedrag níét in de melding staat |
| 5 | Geld staat óók op de wallet bij BRIDGE_BACK_NEEDED zonder sleutel | **Bekende beperking**, hieronder vastgelegd; Check 14 vangt die statussen na 6u |
| 6 | "logt wel (debug)" is onzichtbaar bij `level=INFO` | **Opgelost.** Records ouder dan 14 dagen geven nu een INFO-regel met id en leeftijd |
| 7 | M4-meetklok klopt niet zodra je deployt | **Opgelost bij de deploy zelf**: de klok gaat op het werkelijke herstartmoment. Ook een hot-patch herstart de container, dus dat maakt geen verschil |
| gemiste kans | Een regressietoets op de historische samenloop is meer waard dan de melding | **Gebouwd.** `test_de_twee_echte_botsingen_van_juli_kunnen_niet_meer` speelt beide incidenten na op de echte statussen |

**Antwoorden op de open vragen:**
- *Waarom het saldo als drempel?* Een denkfout: ik redeneerde vanuit "geld dat blijft liggen" in plaats van vanuit de gebeurtenis. Het is nu een veld.
- *Stilte na 14 dagen?* Niet meer stil: oudere records geven een INFO-regel. Een wekelijkse samenvatting voegt daar weinig aan toe zolang er één dood record is.

**Bekende beperkingen (bewust, staan op de lijst voor de herbouw):**
- Alleen de treasury-wallet wordt gelezen, niet het vault-Arb-adres.
- `BRIDGE_BACK_NEEDED`/`REBALANCING`/`BRIDGING_TO_HL` zonder statuswijziging vallen buiten deze check; Check 14 meldt die na 6 uur, maar zonder te zeggen dat er geld op de wallet staat.
- Er is nog steeds **geen automatisch herstel** — alleen een melding.
