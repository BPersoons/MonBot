# Uitstap naar euro's — van USDC naar DeGiro

*Opgesteld 2026-08-12. De ontbrekende schakel: al het vermogen zit in crypto, terwijl
het plan 40% in een wereldindexfonds bij DeGiro wil.*

> ## ✅ BESLIST 2026-08-17 — dit gaat door
>
> Bart heeft gekozen voor **uitstappen uit USDC**. Daarmee **vervalt** de eerdere
> keuze dat USDC bij Hyperliquid het eindstation is (vastgelegd 2026-08-12). Dat was
> geen vergissing maar een verschuiving: zolang er geen bestemming buiten crypto was,
> was USDC een prima eindpunt. Nu is er één.
>
> **Het bedrag: $1.235 (≈ €1.065).** Dat is 40% van de NAV van $3.088 (gemeten
> 2026-08-17), en het komt **volledig uit Aave** — niet uit de dip-koper en niet uit
> het crypto-vasthoud-potje. Die twee zijn werkende onderdelen met eigen budget en
> blijven staan; de dip-koper heeft net een voorsprong van 9pp op de wereldindex
> laten zien en het crypto-potje staat op 1 van 8 geplande tranches.
>
> | | nu | na de uitstap |
> |---|---|---|
> | Aave (veilig) | $2.379 · 77% | $1.144 · 37% |
> | Hyperliquid USDC | $270 · 9% | $270 · 9% |
> | **Wereldindexfonds** | **$0 · 0%** | **$1.235 · 40%** |
> | Dip-koper | $264 · 9% | $264 · 9% |
> | Crypto vasthouden | $174 · 6% | $174 · 6% |
>
> Veilig komt daarmee op 46% (Aave + Hyperliquid) in plaats van de 60% die Fase A
> noemt. Het verschil zit in de twee experimenten, die in Fase A's tweepotjes-beeld
> niet voorkomen. Dat is een bewuste afwijking, geen rekenfout: ze afbouwen om een
> percentage te halen zou werkende onderdelen slopen voor een getal.
>
> **Totale kosten: ~$4,40 op $1.235 = 0,35%.** Opbouw: ~$0,20 gas (twee Arbitrum-
> transacties), ~$3,09 wisselkosten (0,25%), €1 DeGiro-handling. Ruim onder de 1%
> waar het plan voor waarschuwt.

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
