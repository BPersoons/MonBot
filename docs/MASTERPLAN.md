# Masterplan — van trading-swarm naar autonome vermogensbeheerder

*Opgesteld 2026-07-04. Status: voorstel ter uitvoering, stap voor stap. Eigenaar: Bart. Doel-kapitaal: opschalen naar €100k+.*

---

## 1. North star

> Op elk moment staat het kapitaal op de plek met het hoogste **risicogewogen** rendement, volledig autonoom beheerd, met als output een **positief passief inkomen**.

Niet: "de markt voorspellen". Wel: een portefeuille van *opbrengstbronnen* die elk hun eigen bewijs leveren, met een allocator erboven die kapitaal verschuift naar wat aantoonbaar werkt.

---

## 2. Wat de data van 2 maanden live ons vertelt (waarom we uit de tunnel moeten)

| Bron | Inzet | Resultaat | Aandacht |
|---|---|---|---|
| Directionele swarm (perps) | ~$1.000 | **+$40,76 all-time**, 327 trades, PF 1.07 | ~90% van alle engineering |
| Yield treasury (Aave/Morpho/Gains) | ~$2.000 | Stil en betrouwbaar ~4-8% APY | ~10% |
| Funding Harvest (betaald worden voor een positie) | **gecapt op $150** | Nauwelijks benut | ~0% |
| ShadowBook (gratis hypothese-validatie) | $0 | 500+ gevalideerde signaal-observaties | bijvangst |

**Conclusies:**
1. **Directional alpha is de duurste en dunste opbrengstbron.** PF 1.07 op 327 trades is geen edge, het is ruis. Zelfs als EXP-003 hem naar PF 1.3 tilt, blijft het één sleeve — niet de motor van 100k.
2. **De structurele bronnen zijn onderbenut**: funding/basis, market-making-vaults, vaste rente, nieuwe-markt-inefficiënties. Daar zit rendement dat niet afhangt van gelijk krijgen.
3. **Onze sterkste asset is niet een strategie maar de infrastructuur**: het ShadowBook-patroon (goedkoop meten vóór je kapitaal inzet), de experiment-discipline (EXP-001..003 met review-datums en kill-criteria), en de autonome executie-laag (Arbitrum, HL, Telegram). Dat generaliseren we naar álle bronnen.
4. **De grootste ontdekking van de swarm is geen trade maar een markt**: XYZ synthetische aandelen op Hyperliquid zijn de enige consistent winstgevende asset-klasse (shadow WR 49,6% vs crypto 36,7%). Jonge, dunne markten = inefficiënties waar weinig professionals zitten. Daar hoort een eigen onderzoekslijn.

---

## 3. De vier structurele opbrengstbronnen (+ één lab)

Waar weinig particulieren *systematisch* zitten, maar die wél schalen met kapitaal:

### Bron A — Betaald worden voor balans: funding & basis (delta-neutraal)
Perp-funding is een structurele geldstroom van speculanten naar de neutrale partij. Delta-neutraal (short perp + long spot, of cross-venue) vangt die stroom zonder richtingsrisico. Historisch 5-20% APY in normale markten, met uitschieters naar 50%+ in mania-fases — en juist dán schaalt het. Wij hebben al: FundingHarvestor (naakte short, $150 cap), HL-executie, funding-data. Ontbreekt: de hedge-poot en de schaal.

### Bron B — Betaald worden om de bank te zijn: market-making- en counterparty-vaults
HLP (Hyperliquid's market-making vault), GMX GM, Gains gUSDC: je bent het huis, statistisch gunstig op lange termijn, met zichtbare drawdowns. Historisch 10-20% APY. Wij hebben al: gUSDC live ($1.088), GM in het protocolregister. Ontbreekt: HLP-sleeve en het meten ervan als aparte bron.

### Bron C — Vaste rente kopen wanneer die te duur geprijsd is: Pendle PT
Impliciete yields op Pendle schieten omhoog bij stress/hype; PT kopen = vaste rente vastklikken. Fixed-income-poot van de portefeuille. Stond al als Fase 3 in de treasury-roadmap.

### Bron D — Jonge-markt-inefficiënties: het XYZ-lab
Synthetische aandelen-perps zijn maanden oud, dun, en prijzen buiten beurstijden verkeerd. Concrete, toetsbare hypotheses:
- **Open-gap convergentie**: XYZ-prijs 15:25 UTC vs echte open 15:30 — convergeert de synthetische prijs voorspelbaar?
- **Weekend-funding op synthetics**: extreme funding zonder onderliggende prijsontdekking.
- **Nieuwe listings** (HL voegt wekelijks markten toe): eerste dagen = dunste boeken, grootste inefficiënties.
Alles éérst in shadow (het patroon dat we al hebben), pas live bij aangetoonde edge.

### Lab-bron E (optioneel) — Early-protocol incentives
Nieuwe protocollen betalen vroege gebruikers (points/airdrops). Klein kapitaal, systematisch gekwalificeerd, historisch de meest asymmetrische "passieve" opbrengst in crypto. Default: max 5% van kapitaal, alleen protocollen die al door onze RiskModel-profilering komen.

### Bron F — TradFi-sleeve: ETF's + optie-inkomen (toegevoegd 2026-07-05)
De enige bron met **decennia aan validatiedata**, vrijwel onbeperkte capaciteit en gereguleerde EUR-custody — en daarmee ook de structurele oplossing voor venue-concentratie bij 100k. Volledig automatiseerbaar via de IBKR-API (ib_insync), inclusief **gratis paper-trading account** voor snel-falen zonder risico. Drie bewezen, systematische strategieën:
1. **Kern-compounder**: accumulerende wereld-index-ETF (lange termijn ~7-10% nominaal) als TradFi-fundament. Fiscaal doorgaans gunstig voor accumulerend in België (check accountant — geen advies).
2. **Trend/dual-momentum overlay**: 12-maands trendfilter / relatieve momentum over index-ETF's — 50+ jaar literatuur en data, historisch vergelijkbaar rendement met fors kleinere drawdowns dan buy&hold. Maandelijkse herweging = traag, robuust, goedkoop.
3. **Optie-inkomen (variance risk premium)**: covered calls op de kernpositie / cash-secured puts — structureel betaald worden om risico te dragen, zelfde filosofie als onze funding- en house-sleeves maar op gereguleerde markten. Doel: 5-12% premie-inkomen per jaar bovenop de onderliggende positie.

*Brug op huidige rails: XYZ-SP500/XYZ100 geven al synthetische equity-beta op HL — bruikbaar voor het lab, geen vervanging voor echte custody.*

De **directionele swarm blijft bestaan** — als sleeve met vast, klein budget en een harde bewijslast (PF > 1.3 over 100+ trades) vóór hij meer krijgt. Hij is de optie op hoge upside, niet de kurk waar alles op drijft.

---

## 4. Architectuur: sleeves + meta-allocator

```
                    ┌─────────────────────────────┐
                    │   META-ALLOCATOR (v2 van    │
                    │   TreasuryAgent)            │
                    │   wekelijkse herweging op   │
                    │   rolling risk-adj. return  │
                    └──────────┬──────────────────┘
       ┌───────────┬───────────┼───────────┬───────────────┐
   ┌───▼───┐  ┌────▼────┐ ┌────▼────┐ ┌────▼────┐  ┌───────▼──────┐
   │ YIELD │  │ BASIS   │ │ HOUSE   │ │ SWARM   │  │ LAB          │
   │ core  │  │ funding │ │ HLP/GM/ │ │ direct. │  │ XYZ-gaps,    │
   │ Aave/ │  │ delta-  │ │ gUSDC   │ │ perps   │  │ listings,    │
   │ Morpho│  │ neutraal│ │         │ │         │  │ points       │
   │ Pendle│  │         │ │         │ │         │  │              │
   └───────┘  └─────────┘ └─────────┘ └─────────┘  └──────────────┘
```

**Regels:**
- Elke sleeve heeft: eigen NAV-boekhouding, eigen risk budget, vooraf gedefinieerde kill-criteria en een review-datum in `roadmap.json` (zelfde discipline als EXP-001..003).
- De allocator herweegt wekelijks op **rolling 30d risk-adjusted rendement** (rendement / max-drawdown of Sharpe-proxy), met floors en caps zodat één goede maand niet alles verschuift. Dit vervangt de huidige WR-gebaseerde boost (BL-008 — WR zonder payoff is misleidend gebleken).
- Nieuwe sleeves beginnen ALTIJD in shadow of met max €1-2,5k, en verdienen kapitaal met data.

**Doelmix bij 100k (indicatief, de allocator bepaalt uiteindelijk):**

| Sleeve | Startgewicht | Realistisch target | Karakter |
|---|---|---|---|
| TradFi (F): ETF-kern + trend + optie-inkomen | 30% | 8-15% (beta + premie) | Onbeperkte capaciteit, EUR-custody, decennia data |
| Yield core (A+C) | 25% | 5-9% APY | Fundament, altijd liquide |
| Basis/funding (A) | 20% | 8-20% APY, 30-50% in mania | Marktneutraal, schaalt juist in gekte |
| House-vaults (B) | 10% | 10-20% APY | Drawdowns horen erbij |
| Directionele swarm | 7,5% | optie op >30%, bewijs vereist | Hoog risico |
| Lab (D+E) | 7,5% | asymmetrisch | Experimenten, klein per stuk |

**Verwachting, eerlijk geformuleerd**: het **basisscenario** bij deze startgewichten is blended 8-15% per jaar (= €8-15k passief op 100k). Dat is de vloer waarop je plant, **geen plafond**: de allocator is er juist voor gebouwd om gewichten te verschuiven naar wat op dat moment meer verdient — funding-regimes van 30-50%, een swarm die zijn bewijs levert, een lab-strategie die aanslaat. In gunstige regimes is 20-30% blended haalbaar; het verschil met "beloofd rendement" is dat wij het pas geloven als de sleeve-NAV het laat zien. Geen beloftes van structureel 50%+; wie dat belooft verkoopt iets.

---

## 5. Fasering met validatiepoorten

*Principe: klein starten, snel meten, hard killen. Elke fase heeft een poort — pas door de poort = meer kapitaal.*

### Fase 0 — Meetfundament (week 1-2) ← zonder dit is alles blind
- **Sleeve-NAV boekhouding**: elke euro krijgt een sleeve-label; dagelijkse NAV-snapshot per sleeve (uitbreiding `treasury_state.json` + `pnl_snapshots.json`).
- **Dagelijks Telegram-rapport**: NAV per sleeve, 7d/30d rendement, drawdown, blended totaal in EUR én USD (FX-exposure zichtbaar).
- **Risicokader hard in code**: max % per venue (default: ≤40% op Hyperliquid — bridge/exchange-risico), max drawdown per sleeve → auto-de-risk naar yield core, globale kill-switch.
- *Poort F0: 7 dagen foutloze sleeve-rapportage.*

### Fase 1 — Funding Harvest 2.0: delta-neutraal op schaal (week 2-5)
- Hedge-poot bouwen: short perp + long spot op HL (of unified-margin equivalent), échte basis-trade i.p.v. naakte short.
- Cap $150 → **€2.500 test-notional**. Asset-universum BTC/ETH → top-10 op funding-rank.
- Meten: netto APY na fees/slippage, per epoch.
- *Poort F1: ≥3 weken live, netto APY > 8%, max DD < 2% → schaal naar 25% van kapitaal.*

### Fase 2 — House-sleeve: HLP + herweging bestaande vaults (week 3-6)
- HLP-deposit klein (€1-2k), naast bestaand gUSDC/GM. Alle drie meten als één "house"-sleeve.
- *Poort F2: 4 weken data, rendement/DD-profiel binnen verwachting → naar 15%-gewicht.*

### Fase 3 — XYZ-lab: shadow-first (week 4-8, parallel)
- Open-gap-convergentie-recorder (shadow, $0 risico): log dagelijks XYZ-prijs vlak vóór US open vs eerste echte prints; idem weekend-funding op synthetics; idem eerste-week-gedrag van nieuwe HL-listings.
- *Poort F3: n ≥ 30 events met aantoonbare, na-kosten-positieve edge → live met €1k per strategie.*

### Fase 4 — Pendle PT executor (week 6-10)
- Stond al gepland (Treasury Fase 3). Trigger: PT kopen wanneer implied yield > X% boven onze variabele yield core.
- *Poort F4: eerste tranche €2,5k, hold-to-maturity wiskunde klopt na gas/slippage.*

### Fase 5 — Meta-allocator v1 (week 8-12)
- TreasuryAgent-uitbreiding: wekelijkse herweging over álle sleeves op rolling risk-adjusted rendement. Eerste 4 weken mens-in-de-loop (Telegram-approve), daarna autonoom binnen het risicokader.
- *Poort F5: 4 weken schaduw-adviezen die je zelf ook gedaan zou hebben → autonoom.*

### Fase 6 — TradFi-sleeve via IBKR (week 2-12, parallel — start in paper)
- Week 2-3: IBKR-account (echt + paper), API-koppeling (ib_insync), sleeve-NAV integratie.
- Week 3-8: trend/dual-momentum strategie **eerst backtesten op 20+ jaar data** (dat kán hier, uniek onder onze sleeves), daarna live in **paper-account** — gratis snel-falen.
- Week 4-8: covered-call module in paper naast de kern-ETF.
- *Poort F6a: backtest bevestigt literatuur (Sharpe > buy&hold, kleinere max DD) → kern-ETF live met echte eerste tranche.*
- *Poort F6b: 4 weken paper-trading zonder executie-verrassingen → trend-overlay en optie-inkomen live.*
- Fiscale check (accumulerend vs distribuerend, optiepremies) door accountant vóór echte inleg — geen fiscaal advies van het systeem.

### Kapitaal-opschaling (poorten, geen datums)
| Stap | Voorwaarde |
|---|---|
| €3k → €10k | F0 + F1 gehaald |
| €10k → €30k | Allocator live (F5) + 8 weken blended track record positief |
| €30k → €100k | 3 maanden blended track + venue-spreiding operationeel (≥3 onafhankelijke custody-locaties) |

De directionele swarm doet ondertussen gewoon mee (EXP-003 loopt, review 07-11) — maar met vast budget, en hij concurreert vanaf Fase 5 op gelijke voet met de andere sleeves om kapitaal.

---

## 6. Beslispunten (defaults gekozen — overrule waar je wilt)

1. **Venue-concentratie**: max 40% op Hyperliquid. *(Alles-op-HL is de facto één counterparty-risico, hoe goed het platform ook is.)*
2. **Basisvaluta**: rapportage in EUR én USD; 100k in USD-stables = een impliciete EUR/USD-positie. Optie voor later: deel yield core in EUR-stables (EURC op Aave).
3. **Lab-sleeve E (points/airdrops)**: default AAN, max 5%, alleen protocollen met RiskModel-profiel.
4. **HLP-drawdowns**: default geaccepteerd (capped op sleeve-budget) — je bent het huis, het huis heeft slechte avonden.
5. **Broker voor TradFi-sleeve**: default IBKR (enige met volwaardige API voor volledige automatisering + opties + paper-accounts). Alternatieven (Bolero/DEGIRO/Saxo) zijn fiscaal-administratief eenvoudiger voor Belgen maar niet of nauwelijks automatiseerbaar — en "alles beheerd" was de eis.

---

## 7. Uitvoeringsdiscipline

- Elke fase wordt een **EXP-entry in `roadmap.json`** met metric, review-datum en kill-criterium — exact zoals EXP-001..003. Geen sleeve zonder poort.
- **Snel falen is het doel**: een sleeve die zijn poort mist wordt gekilld of terug naar shadow — geen "nog even aankijken".
- Dit document is de bron; per fase maken we een korte werkbon (taak in de sessie) met de concrete bouwstappen.
- Eerste concrete stap na akkoord: **Fase 0, sleeve-NAV boekhouding** — want zonder meetfundament is elke discussie over "wat werkt het best" een mening.
