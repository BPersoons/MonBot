# Uitstap naar euro's — van USDC naar DeGiro

*Opgesteld 2026-08-12. De ontbrekende schakel: al het vermogen zit in crypto, terwijl
het plan 40% in een wereldindexfonds bij DeGiro wil.*

> ## 🧊 IN DE IJSKAST — herzien 2026-08-18
>
> Op 17 augustus was de keuze: uitstappen uit USDC om het wereldindexfonds te
> financieren. **Een dag later teruggedraaid, en om een goede reden:** er is ruim
> voldoende vers geld. Daarmee is deze hele route overbodig geworden voor dit doel.
>
> **De nieuwe opzet is twee potjes naast elkaar:** crypto/USDC blijft bij
> Hyperliquid en Aave, en DeGiro wordt gevuld met euro's van de bank. Geen
> conversie, geen extra rekening, geen KYC bij een derde partij — en, het
> belangrijkste, **geen onomkeerbaar risico**: de kans om USDC op het verkeerde
> netwerk te sturen bestaat niet meer als je die stap overslaat.
>
> **Rekenkundig verschil, voor de volledigheid.** Uitstappen zou $1.235 binnen
> hetzelfde totaal verschuiven. Vers geld moet ~€1.774 zijn om dezelfde 40% te
> halen, want **nieuw geld vergroot ook de noemer**: `X = 0,4 × (3.088 + X)`.
> Met ruim voldoende inleg is dat geen bezwaar.
>
> ### Wanneer dit document weer relevant wordt
>
> Niet voor het wereldindexfonds — wél zodra je **winst uit de crypto-kant naar de
> aandelenkant** wil verplaatsen, of andersom. Dan is dit de brug, en hij is al
> gebouwd en nagelopen: alle functies bestaan, de saldi zijn live uitgelezen (zie
> onderaan). Een brug die je bouwt wanneer je hem oversteekt.
>
> **Blijft staan als regel voor die dag:** eerst $20 als test, wachten op
> bijschrijving, dán de rest. En het stortadres is dat van een **crypto-exchange**
> op het **Arbitrum-netwerk**, nooit dat van DeGiro — die heeft alleen een IBAN.

Twee dingen wachten hierop:

1. **Wereldindexfonds** — 40% van het plan, staat op nul. Fonds gekozen:
   **WEBN**, ISIN `IE0003XJA0J9`, op **Tradegate** (zie `docs/KERN_ETF_KEUZE.md`)
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

Nog **één ding**, niet drie meer — het bedrag is beslist en de exchange is geadviseerd:

> **Het Arbitrum-USDC-stortadres van je exchange-rekening.**

⚠️ **Nadrukkelijk NIET bij DeGiro.** Dat is een effectenmakelaar: die heeft geen
crypto-stortadres, alleen een IBAN voor euro's. Deze vraag kwam op 2026-08-18 en
het is precies het soort misverstand dat onherstelbaar geld kost.

Wat er nodig is, is het stortadres van een **crypto-exchange** (Bitvavo
geadviseerd): rekening openen → KYC → "USDC storten" → **netwerk op Arbitrum
zetten** → het `0x…`-adres dat daar verschijnt. DeGiro komt pas drie stappen
later in beeld, en dan met een IBAN.

Hetzelfde adres op Ethereum-mainnet accepteert de storting niet en het geld is
dan weg. Daarom eerst $20, wachten op bijschrijving, dán de rest.

Dat is alles. Zodra dat er is, doe ik stap 3 en 4. Stap 1, 2, 5, 6 en 7 zijn
onvermijdelijk handwerk — een KYC-rekening openen en een SEPA-overboeking doen kan
en mag geen script voor je doen.

### De code is nagelopen (2026-08-17)

Niet aangenomen dat het werkt, maar gecontroleerd in de draaiende container. Alle
functies bestaan met de verwachte signatuur, en de saldi zijn live uitgelezen:

| Functie | Signatuur |
|---|---|
| `withdraw_aave_to_wallet` | `(amount_usd: float, private_key: str) -> str` |
| `_encode_erc20_transfer` | `(to: str, amount: int) -> str` |
| `_send_tx` | `(to: str, data: str, private_key: str, gas_limit: int) -> str` |
| `get_aave_balance` | `(wallet_address: str) -> float` |
| `get_arb_usdc_balance` | `(address: str) -> float` |

Treasury-wallet `0x4144e0b52247Ba1Cb06FF1E5fB6F817f330Ce4D3` — Aave $2.379,44,
losse USDC $0,00. Dat laatste is belangrijk: er staat niets klaar, dus stap 3 moet
echt eerst gebeuren.

### In twee transacties, niet één

**Eerst $20, wachten op bijschrijving, dán de rest.** Deze route is nog nooit
gelopen. Een verkeerd netwerk of een stortadres dat alleen Ethereum-mainnet
aanneemt betekent totaal verlies, en dat is niet te herstellen. $0,10 extra gas is
een verwaarloosbare prijs voor die zekerheid.

Dit is dezelfde regel die bij de dip-koper werkte: eerst klein aantonen, dan
schalen.

## Waarom dit niet eerder is opgevallen

Het project is gebouwd als crypto-handelssysteem; alles bewoog binnen crypto en er
was nooit een reden om eruit te stappen. Het plan van augustus 2026 introduceerde
voor het eerst een bestemming buiten die wereld (een indexfonds bij een gewone
broker) zonder de route ernaartoe te beschrijven. Beide ETF-plannen — het
wereldindexfonds én de thema-ETF's — stonden daardoor stil op dezelfde ontbrekende
schakel, zonder dat dat ergens benoemd was.
