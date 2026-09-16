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
- Daarna: treasury ≈ 0,00047 ETH (≈ 120 transacties boven de blokkeergrens), hoofdwallet ≈ 0,00015 ETH (≈ 88 bridge-transacties à 1,7e-06).
- Kosten van de overboeking zelf: ~$0,01.
- Beide potjes blijven in hetzelfde vermogen; **geen** stroomboeking nodig (gas is kosten, geen verplaatsing tussen potjes — zie ook de vraag hieronder).

## Risico en terugdraaien
- **Grootste risico's:**
  - Een verkeerde sleutel tekent voor een ander account. De bovengrens is het vangnet: hooguit 0,001 ETH kan ooit bewegen via dit pad.
  - Een kale overboeking heeft geen dry-run; `_simulate_tx` kent geen `value`. De saldo-controle en de vaste bestemming zijn de vervanging.
  - `data="0x"` bij een EOA-bestemming: standaard, maar dit project heeft nog nooit een waarde-transactie gestuurd.
- **Terugdraaien:** niet mogelijk (on-chain), wel verwaarloosbaar van omvang. De code terugdraaien kan met `git revert`.

## Wat ik zelf niet heb gecontroleerd
- Of `eth_account` bij `data="0x"` en `value>0` op Arbitrum precies deze transactie bouwt — niet live geprobeerd.
- Of 0,00015 ETH op de hoofdwallet genoeg blijft voor een HL-bridge in een duurdere gasperiode (gemeten bij 0,1 gwei op mainnet; Arbitrum-gas fluctueert minder, maar ik heb geen piekmeting).
- Of gas als "kosten" in de KPI's hoort (H1 telt `total_cost_usd` uit `cost_log.json`; on-chain gas zit daar niet in). Dat is een meetvraag, geen blokkade voor deze beweging.
