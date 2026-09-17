# Claimblad — gas bijvullen tussen eigen wallets (ETH, ~$0,84)

*Datum: 2026-09-16 · Poorten: **A1** (code die geld raakt) én **A2** (kapitaalbeweging) · Aanleiding: M3 (Fluid) kan anders halverwege stilvallen*

> Voor de controle-agent. Dit is de eerste code in dit project die **waarde** verstuurt; alle andere transacties zijn contract-aanroepen met `value` 0. Beoordeel het navenant.

## Waarom
De treasury-wallet `0x4144…e4D3` heeft **0,000124 ETH**. Een transactie kost ~3,1e-06 ETH (gemeten aan echte receipts), maar `_check_eth_gas` weigert al onder `_MIN_ETH_FOR_GAS` = 0,0001 — de bruikbare marge is dus ~7 transacties. Een Fluid-switch kost er 3 (opnemen, approve, storten). Eén switch past; daarna blokkeert de gasbewaking, mogelijk halverwege een beweging.

De hoofdwallet `0x92D4…F445` heeft **0,000497 ETH** op Arbitrum, en de swarm heeft daarvan de sleutel (`HL_VAULT_PRIVATE_KEY`). Een interne overboeking lost het op **zonder nieuw geld**. Bart vroeg hier expliciet om ("kun je zelf geen gas regelen?"); mijn eerdere verzoek om ~$7 is daarmee ingetrokken.

Mainnet is gemeten en bewust niet gebruikt: de hoofdwallet heeft daar 0,001329 ETH ($3,21), maar overbruggen vergt een bridge-interactie én mainnet-RPC-toegang die de VM niet heeft.

## Wat er verandert
- `utils/treasury_executor.py`: `_send_tx` krijgt een optionele `value` (standaard 0 — bestaand gedrag ongewijzigd); nieuwe `stuur_eth_voor_gas()`; en de adres-terugval van de opname-client (`HL_VAULT_ADDRESS or HL_WALLET_ADDRESS`) is weg.
- `tests/test_gas_bijvullen.py` (nieuw).
- **Geen automatisering:** `stuur_eth_voor_gas` wordt door geen enkele agent aangeroepen. Hij draait één keer, met de hand, ná jouw GO.

## Beweringen
| # | Bewering | Bewijs |
|---|---|---|
| 1 | Bestaande transacties veranderen niet | `value: int = 0` als default; `test_send_tx_stuurt_standaard_geen_waarde` controleert de ondertekende transactie |
| 2 | Hooguit 0,001 ETH per keer | `_MAX_GAS_TOPUP_ETH`; toets weigert 0,01 én 0 én negatief. Mutatie (grens op 1e9) maakt de toets rood |
| 3 | Alleen naar de treasury-wallet | Vergelijking met `_TREASURY_WALLET`; zelfs de dip-koper-wallet wordt geweigerd |
| 4 | De afzender houdt zelf gas over | Saldo-controle met `_MIN_ETH_FOR_GAS` als marge; 0,00045 vanaf 0,000497 wordt geweigerd, 0,00035 niet. Mutatie (marge op 0) maakt de toets rood |
| 5 | Dit is het enige pad dat waarde verstuurt | `grep '"value"'` in `treasury_executor.py`: alleen `_send_tx` en het EIP-2612-permit-bericht (geen transactiewaarde) |
| 6 | De opname-client kan niet meer op de verkeerde rekening uitkomen | `HL_WALLET_ADDRESS` is de **agent**-wallet, een ander account; de terugval is weg, ontbreekt het vault-adres dan geeft de functie `None` zoals ze al deed |
| 7 | Pre-deploy-poort groen | `python scripts/predeploy.py` |

## De voorgenomen beweging (A2)
- **0,00035 ETH** (~$0,84) van `0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445` naar `0x4144e0b52247Ba1Cb06FF1E5fB6F817f330Ce4D3`, op **Arbitrum**.
- Daarna: treasury ≈ 0,00047 ETH, hoofdwallet ≈ 0,000147 ETH.
- **Gecorrigeerd na de audit** (mijn eerste cijfers waren te gunstig, doordat ik de blokkeergrens bij de treasury wél en bij de hoofdwallet níét aftrok, en met een te lage kostenaanname rekende):
  - treasury: (0,00047 − 0,0001) / 3,4–3,9e-06 = **95–111 transacties** (niet 120);
  - hoofdwallet: (0,000147 − 0,0001) / 1,7e-06 = **~27 bridge-transacties** (niet 88).
  - Kosten uit echte receipts in `treasury_state.json`: bridge 1,7e-06 ETH, Aave-acties 3,4–3,9e-06 ETH. Mijn eerdere 3,1e-06 was 15–20% te laag.
- 27 bridges is ruim voor het gebruikspatroon (alleen bij REBALANCE en BRIDGE_BACK_NEEDED), maar het verschil hoorde niet in een beslisstuk te staan.
- Kosten van de overboeking zelf: ~$0,01.
- Beide potjes blijven in hetzelfde vermogen; **geen** stroomboeking nodig (gas is kosten, geen verplaatsing tussen potjes — zie ook de vraag hieronder).

## Risico en terugdraaien
- **Grootste risico's:**
  - Een verkeerde sleutel tekent voor een ander account. De bovengrens is het vangnet: hooguit 0,001 ETH kan ooit bewegen via dit pad.
  - Een kale overboeking heeft geen dry-run; `_simulate_tx` kent geen `value`. De saldo-controle en de vaste bestemming zijn de vervanging.
  - `data="0x"` bij een EOA-bestemming: standaard, maar dit project heeft nog nooit een waarde-transactie gestuurd.
- **Terugdraaien:** niet mogelijk (on-chain), wel verwaarloosbaar van omvang. De code terugdraaien kan met `git revert`.

## Wat ik zelf niet heb gecontroleerd (vóór de audit)
- Of `eth_account` bij `data="0x"` en `value>0` op Arbitrum precies deze transactie bouwt — niet live geprobeerd.
- Of 0,00015 ETH op de hoofdwallet genoeg blijft voor een HL-bridge in een duurdere gasperiode (gemeten bij 0,1 gwei op mainnet; Arbitrum-gas fluctueert minder, maar ik heb geen piekmeting).
- Of gas als "kosten" in de KPI's hoort (H1 telt `total_cost_usd` uit `cost_log.json`; on-chain gas zit daar niet in). Dat is een meetvraag, geen blokkade voor deze beweging.

---

## Audit
**Oordeel: A1 STOP · A2 geblokkeerd tot A1 hersteld is.** Twee blokkerende fouten, allebei in code die ik nieuw schreef, en allebei hard gemeten.

**Bevinding 1 — 21.000 gas is een L1-getal.** Op Arbitrum zitten de L1-posterkosten in de intrinsieke kosten. Gemeten in de container: `eth_estimateGas` voor exact deze overboeking geeft **22.599**, en met 21.000 weigert de keten hem (`intrinsic gas too low`). Mijn toets legde dat foute getal ook nog eens vast (`assert gas == 21_000`), dus hij bewaakte precies de fout.
**Opgelost:** de gaslimiet komt uit `_estimate_gas` **mét** `value` (zonder waarde schat je een andere transactie), met een ondergrens van 40.000. De toets pint die ondergrens nu **hard** (`>= 40_000`) in plaats van via de constante — anders verlaagt een mutatie de grens én de verwachting tegelijk.

**Bevinding 2 — geen receipt-controle.** Ik gaf de hash terug zonder op status `0x1` te wachten, terwijl élk ander waardepad in dat bestand dat wél doet. Een mislukte overboeking (status `0x0`, gas verbrand) zou er dus uitzien als geslaagd — en dan valt de Fluid-switch alsnog halverwege stil, precies het scenario dat deze actie moest voorkomen. Dit is de "vlag vóór de order slaagt"-valkuil in een nieuwe jas.
**Opgelost:** `_wait_receipt` + status `0x1` afgedwongen, anders `RuntimeError`; daarna hermeet de functie het ontvangerssaldo en logt dat. Toetsen: status `0x0` én "geen receipt" moeten allebei luid falen.

| # | Bevinding | Reactie |
|---|---|---|
| 3 | Mijn rekensom trok de blokkeergrens bij de treasury wél af en bij de hoofdwallet niet; kosten 15–20% te laag | **Gecorrigeerd** hierboven: ~27 bridge-transacties voor de hoofdwallet, 95–111 voor de treasury |
| 4 | Geen rail op de afzender — elke sleutel met genoeg saldo werd geaccepteerd | **Opgelost.** De afzender moet het vault-adres zijn; is dat adres onbekend, dan weigert hij. Toetsen voor beide |
| 5 | Het vault-**adres** had één ontsnappingsroute minder dan de vault-**sleutel** (env → SDK, zonder REST) | **Opgelost.** `_vault_adres()` doet env → SDK → REST en wordt ook door de opname-client gebruikt |
| deploy | Via de image, niet via `docker cp` | **Akkoord.** Het wordt een full deploy; daarmee gaat Check 25 (nu alleen hot-patch) de image in en overleeft hij een compose-recreate |

**Antwoorden op de open vragen:**
- *Waar kwam 3,1e-06 vandaan?* Uit mijn eigen meting van zes receipts, maar dat was een **gemiddelde over twee soorten transacties** — inclusief de goedkope bridge (1,7e-06) — dat ik presenteerde als "per treasury-transactie". De Aave-acties alleen kosten 3,4–3,9e-06. Een gemiddelde over ongelijksoortige dingen, precies de definitiefout die dit project vaker heeft gekost.
- *Hash of receipt?* Receipt, plus hermeting van het ontvangerssaldo — de functie doet dat nu zelf, dus het hangt niet aan mijn discipline op het moment van uitvoeren.
- *On-chain gas ontbreekt in H1?* Akkoord om dat als **bekend gat** te noteren (~$0,40/maand op ~$160/jaar). Meetcode bouwen voor dat bedrag is niet in verhouding; het hoort wel eerlijk in H5 te staan, niet stilzwijgend te ontbreken.

**Mutatietoetsen:** bovengrens, gasmarge, gaslimiet-ondergrens en de receipt-controle maken elk een toets rood (de laatste zeven tegelijk).

## Hertoets (ronde 2) — 2026-09-17
**Oordeel: A1 GO-mits · A2 GO-mits.** Beide blokkerende punten live nagemeten en in orde: `eth_estimateGas` mét waarde geeft nu 21.337, de nieuwe `_estimate_gas` levert 40.000 (ondergrens wint), 21.000 wordt door de keten geweigerd en 40.000 gaat door. De opgebouwde transactie is ontleed (EIP-155, chainId 42161, value 3,5e14, lege data). **0,00035 ETH is het juiste bedrag:** bij het verbruik van de laatste 90 dagen heeft de vault daarna gas voor ~14 maanden en de treasury voor ~12.

| # | Bevinding | Reactie |
|---|---|---|
| 1 | **`_vault_adres` hing aan geen enkele toets** — drie mutaties (terugval op de agent-wallet, REST-weg weg, terugval in de opname-client) bleven groen in alle 330 toetsen, omdat mijn toets de functie in zijn geheel verving | **Opgelost.** Vier directe toetsen: nooit terugvallen op `HL_WALLET_ADDRESS`, REST als laatste weg, SDK vóór REST, en geen opname-client als er een sleutel is maar geen vault-adres. Alle drie de mutaties maken nu een toets rood. Voor de derde keer in twee dagen dezelfde les: een fix zonder toets die rood wordt bij terugdraaien, is geen fix |
| 2 | Een geslaagde overboeking kon als fout eindigen (hermeting buiten `try`), en "geen receipt" heette "mislukt" | **Opgelost.** Hermeting in `try/except`; zonder receipt heet het nu **ONBEKEND** met "niet opnieuw starten" erbij. Twee toetsen |
| 3 | De monitor zocht het vault-adres zelf op, zonder de REST-weg | **Opgelost.** Check 25 gebruikt nu `_vault_adres` uit kasbeheer — één definitie. Het toetsbestand van de monitor patcht de REST-weg standaard weg, zodat geen toets ooit het echte secret ophaalt |
| 4 | Uitvoerscript: geen nameting na een fout; vals alarm als kasbeheer tegelijk iets doet | **Opgelost.** Nameting in `finally`, en het script weigert te starten zolang er een voorstel niet in een eindstatus staat |
| 5 | Kosten te ruim geschat | **Gecorrigeerd** in het plan: gemeten ~$0,08/maand (niet $0,40), een kale overboeking ~$0,001 (niet $0,01) |
| pre-mortem | Een REBALANCE controleert het vault-gas pas bij de bridge, ná de Aave-opname | **Genoteerd voor M3**, samen met de gemiste kans hieronder |
| gemiste kans | Geen vroege waarschuwing op het ETH-saldo van beide wallets | **Genoteerd voor M3**: een monitorcheck onder ~0,00015 ETH. Niet in deze ronde — dat is nieuwe code met een eigen audit |

**Antwoord op de open vraag** (eerder ETH van 0x92D4 naar de treasury?): dat weet ik niet. De daling van ~0,0005 ETH op de vault tussen dag −120 en −90, terwijl de treasury gevuld raakte, wijst er wel op. "Eerste waarde-transactie" klopt dus alleen voor **de code**, niet voor de wallets.

**Uitvoering:** pas ná de M4-meting van 17-09 18:10 UTC. De functie zit niet in de draaiende image, en elke herstart zet de 24-uursklok terug.
