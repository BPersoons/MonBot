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
| 1 | De check zou geen van beide echte incidenten hebben gezien | **Herontworpen** (en let op de correctie hieronder: het gaat om één incident, niet twee). Melden gebeurt nu op de **gebeurtenis** (REBALANCE → FAILED mét `aave_withdrawn_at`, binnen 14 dagen), ongeacht het saldo. Het wallet-saldo is een **veld** in de melding geworden. Toets: `test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is` (saldo $0,00 → meldt) |
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

## Hertoets (ronde 2)
**Oordeel: GO-mits** — drie blokkerende voorwaarden, plus vijf punten om te corrigeren. De herontwerp-kern (melden op de gebeurtenis) werd bevestigd met een replay op de echte records.

**Correctie: het gaat om één incident, niet twee.** `TRR_20260718_1852` is op 18-07 om 19:31 **COMPLETED** geworden — dat geld kwam dus gewoon aan. Alleen 23-07 zou een melding hebben opgeleverd. Mijn commit-tekst en claimblad suggereerden dekking van twee gevallen; dat klopt niet.

| # | Voorwaarde / bevinding | Reactie |
|---|---|---|
| V1 | De melding kan een mens de verkeerde kant op sturen: geld kan op het **vault-Arb-adres** staan (mislukte bridge-stap 2), of tóch op HL zijn aangekomen (verlopen bevestiging) | **Opgelost.** De melding leest nu **beide** adressen (treasury-wallet én vault-Arb-adres, uit `HL_VAULT_ADDRESS`) en zegt "de bridge naar HL is **niet bevestigd**" in plaats van "strandde vóór de bridge", met de drie mogelijkheden expliciet. Toetsen: `test_monitor_meldt_beide_adressen`, plus de tekstcontroles in `test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is` |
| V2 | 14 meldingen voor één gebeurtenis; ook nog ná de vervangende geslaagde rebalance | **Opgelost, twee kanten.** (a) Een latere **COMPLETED** rebalance sluit het geval af (INFO, geen melding). (b) Hooguit **twee** meldingen per voorstel: de tweede pas na 24u, met kop "herinnering", daarna alleen INFO. Toetsen: `test_monitor_zwijgt_bij_oud_scheef_en_opgelost`, `test_monitor_kiest_de_meest_recente_en_meldt_hoogstens_twee_keer` |
| V3 | Negatieve leeftijd mogelijk ("-4.8 dagen geleden"), en zo'n record wint altijd de `min()` | **Opgelost.** `0 <= dagen <= 14`; toekomstige stempels krijgen een eigen INFO-regel |
| 1 | "Stempelen ná de melding" had geen effect: `_send_telegram` slikt alles in | **Echt opgelost.** `_send_telegram` geeft nu `True`/`False` terug (alle takken), en de check stempelt alleen bij `True`. Toets: `test_mislukte_melding_geeft_geen_stilte` (twee rondes, twee pogingen) |
| 2 | Claim "beide echte incidenten" klopt niet | **Gecorrigeerd** — zie hierboven |
| 3 | Sleutel per id niet getoetst; voorstel zonder id deelt `…:None` | **Opgelost.** Toets `test_twee_verschillende_strandingen_melden_allebei`; zonder id valt de sleutel terug op `aave_withdrawn_at` in plaats van op `None` |
| 4 | De regressietoets toetste alleen de constante | **Opgelost.** Hij loopt nu door `_check_hl_excess` met een rebalance in elk van de vier onderweg-statussen en eist dat er géén DEPLOY_YIELD bij komt — precies het pad waarlangs `TRP_20260723_1447_excess` ontstond |
| 5 | Dubbele `balanceOf`-codering | **Opgelost.** Gebruikt `_encode_balance_of` en `_USDC_DECIMALS` uit de executor |

**Antwoorden op de open vragen:**
- *Waarom 24u cooldown en 14 meldingen?* Dat was geen keuze maar een gat: er zat geen bovengrens op. Nu twee meldingen, en afsluiten zodra een latere rebalance slaagt.
- *Vault-Arb-adres meelezen?* Ja, nu al — het was juist het adres waar het geld bij een mislukte stap 2 blijft staan.

## Hertoets (ronde 3)
**Oordeel: GO-mits** — V1, V2 en V3 vervuld (alle vier mutaties van de agent maken een toets rood), met drie kleine voorwaarden en één belangrijke bevinding.

**De belangrijke bevinding, en waarom mijn "opgelost" te sterk was.** Een latere geslaagde rebalance zegt niets over geld op de **treasury-wallet**: de bridge leegt alleen het **vault**-adres (`_bridge_usdc_to_hl` verplaatst stap 1 alleen het bedrag van dat ene voorstel). Geld dat op de treasury-wallet blijft staan wordt opgeruimd door het deploy-pad, en dat vuurt pas vanaf $100. Onder dat bedrag ruimt niets het op — en mijn regel zette de melding dan uit. Replay van de agent: stranding + een andere rebalance die 3 minuten later slaagt → **0 meldingen in 3 dagen**.

| # | Voorwaarde / bevinding | Reactie |
|---|---|---|
| 1 | "Opgelost" is een uitspraak over de pijplijn, niet over het geld | **Opgelost.** Een geval sluit alleen als het **gemeten** saldo (treasury + vault) onder het bridgeminimum van $10 ligt; is het hoger of onmeetbaar, dan blijft hij melden. De INFO-regel noemt in beide gevallen de gemeten saldi. Toets: `test_opgelost_telt_alleen_als_er_ook_niets_meer_staat` ($60 → blijft melden, $0 → stil) |
| 2 | De terugval op `HL_WALLET_ADDRESS` las de **agent**-wallet en noemde dat vault-adres | **Opgelost.** Alleen `HL_VAULT_ADDRESS` (met secrets-terugval), anders "niet gemeten". Beide adressen staan nu met hun laatste vier tekens in de melding |
| 3 | Voorstel zonder id gaf letterlijk `` `None` haalde $267 uit Aave `` | **Opgelost.** `voorstel zonder id`; toets `test_voorstel_zonder_id_meldt_geen_none` |
| 4 | Geen backoff bij een kapotte Telegram: ~4.000 pogingen en 8.000 `eth_call`s over 14 dagen | **Opgelost.** Na een mislukte melding hooguit 1× per uur opnieuw — zonder te stempelen, dus de melding blijft openstaan. Toets: drie rondes, twee pogingen |
| 5 | `CLAUDE.md` zegt "24 checks" | **Bijgewerkt** naar 25 |

**Antwoorden op de open vragen:**
- *Waarom sloot een geslaagde rebalance het geval af?* Een aanname over de pijplijn die ik niet aan het geld had getoetst. Nu is het saldo doorslaggevend.
- *Een afsluitende melding bij "opgelost"?* Nee — dat is een tweede melding voor een niet-gebeurtenis. Het sluiten staat met de gemeten saldi in de INFO-regel; Telegram blijft voor dingen die actie vragen.

**Bekende beperkingen (bewust, staan op de lijst voor de herbouw):**
- Alleen de treasury-wallet wordt gelezen, niet het vault-Arb-adres.
- `BRIDGE_BACK_NEEDED`/`REBALANCING`/`BRIDGING_TO_HL` zonder statuswijziging vallen buiten deze check; Check 14 meldt die na 6 uur, maar zonder te zeggen dat er geld op de wallet staat.
- Er is nog steeds **geen automatisch herstel** — alleen een melding.
