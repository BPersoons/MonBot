# Fase 1 — Funding Harvest 2.0: ontwerp (delta-neutrale basis-trade)

*Opgesteld 2026-07-05. Status: ONTWERP — geen code gebouwd, geen kapitaal ingezet. Onderdeel van [docs/MASTERPLAN.md](MASTERPLAN.md) Fase 1. Uitvoering start pas als de F0-poort (7 dagen foutloze sleeve-rapportage) gehaald is.*

---

## 1. Waarom dit document bestaat

Bart vroeg om alvast te beginnen met Fase 1 terwijl de F0-poort (sleeve-NAV, EXP-004) nog loopt. Besluit: **geen kapitaal nu, wel het ontwerp nu** — zodat er niets te wachten valt zodra de poort valt. Dit document is het resultaat van dat ontwerpwerk: wat er al is, wat er ontbreekt, wat ik heb geverifieerd tegen de live Hyperliquid-API, en het concrete bouwplan.

---

## 2. Huidige staat: FundingHarvestor is een naakte short, geen hedge

`agents/treasury_agent.py` (regel ~1180-1440) opent een **kale SELL** op HL wanneer de funding-rate hoog genoeg is (`_HARVEST_MIN_RATE_8H = 0.01%/8h`), gecapt op **$150 notional**, alleen BTC/ETH, max 48h hold.

Dit is géén delta-neutrale trade. Het is een gerichte weddenschap dat de funding-opbrengst de prijsbeweging compenseert — de "veiligheid" komt puur van de kleine omvang en de korte houdduur, niet van een hedge. Bij een harde prijsrally op de short verlies je op de koers, ook al incasseer je funding. Dat is precies waarom het masterplan (sectie 3, Bron A) dit al benoemde als "naakte short, $150 cap" en pleit voor een échte hedge-poot.

---

## 3. Onderzoek: is een échte basis-trade haalbaar op Hyperliquid zelf?

De centrale vraag was: heeft HL spot-markten met genoeg liquiditeit om de long-poot (spot) te vullen naast de bestaande short-poot (perp)? Geverifieerd tegen de live HL-API (`https://api.hyperliquid.xyz/info`, 2026-07-05):

**Ja — UBTC/USDC en UETH/USDC bestaan** (wrapped BTC/ETH via HL's "Unit"-protocol, dezelfde onderliggende assets als de perps):

| Pair | API-naam | Spread | Diepte (top-5) | Basis vs perp |
|---|---|---|---|---|
| UBTC/USDC | `@142` | $62.649 / $62.650 (~1,6 bps) | ~2,1 BTC (~$130k) | perp $62.663 vs spot ask $62.650 → ~2 bps, verwaarloosbaar |
| UETH/USDC | `@151` | $1.762,8 / $1.762,9 (~0,6 bps) | ~50+ ETH (~$90k) | perp $1.763 vs spot ask $1.762,9 → ~0,6 bps, verwaarloosbaar |

**Conclusie**: voor een test-notional van €2.500 is er ruim voldoende diepte, en de basis (prijsverschil spot vs perp) is klein genoeg dat instappen geen structurele kost is. Beide poten (long spot + short perp) kunnen op **dezelfde venue** — geen extra cross-exchange bridging of counterparty-risico bovenop wat we al hebben.

**Bonus**: HYPE heeft directe spot-markten (index 107/207/232/255, tegen USDC/USDT0/USDH/USDE) — potentieel een derde asset voor de universumverbreding (top-10 op funding-rank) uit het masterplan, al is HYPE volatieler en dunner dan BTC/ETH.

---

## 4. Technische gap: exchange_client kan nu geen spot-orders plaatsen

`utils/exchange_client.py` initialiseert zowel de public als de signing CCXT-client hardcoded met `'options': {'defaultType': 'swap'}`, en `_normalize_symbol()` kiest **expliciet altijd perp boven spot** wanneer beide bestaan (regel ~96: *"Always prefers perpetual (swap) over spot when both exist"*). Dat is een bewuste keuze geweest omdat de swarm tot nu toe uitsluitend perps handelt — maar het betekent dat er vandaag geen pad is om `UBTC/USDC` (spot) te kopen via de bestaande client.

**Benodigde uitbreiding** (geen implementatie nu, wel gescoped):
- Nieuwe methode of parameter op `HyperliquidExchange` om een spot-order te plaatsen zonder de bestaande perp-normalisatie te breken (bv. `create_spot_order(ticker, action, quantity)` met een aparte CCXT-instance met `defaultType: 'spot'`, of een `market_type` parameter op `create_order`).
- Decimale precisie: spot-tokens hebben hun eigen `weiDecimals` (UBTC=10, UETH=9) — afwijkend van de perp size-decimals. Sizing-logica moet beide kanten correct afronden zodat de long- en short-poot notioneel gelijk zijn.

---

## 5. Ontwerp: symmetrische open/close, eigen state, eigen sleeve

**State machine** (nieuw `treasury_basis.json`, naast het bestaande `treasury_harvest.json` — niet vermengen, de naakte-short-harvestor blijft desgewenst apart bestaan als kleinere/snellere variant):
1. **Open**: bij funding-rate boven drempel → koop spot (long) EN open perp-short in dezelfde cyclus, gelijke notional. Bij falen van één poot: de andere poot direct terugdraaien (geen periode met alleen één been open — dat is naakte directionele exposure, precies wat we willen vermijden).
2. **Monitor**: elke cyclus funding-rate + basis (spot-perp spread) checken. Basis die te veel uitwaaiert (bv. spot depegt van perp) is een eigen risicosignaal, los van de funding-rate.
3. **Close**: symmetrisch — beide poten sluiten in dezelfde cyclus. Netto P&L = funding ontvangen + (spot-koersverandering) + (perp-koersverandering, tegengesteld teken) − fees beide poten − slippage beide poten. Bij een correcte hedge vallen de koerstermen grotendeels weg; het overblijvende is funding minus kosten.

**Sleeve-boekhouding**: de `basis`-sleeve (al gereserveerd in `config/sleeves.json`, nu op $0) krijgt twee componenten — spot-holding (UBTC/UETH-waarde) én perp-marge. **Let op de bestaande pitfall** ("Unified mode balance double-count", CLAUDE.md): de huidige `get_balance()` combineert al spot + perp-accountValue voor de hoofd-balans. Zodra we spot UBTC/UETH aanhouden náást de bestaande USDC-spot, moet de sleeve_nav-mapping dat component apart en correct optellen — niet laten meetellen in een generieke "spot_usdc"-teller, en niet dubbel tellen met de perp-kant van dezelfde basis-trade.

**Asset-universum**: masterplan noemt "top-10 op funding-rank"; op dit moment is alleen BTC/ETH (en experimenteel HYPE) spot-gedekt haalbaar op HL zelf. Verbreding naar meer assets vereist ofwel meer HL Unit-spot-listings (buiten onze controle, wel maandelijks te checken via de Opportunity Radar) of een cross-exchange hedge-poot (grotere stap, apart te ontwerpen, brengt exchange-risico terug dat we net vermeden).

---

## 6. Open vragen / risico's (niet opgelost, bewust benoemd)

1. **Been-desync risico**: als de long-poot vult maar de short-poot faalt (of vice versa) middenin een cyclus, ontstaat tijdelijk naakte exposure. Ontwerp moet dit actief detecteren en binnen dezelfde cyclus corrigeren, niet pas bij de volgende monitor-tick.
2. **Correlatie met de directionele swarm**: als de swarm zelf al een BTC/ETH-positie open heeft (long of short), telt de basis-trade's perp-poot mee in de bestaande correlation-cap-logica van RiskManager? Moet worden uitgesloten of apart geboekt — een basis-trade is geen directionele weddenschap en moet niet de correlation-gate van echte swarm-trades triggeren, maar moet wél meetellen in totale venue-marge-gebruik.
3. **Spot trading fees**: nog niet opgehaald uit HL's fee-schedule-endpoint. Nodig voor de echte netto-APY-berekening (poort F1 vereist >8% ná fees).
4. **`dayNtlVlm` toonde 0.0** in de asset-context-call voor beide pairs, terwijl het orderboek wél echte diepte laat zien — vermoedelijk een API-veld-eigenaardigheid (mogelijk anders geaggregeerd voor spot dan voor perps) en geen teken van een dode markt. Voor de zekerheid: vóór live-gang een paar dagen orderboek-diepte op verschillende tijdstippen samplen, niet op één snapshot vertrouwen.
5. **HYPE-uitbreiding**: apart te beoordelen — volatieler, dunner, en HYPE is het eigen token van de venue (extra correlatie met "hoe gaat het met Hyperliquid zelf").

---

## 7. Shadow mode — live sinds 2026-07-05 (geen kapitaal, geen orders)

Op Bart's voorstel: in plaats van te wachten tot de F0-poort valt voordat er iets gebeurt, draait er nu een **virtuele** versie van de basis-trade mee — `utils/shadow_basis.py`, zelfde filosofie als het bestaande ShadowBook-patroon. Elke ~5 minuten: haalt live funding-rates + de echte UBTC/UETH-orderboeken op (publieke HL-endpoints, geen keys nodig), simuleert open/monitor/close volgens de logica uit sectie 5, en logt het resultaat — inclusief een placeholder fee-aanname (3,5 bps × 4 poten, expliciet gemarkeerd als te vervangen zodra de echte fee-schedule bekend is, zie open vraag #3). Bij elke virtuele close krijgt Bart een Telegram-melding.

Bestanden: `shadow_basis_state.json` (open virtuele positie), `shadow_basis_log.json` (gesloten, bounded 500), `shadow_basis_report.json` (cumulatief: totale funding, fees, netto P&L, gemiddelde APY, max geobserveerde basis-spread, close-reden-verdeling).

**Nieuwe, striktere gate-volgorde** (vervangt de oude enkelvoudige Poort F1):

- **Poort F1-shadow**: N dagen shadow-data (richtwaarde: 2-3 weken, genoeg voor meerdere funding-cycli en marktomstandigheden) met modelmatig netto APY > 8% en een stabiele basis (geen herhaalde `basis_blowout`-closes). Kost niets, loopt al.
- **Poort F1-live** (pas ná F1-shadow én de F0-poort): eerste echte inzet, klein (€500-2.500), ≥3 weken, netto APY > 8% ná échte fees, max drawdown < 2% → pas dan opschalen naar het volledige sleeve-gewicht.

**Methodologische kanttekening** (ontdekt tijdens het testen van de rekenkern): bij korte houdduren domineren de fees de geannualiseerde APY enorm — een positie die na 2 uur sluit op de rate-drop-conditie toont een APY van honderden procenten negatief, puur omdat een vast kostenbedrag over een paar uur wordt geëxtrapoleerd naar een jaar. Beoordeel de shadow-resultaten dus op **cumulatieve netto USD** en het gemiddelde over voldoende trades, niet op de APY van een individuele korte trade.

## 8. Concreet stappenplan voor de LIVE stap (uit te voeren zodra beide poorten vallen)

1. `exchange_client.py`: spot-order-capability toevoegen (nieuwe methode, geen breaking change aan bestaand perp-pad).
2. `treasury_agent.py`: nieuwe `BasisHarvestor`-klasse (of uitbreiding van de bestaande) met de symmetrische open/monitor/close-logica uit sectie 5, eigen `treasury_basis.json`. Kan grotendeels de bewezen logica uit `shadow_basis.py` hergebruiken.
3. `config/sleeves.json`: mapping voor de spot-component van de basis-sleeve toevoegen; `utils/sleeve_nav.py` uitbreiden zodat een sleeve met twee componenten (spot + perp-marge) correct optelt zonder dubbeltelling.
4. HL fee-schedule ophalen, de placeholder-aanname in het netto-APY-model vervangen door echte cijfers.
5. RiskManager: expliciete uitsluiting/aparte boeking van basis-trade-posities in de correlation-cap-check.
6. Test-notional €2.500 (of kleiner startbedrag, bv. €500, als extra voorzichtige eerste stap — te beslissen bij uitvoering), BTC of ETH afhankelijk van welke op dat moment de beste funding-rate + shadow-track-record heeft.
7. Live monitoren tegen **Poort F1-live** → pas dan opschalen naar het volledige sleeve-gewicht.

---

## 9. Wat dit ontwerp NIET doet

Geen order geplaatst, geen kapitaal verplaatst, geen wijziging aan de echte trading- of treasury-paden. `shadow_basis.py` raakt uitsluitend publieke read-only endpoints en zijn eigen los bestand. In lijn met de afspraak: geen echt kapitaal vóór beide poorten (shadow + F0) vallen.
