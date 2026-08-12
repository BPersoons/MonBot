# Uitstap naar euro's — van USDC naar DeGiro

*Opgesteld 2026-08-12. De ontbrekende schakel: al het vermogen zit in crypto, terwijl
het plan 40% in een wereldindexfonds bij DeGiro wil.*

Twee dingen wachten hierop:

1. **Wereldindexfonds** — 40% van het plan, staat op nul
2. **Thema-ETF's** — instrumenten al gekozen (ISIN's vastgelegd 2026-07-30), nooit gekocht

## Wat er al kan (code, geautomatiseerd)

De crypto-kant is volledig gedekt door bestaande functies in `utils/treasury_executor.py`:

| Stap | Functie | Status |
|---|---|---|
| USDC uit Aave halen | `withdraw_aave_to_wallet()` | ✅ bestaat, is gebruikt |
| USDC van Hyperliquid halen | `_attempt_hl_withdrawal()` | ✅ bestaat |
| USDC naar een willekeurig adres sturen | `_encode_erc20_transfer()` + `_send_tx()` | ✅ bestaat |

## Wat ontbreekt (handmatig, eenmalig)

Alleen de **laatste meter**: een rekening die USDC aanneemt en euro's uitbetaalt.

```
Aave/Hyperliquid  →  treasury-wallet (Arbitrum)  →  exchange  →  euro's  →  bank  →  DeGiro
        ✅ code            ✅ code                    ❌ ontbreekt
```

## De route

| # | Stap | Wie | Duur | Kosten |
|---|---|---|---|---|
| 1 | Rekening bij een EUR-exchange, KYC | Bart | 1-3 dagen als er nog geen is | — |
| 2 | Stortadres (Arbitrum USDC) opvragen | Bart | minuten | — |
| 3 | USDC uit Aave naar treasury-wallet | code | minuten | ~$0,10 gas |
| 4 | USDC naar het stortadres | code | minuten | ~$0,10 gas |
| 5 | USDC verkopen voor EUR | Bart | minuten | ~0,15-0,25% |
| 6 | SEPA naar je bank | Bart | 1 werkdag | meestal gratis |
| 7 | Bank → DeGiro | Bart | 1 werkdag | gratis |

**Totale kosten op ~$1.050: ongeveer $3-5, dus 0,3-0,5%.** Ruim onder de 1% waar
het plan voor waarschuwt bij kleine transacties.

**Belangrijk:** stuur op **Arbitrum**, niet op Ethereum mainnet. Controleer dat de
exchange USDC op Arbitrum accepteert — een verkeerd netwerk betekent verlies.
Stuur altijd eerst een testbedrag van ~$20 en wacht op bijschrijving.

## Welke exchange

| | Voordeel | Nadeel |
|---|---|---|
| **Bitvavo** *(advies)* | Nederlands, euro's als basisvaluta, SEPA gratis en snel, lage tarieven | Kleiner dan de rest |
| Kraken | Sterke reputatie op beveiliging, ondersteunt Arbitrum | Iets duurder, EUR minder centraal |
| Coinbase | Bekendste, simpelste interface | Duurste van de drie |

Bitvavo omdat de hele keten in euro's blijft en SEPA gratis is; bij een bedrag van
~$1.000 tikt een half procent verschil meteen aan.

## Fiscaal

Box 3 belast vermogen op de peildatum, niet de winst. **USDC omwisselen naar euro's
is dus geen belastbaar moment** — het verandert alleen wat er op 1 januari op welke
rekening staat. Geen reden om de uitstap uit te stellen of te spreiden.

## Wat ik nodig heb om verder te gaan

1. **Bij welke exchange** — en of je daar al een rekening hebt
2. **Het Arbitrum-USDC-stortadres** zodra de rekening er is
3. **Het bedrag** — hangt af van de nog openstaande keuze over hoeveel BTC/ETH je
   wilt vasthouden (zie `docs/NAMEN.md` en `PLAN_2026-08.md`)

Stap 3 en 4 kan ik daarna uitvoeren; 1, 2, 5, 6 en 7 zijn onvermijdelijk handwerk.

## Waarom dit niet eerder is opgevallen

Het project is gebouwd als crypto-handelssysteem; alles bewoog binnen crypto en er
was nooit een reden om eruit te stappen. Het plan van augustus 2026 introduceerde
voor het eerst een bestemming buiten die wereld (een indexfonds bij een gewone
broker) zonder de route ernaartoe te beschrijven. Beide ETF-plannen — het
wereldindexfonds én de thema-ETF's — stonden daardoor stil op dezelfde ontbrekende
schakel, zonder dat dat ergens benoemd was.
