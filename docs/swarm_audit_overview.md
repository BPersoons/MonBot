# Swarm Audit Overview (2026-04-04)

Volledige audit van alle componenten. Gegroepeerd op urgentie.

---

## BUGS — Moeten opgelost worden

### BUG-1: Circuit Breaker defaults naar "trades toestaan" als Redis down is
**Component:** `core/circuit_breaker.py:26-27`
**Ernst:** KRITIEK — verlies van veiligheidsmechanisme
**Probleem:** Als Redis crasht, retourneert `can_trade()` `True` (staat trades toe). De logmelding zegt het tegenovergestelde ("stopping trades"). Dit is een tikkende tijdbom — als Redis faalt tijdens een crash, is er geen bescherming.
**Fix:** Verander default naar `return False`. Voeg file-based fallback toe.

### BUG-2: Pending approval queue wordt nooit opgeruimd
**Component:** `agents/execution_agent.py:1086-1120`
**Ernst:** KRITIEK — trades blijven oneindig in pending staan
**Probleem:** Na goedkeuring of afwijzing wordt de trade NIET verwijderd uit `pending_approvals`. Herverwerking en duplicaten mogelijk.
**Fix:** Verwijder verwerkte trades uit de lijst na processing.

### BUG-3: Auto-backtester SHORT P&L berekening fout
**Component:** `utils/auto_backtester.py:106-107`
**Ernst:** KRITIEK — 1-2% opgeblazen SHORT P&L
**Probleem:** `capital = (position * entry_price) + profit` dubbelltelt winst bij SHORT. Strategieen worden goedgekeurd op basis van te optimistische cijfers.
**Fix:** Corrigeer de capital-berekening na SHORT close.

### BUG-4: Auto-backtester win rate pairing incorrect voor SHORT
**Component:** `utils/auto_backtester.py:134-141`
**Ernst:** KRITIEK — 10-20% afwijking in gerapporteerde win rates
**Probleem:** Buy/sell trades worden i-op-i gepaird in chronologische volgorde, maar de daadwerkelijke roundtrips zijn anders bij meerdere open/close cycli.
**Fix:** Pair trades op basis van entry/exit timestamps, niet op volgorde.

### BUG-5: Research agent keurt SHORT goed met negatieve PnL
**Component:** `agents/research_agent.py:170-175`
**Ernst:** HOOG — 15-20% van SHORT trades zijn verliezers bij goedkeuring
**Probleem:** `if pnl_short > pnl_long` staat toe dat SHORT wordt gekozen als die "minder slecht" is dan LONG, zelfs als beide negatief zijn.
**Fix:** Voeg `pnl_short > 0` toe als vereiste.

### BUG-6: Ghost trade race condition bij order logging failure
**Component:** `agents/execution_agent.py:896-905`
**Ernst:** HOOG — potentiele dubbele posities op Hyperliquid
**Probleem:** Als `log_trade()` faalt maar de order WEL live is op HL, kan de caller opnieuw `execute_order()` aanroepen in dezelfde cycle.
**Fix:** In-flight lock mechanisme voor order placement.

### BUG-7: Market regime SMA berekening off-by-one
**Component:** `agents/research_agent.py:49`
**Ernst:** MEDIUM
**Probleem:** `closes[-21:-1]` sluit huidige close uit. Zou `closes[-20:]` moeten zijn.

---

## OPTIMALISATIES — Gegroepeerd op thema

### A. Backtester & Research Pipeline

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| A1 | Fees modelleren in backtest (0.14% round-trip) | Voorkomt goedkeuring van break-even strategieen | Laag | `auto_backtester.py` |
| A2 | Backtest lookback verlengen van 7 naar 14-21 dagen | Betere regime-dekking | Laag | `auto_backtester.py:14` |
| A3 | Volume filter configureerbaar per asset class | RWA/commodities worden nu uitgesloten bij $100K | Laag | `research_agent.py:31` |
| A4 | Sentiment fallback herstructureren | NEWS_SENTIMENT trades hebben 2-3x hogere drawdown | Medium | `research_agent.py:217-249` |
| A5 | Scout error handling (try/catch) | Scout crash blokkeert hele cycle | Laag | `main.py:368-395` |

### B. Execution & Risk Management

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| B1 | Kelly Criterion naar 1/4-Kelly | Voorkomt over-leveraging bij onzekere probability estimates | Laag | `risk_manager.py:59-76` |
| B2 | Slippage check met orderbook depth | Grote orders krijgen nu 0.5%+ onverwachte slippage | Medium | `execution_agent.py:670-680` |
| B3 | Async order polling (ipv 10s blocking sleep) | 10s latency per order blokkeert alle processing | Medium | `execution_agent.py:838-850` |
| B4 | Fees meenemen in expectancy berekening | 0.14% per trade niet meegenomen | Laag | `risk_manager.py:320` |
| B5 | Adaptieve slippage tolerance (volatility-based) | Vaste 0.5% is te streng in volatiele markten | Laag | `execution_agent.py:673` |

### C. Monitoring & Alerting

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| C1 | Circuit breaker default naar False | Kritiek veiligheidsprobleem | Laag | `circuit_breaker.py:26-27` |
| C2 | Dashboard HTML caching (5s) | Elke request regenereert alles | Laag | `dashboard_server.py:2859` |
| C3 | SwarmMonitor alert dedup persisteren naar disk | Alert spam na restart | Laag | `swarm_monitor.py:1074-1095` |
| C4 | Telegram alert validatie | Stille failures bij verkeerde token/chat ID | Laag | `swarm_monitor.py:34-51` |
| C5 | Database connection pooling / retry logic | Frequent "Connection restored" oscillatie | Medium | `db_client.py` |

### D. Auto-Tuning & Learning

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| D1 | Shadow test window verkorten naar 1-2h | 4h test overlapt meerdere marktregimes | Laag | `auditor.py:510-574` |
| D2 | Win-rate thresholds statistisch onderbouwen | 0.65/0.45 is arbitrair, noise-gevoelig | Medium | `auditor.py:399-400` |
| D3 | Off-boarding op single bad trade versoepelen | Volatiel asset verliest 1 trade = permanent verwijderd | Laag | `auditor.py:320-328` |
| D4 | SwarmLearner prompt dynamisch maken | Hardcoded "ZERO trades" klopt niet altijd | Laag | `swarm_learner.py:403-436` |
| D5 | CPO niet uitschakelen bij >15 pending items | CPO gaat stil tijdens crises | Laag | `product_owner.py:219-222` |

### E. Main Loop & Performance

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| E1 | Parallelliseer ticker analyse (ThreadPool) | Cycle 9 min → 3-4 min, snellere TP/SL checks | Medium | `main.py:792-1020` |
| E2 | Batch price fetches bij reconciliation | 15-30s vertraging per cycle | Medium | `main.py:556-705` |
| E3 | Config-driven TP/SL defaults (ipv hardcoded 2:1/5%) | Herstelde posities krijgen verkeerde risk params | Laag | `main.py:607` |

### F. Analyst Verbeteringen (Prio 3 van eerder)

| # | Verbetering | Impact | Effort | Locatie |
|---|---|---|---|---|
| F1 | Fear & Greed Index integratie | Gratis API, institutioneel sentiment | Medium | `sentiment_analyst.py` |
| F2 | Funding rates / open interest data | On-chain derivaten sentiment | Medium | `fundamental_analyst.py` |
| F3 | Twitter/Reddit API ipv DuckDuckGo scraping | DuckDuckGo is 24-48h vertraagd | Hoog | `web_intelligence.py` |
| F4 | Betere spam-filtering in fundamental analyst | Geen keyword filtering (sentiment analyst heeft dit wel) | Laag | `fundamental_analyst.py` |
| F5 | Asset-class aware sentiment queries | "crypto" hardcoded, breekt voor commodities | Laag | `web_intelligence.py` |
| F6 | LLM cost tracking per agent | Geen inzicht welke agent het meeste kost | Laag | `cost_tracker.py` |

---

## Aanbevolen volgorde

**Week 1 — Bugs + quick wins:**
BUG-1 (circuit breaker), BUG-2 (pending queue), BUG-3+4 (backtester), BUG-5 (SHORT PnL check), A1 (fees), A5 (scout error handling), B1 (1/4-Kelly), C1 (= BUG-1)

**Week 2 — High-impact optimalisaties:**
E1 (parallel ticker analyse), A2 (backtest lookback), B2 (orderbook slippage), C2 (dashboard cache), C5 (db connection), D1 (shadow test window)

**Week 3+ — Structurele verbeteringen:**
F1-F6 (analyst data sources), B3 (async order polling), E2 (batch reconciliation), D2-D5 (tuning/learning)
