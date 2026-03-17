# SPECIFICATION.md: Blauwdruk Ontwikkeling (v1.0)
**Project Status:** Startup Fase 1 (MVP - Validatie)
**Datum:** Februari 2026
**Founder/CIO:** [Jouw Naam]

## 1. Visie & Doelstelling
Het bouwen van een autonoom **Agentic Hedge Fund** dat gebruikmaakt van multi-agent orkestratie om 24/7 kansen te identificeren en te verzilveren in Crypto, Aandelen en Metalen. De focus ligt op het transformeren van passieve trading bots naar actieve, adaptieve besluitvormers (Agents).

## 2. Techniek & Infrastructuur (2026 Stack)
### 2.1 Agent Orchestration Layer
* **Primary Framework:** Google Agent Developer Kit (ADK). Essentieel voor state management, gestandaardiseerde agent-handovers en gedeeld geheugen.
* **Mission Control:** Google Antigravity. De visuele interface voor de Founder om missies te starten, artefacten te bekijken en de "Council of Experts" te monitoren.
* **Development Engine:** Claude Code. Wordt aangestuurd voor high-speed coding, debugging en technische optimalisatie van de trading-executie.

### 2.2 Data & API's
* **Databases:** Supabase (PostgreSQL) voor trade-historie; Redis voor real-time 'Circuit Breaker' status.
* **Markets:** Alpaca (Stocks/Crypto), CCXT (Global Crypto Exchanges), Alpha Vantage (Commodities).
* **Intelligence:** NewsAPI & Claude Browser Skill (voor real-time sentiment analyse op X/Reddit).

## 3. Agent Hiërarchie (Council of Experts)
De ADK zorgt voor de communicatieprotocollen tussen onderstaande rollen:

### A. Project Lead Agent (The CEO)
- **Verantwoordelijkheid:** Delegeert taken, beheert de roadmap en rapporteert P&L aan de Founder.
- **Modus:** Wisselt tussen `Plan Mode` (strategie) en `Act Mode` (executie via Antigravity).

### B. Analyst Council (The Think Tank)
1. **Fundamental Analyst:** Analyseert on-chain data, kwartaalcijfers en macro-economische indicators.
2. **Technical Analyst:** Berekent prijsactie, RSI, MACD en identificeert steun/weerstand zones.
3. **Sentiment Analyst:** Monitort sociale media op 'black swan' events en marktpsychologie (Fear & Greed).

### C. Risk & Audit Agent (The Gatekeeper)
- **Cruciale Taak:** Valideert ELKE trade tegenover de veiligheidsparameters. Kan acties van de Project Lead vetoën.
- **Formule (Kelly Criterion):** $$f^* = \frac{bp - q}{b}$$ (Bepaalt de optimale inzet per trade).

## 4. Operationele Protocollen
### 4.1 Het Debat-protocol
1. De Analisten leveren onafhankelijk van elkaar een signaal (-1 tot +1).
2. De Project Lead synthetiseert dit naar een voorstel.
3. Bij een gecombineerde score > 1.5 wordt het voorstel naar de Risk Agent gestuurd.
4. De Risk Agent controleert de Sharpe Ratio ($$S_a = \frac{E[R_a - R_b]}{\sigma_a}$$). Bij $$S_a < 1.5$$ wordt de trade geblokkeerd.

### 4.2 Veiligheid & Kill Switches
- **Deterministic Check:** Als de koersdata ouder is dan 30 seconden, wordt de executie gestopt.
- **Global Kill Switch:** Een handmatige override in het dashboard die alle actieve posities sluit en agents op 'PAUSED' zet.

## 5. Implementatie Roadmap
- **Fase 1 (Dagen 1-7):** Opzetten ADK-framework in Antigravity. Hello-world connectie met markt-API's.
- **Fase 2 (Dagen 8-21):** Backtesting & Paper Trading. De Council of Experts voert simulaties uit.
- **Fase 3 (Maand 2):** Live Pilot. Gecontroleerde inzet van kapitaal met strikte stop-loss limieten op 2% per positie.

## 6. Dashboard Vereisten (Founder View)
- Real-time P&L weergave.
- "Thought Log" van de Project Lead (waarom doen we wat we doen?).
- Status van de Circuit Breakers.
- Toegang tot 'Artefacten' (browser-opnames van sentiment analyses).