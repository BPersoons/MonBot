# Conviction Barbell — Plan (2026-07-27)

> **Status: ONTWERP, nog niet gebouwd/gedeployed.** Dit is de strategische blauwdruk voor
> Bart's lange-termijn vermogensopbouw-been, los van de actieve trading-swarm.
> AI-output is advies — Bart beslist, reviewt en valideert.

## 0. Waarom dit, en niet nóg een strategie

Deze sessie heeft rigoureus vastgesteld (zie memory `feedback_systematic_alpha_hard`):
**er bestaat geen robuuste systematische directionele/selectie-alpha in liquide crypto** die
wij kunnen deployen. Cross-sectionele momentum, richtingsregels, tech-LONG, dip-buy — allemaal
spectaculair op korte vensters, allemaal ingestort op 31mnd / OOS-data.

De eerlijke paden naar rendement die **wél** overeind blijven:
1. **Structureel** — stablecoin-yield (Aave/Morpho, markt-neutraal, ~3-5%). *Doen we al via de treasury.*
2. **Conviction-hold** van majors + brede indices — historisch dé vermogensbouwer. Vasthouden, niet traden.
3. **Rebalancing-premie + diversificatie** — de enige "edge" die robuust is: mechanisch verkopen
   wat steeg, kopen wat daalde, over laag-gecorreleerde assets.
4. **Kapitaal + geduld.**

Dit plan combineert 1-4 in een **barbell**: een veilig been dat kapitaal beschermt + rente pakt,
en een groei-been ("vermogensraket") dat asymmetrische upside zoekt met geaccepteerd drawdown-risico.

## 1. Allocatie — 50% veilig / 50% groei (Bart's keuze 2026-07-27, opgeschaald van 70/30)

Bart koos bewust méér risico (~−25% portfolio-drawdown in een zware bear geaccepteerd).

| Been | % totaal | Instrument | Karakter |
|---|---|---|---|
| **VEILIG** | **50%** | Stablecoin-yield (Aave v3 / Morpho) | Markt-neutraal, ~3-5%, kapitaalbehoud. **Bestaat al** (treasury). |
| **GROEI** | **50%** | Cross-asset conviction-mandje (zie 1a) | Buy-and-hold + band-rebalance. Accepteer -50/-80% DD op crypto-deel. |

### 1a. Groei-mandje (verdeling *binnen* de 50%)

| Positie | % van groei | % van totaal | Rol |
|---|---|---|---|
| **BTC** (spot UBTC, op HL) | 40% | 20% | Crypto-anker; historische vermogensbouwer |
| **Aandelen — bottleneck-thema's** (broker, zie 1b) | 30% | 15% | Groeimotor |
| **Goud** (broker: fysiek ETC, bv. SGLN) | 20% | 10% | Diversifier, lage correlatie |
| **ETH** (tilt, op HL) | 10% | 5% | Hogere-beta crypto-satelliet |

### 1b. Aandelen-been — selectie op tolhuisje (herzien 2026-07-30, EXP-009)

**Vervangt** de oude opzet "60% Nasdaq-UCITS-ETF + 40% conviction-picks (ASML/TSMC)". Twee redenen:
losse picks passen niet bij dit kapitaal (ASML ≈ €1.376/aandeel tegen een allocatie van ~€85, en
brokers handelen alleen hele aandelen), én de Nasdaq-100 selecteert op *beursplein* — geen
kwaliteitscriterium. De halfgeleider-ETF dekt de ASML/TSMC-these systematischer: die twee zijn er
de grootste posities (11,5% en 9,9%).

**Het criterium is niet "groeit dit?" maar: wie kan hier de prijs bepalen, en waarom kan niemand
daaromheen?**

| Thema | % v/h groei-been | Tolhuisje | Slot |
|---|---|---|---|
| Halfgeleiders | 15% | EUV-monopolie, foundry op de scherpste node, EDA-duopolie | 1 |
| Defensie (EU) | 8% | Certificering, programma's over decennia, structureel budget | 2 |
| Software-infrastructuur | 7% | Switching costs | 3 |

**Uitgesloten:** batterij, zon, waterstof, EV, generieke "AI"-mandjes. Kapitaalintensief,
uitwisselbaar product, geen prijszettingsmacht — het verhaal klopt, de economie niet.

**Validatie** (`scripts/theme_bottleneck_backtest.py`, 2008-2026, 18,5 jaar, na TER):

| Mand | CAGR | maxDD | Sharpe |
|---|---|---|---|
| Tolhuisje | **16,0%** | −51% | 0,68 |
| Wereldindex (ACWI) | 7,8% | −56% | 0,39 |
| Narratief | −5,0% | −89% | −0,14 |

Doorslaggevend is niet het totaal maar de consistentie: de tolhuisje-mand verslaat de index in
**alle drie** de deelperiodes (2008-13, 2014-19, 2020-26) en wordt niet door één naam gedragen.
Bekende bias: tickers zijn met kennis achteraf gekozen, dus de niveaus zijn geflatteerd — de
richting en de consistentie zijn dat niet.

**Slot-regel (schaalt mee):** een thema-slot opent pas als het met ≥$500 gevuld kan worden, anders
vreten transactiekosten meer dan een halve procent. Vullen op volgorde. Het aantal slots hangt van
kapitaal af, de volgorde ligt vast — zo limiteert de huidige omvang de structuur niet.

**Controleer het mandje, niet het label.** De "moat"-ETF die aanvankelijk als kwaliteitskern werd
overwogen bleek 74 posities met Braziliaans bier, Duitse defensie en 18% technologie — prima fonds,
verkeerde taak. Vóór elke aankoop en bij elke herweging: top-10 en sectorverdeling opvragen.

**Geaccepteerd risico — correlatiestapeling.** BTC (20% v/h totaal) en de Thematic Exposure Sleeve
(~8%, AI/hyperscaler) bewegen mee met hetzelfde tech-risico als halfgeleiders en software. In een
tech-bear zakt een groot deel tegelijk. Goud (10%) en het veilige been (50%) doen het spreidingswerk.

**Onderbouwing diversificatie:** cross-asset correlaties (0,40-0,56) zijn véél lager dan
binnen-crypto (0,71-0,90). Een mandje BTC+QQQ+GLD haalt echte rebalancing-premie; een mandje
BTC+ETH+SOL niet (die bewegen als één). Getest deze sessie: binnen-crypto-barbell was slechter
dan BTC alleen.

## 2. Rebalancing — mechanische banden, GEEN timing

**Kernregel:** we handelen alléén op een vooraf vastgelegde drift-band, nooit op onderbuik
("dit voelt hoog"). Kijkfrequentie ≠ handelsfrequentie — vaak kijken is gratis, we handelen pas bij
band-breuk.

### 2a. Banden binnen het groei-mandje
- **Trim** een positie zodra `actueel_gewicht > 1,5 × target` (bv. BTC > 60% van groei → terug naar 40%).
  Brede boven-band = winnaars mogen dóórlopen (dáár zit de asymmetrische upside).
- **Bijkopen** zodra `actueel_gewicht < 0,6 × target` (bv. BTC < 24% van groei → terug naar 40%).
- **Harde cap per naam:** geen enkele groei-positie > 50% van het groei-been (concentratie-rem).
- **Cooldown/hysterese:** na een trim/bijkoop op een naam → 7 dagen geen nieuwe trade op díe naam,
  én de positie moet eerst terug ríchting target voor de band opnieuw mag vuren. Dit doodt whipsaw.

### 2b. Top-level barbell-band (50/50)
- **Trim groei → veilig** zodra groei > 55% van totaal (harvest winst naar yield).
- **Bijvullen groei ← veilig** zodra groei < 45% van totaal.
- (Doelband 50% ±5pp.) Dit is het contraire "meebewegen op marktcondities" dat Bart wilde:
  mechanisch winst vastzetten na een run, dip bijkopen na een crash — geen voorspelling/timing.

### 2c. Kijk-cadans, gekoppeld aan volatiliteit
| Been | Cadans | Reden |
|---|---|---|
| Groei-mandje (crypto/thematisch) | **dagelijks** (geautomatiseerd) of wekelijks (handmatig) | Beweegt snel; vangt intra-maand-uitschieters |
| Veilige kern + 50/50-split | maandelijks | Drift nauwelijks week-op-week |

**Bewust NIET gekozen (2026-07-27):** een voorspellende trend-filter/regime-overlay om risico op/af
te schalen. Dat is markttiming — exact wat deze sessie herhaaldelijk instortte. Alleen de contraire
banden hierboven; die zijn de robuuste vorm van adaptatie.

**Box 3-meevaller:** NL kent geen capital-gains-tax → vaker rebalancen is *niet* fiscaal afgestraft;
enige kosten = broker-fee/spread, die de banden laag houden.

## 3. Instappen — DCA

- **Veilig been (50%):** direct inzetten (yield = cash-equivalent, geen entry-timing-risico).
- **Groei been (50%):** DCA over **8 wekelijkse tranches (~2 maanden)**, gelijke bedragen per positie.
  Vermindert het risico dat we op een lokale top volledig instappen. Daarna neemt de band-rebalance het over.

## 4. Venue — BESLIST (2026-07-27): splitsing per asset-type

Elk been op zijn sterkste venue:

| Deel | % van totaal | Venue | Waarom |
|---|---|---|---|
| Veilig (yield) | 50% | **HL / Arbitrum** (treasury) | Bestaat al, autonoom, markt-neutraal |
| Crypto (BTC 20% + ETH 5%) | 25% (= 50% v/d groei) | **HL** (hoofdwallet 0x92D4) | Swarm automatiseert het al; sleutels + infra aanwezig |
| Aandelen + goud (15% + 10%) | 25% (= 50% v/d groei) | **Broker met API** (Saxo/IBKR) | Echt eigendom, diepe liquiditeit, fiscaal schoon |

**Verdeling groei-mandje over venues:** crypto (BTC 40% + ETH 10% = 50% v/d groei) blijft op HL;
aandelen/goud (30% + 20% = 50% v/d groei) naar de broker. Netto: **~75% van het totaal op HL**
(yield + crypto), **~25% bij de broker** (aandelen + goud).

**Crypto-vorm op HL:** voor een meerjarige hold is **spot (UBTC/UETH)** beter dan een 1x perp-long —
geen funding-drag die over jaren compoundt (~-3%/jr op BTC). Nadeel: vereist spot-order-code in
`exchange_client` (nu perp-only). Snelle-start-alternatief: 1x perp-long (nul nieuwe code, minor funding),
later migreren naar spot.

## 5. Wat bestaat al vs. wat te bouwen

**Bestaat al (hergebruiken):**
- Veilig been ≈ **treasury yield-systeem** (Aave/Morpho, target-allocatie, autonoom).
- Groei-tilt ≈ **Thematic Exposure Sleeve** (AI/tech dip-buys, met circuit-breaker + downside-stop).

**Te bouwen — HL crypto-been (nu mogelijk, infra aanwezig):**
- Klein **conviction-hold-module** in de swarm: houdt BTC/ETH op targetgewicht, band-rebalance
  (band + cooldown + harde cap), gescheiden van de actieve trading-agents.
- Optioneel: spot-order-capaciteit in `utils/exchange_client.py` (als we spot i.p.v. perp-long willen).

**Te bouwen — broker aandelen/goud-been (zodra account open):**
- Óf **semi-auto**: native recurring-buy (DCA) + de bestaande `scripts/rebalance_calculator.py` (jij klikt).
- Óf **volledige Saxo-API-executor**: auto-buy + band-rebalance via de OpenAPI, met veilige
  credential-inrichting (aparte scope, IP-whitelist, geen withdraw-recht). Alleen QQQ/GLD → klein oppervlak.

De rekenhulp (`scripts/rebalance_calculator.py`) werkt voor beide venues: hij rekent het hele mandje
(HL + broker) door en zegt per positie wat te doen — ongeacht wie de order plaatst.

## 6. Fasering (poorten)

- **G0 — Venue-keuze + mandje-fixatie.** Broker of HL-spot; exacte gewichten (deze doc) bevestigen.
- **G1 — Veilig been op target.** 70% naar stablecoin-yield (grotendeels al zo via treasury).
- **G2 — DCA-in groei.** 8 wekelijkse tranches in BTC/QQQ/GLD/tilt.
- **G3 — Rebalance-mechaniek live.** Band-engine (HL) óf rekenhulp (broker) + cooldown + caps.
- **G4 — Observeren + jaarlijkse review.** Geen strategie-tweaks op basis van korte vensters (les v/d sessie).

## 7. Discipline-regels (hard, niet-onderhandelbaar)

1. **Handel alleen op een band, nooit op gevoel.** De band beslist wanneer iets te scheef staat.
2. **We timen de piek niet.** Vaker kijken = band-breuk sneller zien, niet de top nailen.
3. **Accepteer drawdowns op het groei-been.** -50/-80% op crypto is normaal; size navenant (dit ís
   de 30%, niet meer).
4. **Geen nieuwe strategie-backtests als "verbetering".** Korte vensters bedriegen altijd
   (bewezen deze sessie). Waarde zit in weten wat NIET werkt.
5. **Winnaars mogen lopen tot de harde cap.** Trim pas bij band/cap, niet bij de eerste stijging.
