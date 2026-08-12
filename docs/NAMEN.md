# Namen — wat heet wat

De namen in dit project komen uit losse experimenten en zeggen van zichzelf niets.
Deze pagina vertaalt ze. **Gebruik in gesprek en in nieuwe documenten altijd de
rechterkolom.** De linkerkolom blijft in de code staan — hernoemen daar levert
alleen risico op, geen duidelijkheid.

## Potjes en strategieën

| Heet in de code | Is eigenlijk | Wat het doet |
|---|---|---|
| Conviction Barbell | **Kopen en vasthouden** | Twee helften: crypto en aandelen, allebei langdurig aanhouden zonder te handelen |
| Conviction Core / `conviction_core.json` | **Crypto vasthouden** | BTC/ETH spot kopen en niet aanraken. Target stond op $650 |
| Aandelen-been / EXP-009 | **Thema-ETF's** | Halfgeleiders, defensie, goud via DeGiro. Instrumenten al gekozen, nog nooit gekocht |
| Thematic Exposure Sleeve / EXP-008 | **Dip-koper** | Koopt automatisch gedaalde thema-tokens op een aparte wallet |
| Kern-ETF | **Wereldindexfonds** | Eén breed indexfonds. 40% van het plan, staat nu op nul |
| F1 / armed-gate trader | **Handelsbot** | De directionele trader. **Staat gepauzeerd** sinds 2026-08-10 |
| Treasury / allocator | **Kasbeheer** | Verdeelt USDC over Aave en andere renteprotocollen; veegt overschot van Hyperliquid weg |
| Funding Harvest | **Rente-oogst** | Kort shorten om financieringsrente te innen |
| Sleeve | **Potje** | Een afgebakend deel van het vermogen met eigen regels |

## Aankopen in stappen (de dip-koper)

| Heet in de code | Is eigenlijk | Wat het doet |
|---|---|---|
| Tranche / T1 | **Eerste aankoop** | Wat er gekocht wordt zodra een aandeel hard genoeg gedaald is |
| T2 (en vroeger T3, T4) | **Bijkoopstap** | Extra aankoop in dezelfde naam, alleen als hij daarna nóg 10% verder zakt |
| `t2_t4_enabled` | **Bijkopen aan/uit** | Staat **uit**. Bijkopen op een verliezende positie is risico toevoegen |
| `tranche_stage` | **Hoeveelste aankoop** | 1 = alleen de eerste aankoop gedaan |
| `TRANCHE_PCTS` | **Verdeling over de stappen** | Nu 60% eerste aankoop / 40% achter de hand |
| `MAX_CONCURRENT_NAMES` | **Aantal bedrijven tegelijk** | Nu 6 |
| Min-notional | **Minimale ordergrootte** | Hyperliquid weigert orders onder $10 |

## Fases (op kapitaal, niet op datum)

| Heet | Is | Wat er dan geldt |
|---|---|---|
| Fase A | **Nu — tot ~€10k** | Twee potjes: 60% veilig, 40% wereldindexfonds |
| Fase B | **Vanaf ~€25k** | Potjes aan: veilig, wereldindex, goud, selectie, 5% crypto |
| Fase C | **Vanaf ~€100k** | Pas hier loont het om de onderzoekscadans te automatiseren |

## Onderzoek

| Heet | Is | Wat het doet |
|---|---|---|
| Scorekaart | **Aandelenanalyse** | Eén bedrijf beoordeeld op zes punten, met poorten vooraf |
| Ledger (`research/ledger.json`) | **Het scorebord** | Alle beoordeelde namen met prijs en datum. Rekent over 6 maanden af tegen de wereldindex |
| Divergentie-screen | **Gedaald maar gezond** | Koop een daling alleen als de cijfers níét meezakten |
| Poort | **Harde eis vooraf** | Faalt hij, dan valt de naam af. Wordt nooit opgerekt |
| Wachtvoorwaarde | **Koopdrempel** | Bij welke prijs of welk cijfer dit koopwaardig wordt |
| These-breuk | **Verkoopregel** | Vooraf opgeschreven: hierbij verkoop je, ongeacht de koers |
| ShadowBook | **Schaduwboek** | Houdt bij hoe beslissingen zouden zijn afgelopen zonder echt geld |

## Techniek

| Heet | Is |
|---|---|
| HL / Hyperliquid | De crypto-beurs waar de bot handelt |
| XYZ-tickers | Synthetische aandelen/grondstoffen op Hyperliquid (XYZ-GOLD, XYZ-SMH) |
| Aave / Morpho / Gains | Renteprotocollen op Arbitrum waar USDC geld verdient |
| Off-ramp | **Uitstap naar euro's** — USDC omzetten en naar je bankrekening sturen. Bestaat nog niet |
| Sleeve-wallet `0xBd6c` | De aparte wallet van de dip-koper |
| Master-wallet `0x92D4` | De hoofdwallet op Hyperliquid |

## Twee dingen die vaak verward worden

**Kopen en vasthouden ≠ het wereldindexfonds.** Het eerste is een eigen keuze in een
paar thema's; het tweede is de hele markt kopen. Ze concurreren om hetzelfde geld:
bij $2.642 laat 60/40 geen ruimte voor $650 crypto.

**Kasbeheer kan geen aandelen kopen.** Het werkt uitsluitend met USDC op Arbitrum en
Hyperliquid. Voor DeGiro heb je euro's op een bankrekening nodig, en die route
bestaat nergens in dit project.
