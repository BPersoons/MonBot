import json
import logging
import os
import time
from core.circuit_breaker import CircuitBreaker
# from google.cloud import aiplatform # ADK integration point
# Assuming ADK might be a conceptual framework or specific library wrapper
# For now, implementing the core logic requested.

class RiskManager:
    """
    Risk Agent responsible for validating trades and managing portfolio risk.
    Includes anomaly detection and circuit breaker integration.
    """
    def __init__(self, config=None, exchange_client=None):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        self.circuit_breaker = CircuitBreaker()
        self.price_history = {}  # Track recent prices for flash crash detection
        self.exchange_client = exchange_client
        self.free_margin_reserve_pct         = float(os.getenv("FREE_MARGIN_RESERVE_PCT", "0.15"))
        self.max_position_pct                = float(os.getenv("MAX_POSITION_PCT", "0.10"))
        self.displacement_min_conviction     = float(os.getenv("DISPLACEMENT_MIN_CONVICTION", "0.75"))
        self.displacement_weakness_threshold = float(os.getenv("DISPLACEMENT_WEAKNESS_THRESHOLD", "0.40"))
        # Correlation gate — lazy import so RiskManager still imports if util fails.
        self.correlation_max = float(os.getenv("CORRELATION_MAX", "0.65"))
        try:
            from utils.correlation_tracker import CorrelationTracker
            self.correlation_tracker = CorrelationTracker()
        except Exception as e:
            self.logger.warning(f"CorrelationTracker unavailable (fail-open): {e}")
            self.correlation_tracker = None

    def _get_btc_regime(self) -> str:
        """Return BTC market regime from cached market_regime.json (written by ResearchAgent).

        Values: TRENDING_BULL | TRENDING_BEAR | RANGING | VOLATILE | NEUTRAL.
        Falls back to NEUTRAL when the file is absent, unreadable, or stale (>30 min).
        Using the cached file avoids creating a fresh ccxt instance per trade validation
        (~11s market-list reload) and keeps regime logic consistent with the rest of the pipeline.
        """
        try:
            stat = os.stat("market_regime.json")
            if time.time() - stat.st_mtime > 1800:  # stale after 30 min
                return "NEUTRAL"
            with open("market_regime.json") as f:
                data = json.load(f)
            return data.get("regime", "NEUTRAL")
        except Exception:
            return "NEUTRAL"

    def check_trade_safety(self, win_probability: float, net_odds: float, bankroll: float = None) -> dict:
        """
        Calculates the optimal position size using the Kelly Criterion.
        
        Formula: f* = (bp - q) / b
        Where:
            b = net odds received on the wager (b to 1)
            p = probability of winning
            q = probability of losing (1 - p)
        
        Args:
            win_probability (float): The probability of the trade winning (0.0 to 1.0).
            net_odds (float): The net odds (risk/reward ratio per unit). 
                              If you risk 1 to win 2, net_odds is 2.
            bankroll (float, optional): Total available capital. If None, queries the exchange.

        Returns:
            dict: Contains safety status, kelly fraction, and recommended position size.
        """
        if bankroll is None:
            if self.exchange_client:
                # Use free margin (accountValue - totalMarginUsed) instead of total
                # balance. Kelly sizing on total balance over-sized orders when the
                # account was leveraged up, causing HL to fill only the sliver of
                # actually-available margin (Bug #1, April 2026).
                try:
                    bankroll = self.exchange_client.get_free_margin()
                except Exception as e:
                    self.logger.warning(f"get_free_margin() failed, falling back to get_balance(): {e}")
                    bankroll = self.exchange_client.get_balance()
                self.logger.info(f"Fetched live free margin: ${bankroll:.2f}")
            else:
                self.logger.warning("No exchange client or bankroll provided. Defaulting to $0.0 to block trade.")
                bankroll = 0.0

        if net_odds <= 0:
            return {"safe": False, "reason": "Net odds must be positive", "recommended_size": 0.0}
        
        p = win_probability
        q = 1.0 - p
        b = net_odds

        # Kelly Criterion: f* = (bp - q) / b
        full_kelly = (b * p - q) / b

        # Half-Kelly: industry standard for safety — reduces variance by 75%
        # while only sacrificing ~25% of expected growth
        kelly_fraction = full_kelly * 0.5

        is_safe = kelly_fraction > 0
        recommended_size = 0.0

        if is_safe:
            # Leverage multiplies buying power: Kelly sizes the notional,
            # but margin needed is notional / leverage
            leverage = int(os.getenv("DEFAULT_LEVERAGE", "3"))
            effective_bankroll = bankroll * leverage
            recommended_size = kelly_fraction * effective_bankroll

        result = {
            "safe": is_safe,
            "kelly_fraction": round(kelly_fraction, 4),
            "recommended_size": round(recommended_size, 2),
            "details": {
                "p": p,
                "b": b,
                "q": q,
                "full_kelly": round(full_kelly, 4),
                "half_kelly": round(kelly_fraction, 4),
            }
        }
        
        return result
    
    def detect_anomalies(self, proposal: dict) -> dict:
        """
        Detects anomalies and corrupt data in trade proposals.
        Returns dict with has_anomaly, anomalies_found, and details.
        """
        anomalies = []
        ticker = proposal.get('ticker', 'UNKNOWN')
        price = proposal.get('price', 0)
        win_probability = proposal.get('win_probability', 0.5)
        
        # Get analyst signals if available
        analyst_signals = proposal.get('analyst_signals', {})
        technical_signal = analyst_signals.get('technical', 0)
        fundamental_signal = analyst_signals.get('fundamental', 0)
        sentiment_signal = analyst_signals.get('sentiment', 0)
        
        # 1. Price Anomalies
        if price <= 0:
            anomalies.append({
                "type": "INVALID_PRICE",
                "severity": "CRITICAL",
                "detail": f"Price is {price}, must be > 0",
                "field": "price"
            })
        elif price > 1000000:  # Unreasonably high (>$1M)
            anomalies.append({
                "type": "SUSPICIOUS_PRICE",
                "severity": "HIGH",
                "detail": f"Price ${price} exceeds reasonable maximum",
                "field": "price"
            })
        
        # 2. Probability Anomalies
        if win_probability < 0 or win_probability > 1:
            anomalies.append({
                "type": "INVALID_PROBABILITY",
                "severity": "CRITICAL",
                "detail": f"Win probability {win_probability} outside [0,1] range",
                "field": "win_probability"
            })
        
        # 3. Sentiment Signal Anomalies
        if abs(sentiment_signal) > 1.0:
            anomalies.append({
                "type": "INVALID_SENTIMENT",
                "severity": "CRITICAL",
                "detail": f"Sentiment signal {sentiment_signal} outside [-1,1] range",
                "field": "sentiment_signal"
            })
        
        # Check for extreme values (999, -999 etc.)
        if abs(sentiment_signal) > 10:
            anomalies.append({
                "type": "EXTREME_SENTIMENT",
                "severity": "CRITICAL",
                "detail": f"Sentiment signal {sentiment_signal} is suspiciously extreme",
                "field": "sentiment_signal"
            })
        
        # 4. Technical Signal Anomalies
        if abs(technical_signal) > 1.0:
            anomalies.append({
                "type": "INVALID_TECHNICAL",
                "severity": "HIGH",
                "detail": f"Technical signal {technical_signal} outside expected range",
                "field": "technical_signal"
            })
        
        # 5. Fundamental Signal Anomalies  
        if abs(fundamental_signal) > 1.0:
            anomalies.append({
                "type": "INVALID_FUNDAMENTAL",
                "severity": "HIGH",
                "detail": f"Fundamental signal {fundamental_signal} outside expected range",
                "field": "fundamental_signal"
            })
        
        # 6. Flash Crash Detection (price drops significantly from recent average)
        if ticker in self.price_history:
            recent_prices = self.price_history[ticker]
            if len(recent_prices) >= 3:
                avg_price = sum(recent_prices) / len(recent_prices)
                price_drop_pct = (avg_price - price) / avg_price if avg_price > 0 else 0
                
                if price_drop_pct > 0.15:  # 15% drop
                    anomalies.append({
                        "type": "FLASH_CRASH",
                        "severity": "CRITICAL",
                        "detail": f"Price ${price} is {price_drop_pct*100:.1f}% below recent average ${avg_price:.2f}",
                        "field": "price",
                        "avg_price": avg_price,
                        "current_price": price
                    })
        
        # Update price history (keep last 10)
        if ticker not in self.price_history:
            self.price_history[ticker] = []
        if price > 0:  # Only track valid prices
            self.price_history[ticker].append(price)
            if len(self.price_history[ticker]) > 10:
                self.price_history[ticker].pop(0)
        
        has_anomaly = len(anomalies) > 0
        
        return {
            "has_anomaly": has_anomaly,
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
            "ticker": ticker
        }

    def check_portfolio_capacity(self, open_trades: list) -> dict:
        """Returns whether the portfolio has room for a new position based on free margin."""
        if self.exchange_client:
            try:
                total = self.exchange_client.get_balance()
                free  = self.exchange_client.get_free_margin()
                if total > 0:
                    free_pct = free / total
                    if free_pct < self.free_margin_reserve_pct:
                        return {
                            'has_room': False,
                            'needs_displacement': True,
                            'reason': f"Free margin {free_pct*100:.1f}% < reserve {self.free_margin_reserve_pct*100:.0f}%",
                            'free_pct': round(free_pct, 4),
                        }
            except Exception as e:
                self.logger.warning(f"check_portfolio_capacity: balance check failed ({e}), allowing trade")
        return {'has_room': True, 'needs_displacement': False, 'reason': "Capacity OK", 'free_pct': None}

    # ── Max Portfolio Drawdown ──────────────────────────────────────────
    _DRAWDOWN_FILE = "portfolio_peak.json"

    def check_portfolio_drawdown(self) -> dict:
        """
        Tracks portfolio peak equity and blocks new trades if drawdown exceeds threshold.
        Peak is tracked on REALIZED equity only (total - unrealized PnL) to prevent
        temporary paper gains from inflating the peak and causing false drawdown halts
        after normal market reversals. Drawdown is measured from realized peak to
        current total equity (including unrealized).
        """
        max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", "15.0"))

        if not self.exchange_client:
            return {"ok": True, "drawdown_pct": 0.0}

        try:
            current_equity = self.exchange_client.get_balance()
        except Exception as e:
            self.logger.warning(f"Drawdown check: balance fetch failed ({e}), allowing trade")
            return {"ok": True, "drawdown_pct": 0.0}

        if current_equity <= 0:
            return {"ok": True, "drawdown_pct": 0.0}

        # Include capital deployed to external yield protocols (Aave, Morpho, etc.)
        # so that treasury redeployments don't trigger a false drawdown halt.
        deployed_yield = 0.0
        try:
            from utils.treasury_executor import get_total_yield_balance, _TREASURY_WALLET
            deployed_yield = get_total_yield_balance(_TREASURY_WALLET)
            if deployed_yield > 0:
                self.logger.debug(f"Drawdown: adding ${deployed_yield:.2f} total yield balance to equity")
        except Exception:
            pass
        current_equity += deployed_yield

        # Realized equity = total - unrealized PnL (peak tracks only locked-in value)
        unrealized_pnl = 0.0
        try:
            unrealized_pnl = self.exchange_client.get_unrealized_pnl()
        except Exception:
            pass
        realized_equity = current_equity - unrealized_pnl

        # Load persisted peak (realized-only basis)
        peak_equity = realized_equity
        try:
            with open(self._DRAWDOWN_FILE, "r") as f:
                data = json.load(f)
                stored_peak = data.get("peak_equity", realized_equity)
                # Sanity guard: stored peak > 3× current equity almost certainly means a
                # double-count bug (e.g. mid-yield-switch state inflated the balance read).
                # Cap it so a transient read error can't permanently lock out trading.
                if stored_peak > realized_equity * 3:
                    self.logger.warning(
                        f"Drawdown: stored peak ${stored_peak:.2f} > 3× current realized "
                        f"${realized_equity:.2f} — likely inflated, capping to current"
                    )
                    stored_peak = realized_equity
                peak_equity = max(stored_peak, realized_equity)
        except (FileNotFoundError, json.JSONDecodeError):
            peak_equity = realized_equity

        # Persist
        try:
            with open(self._DRAWDOWN_FILE, "w") as f:
                json.dump({"peak_equity": peak_equity, "updated_at": time.time()}, f)
        except Exception:
            pass

        # Drawdown: compare CURRENT total equity against realized peak
        drawdown_pct = ((peak_equity - current_equity) / peak_equity) * 100 if peak_equity > 0 else 0.0

        if drawdown_pct >= max_drawdown_pct:
            self.logger.warning(
                f"DRAWDOWN HALT: ${current_equity:.2f} (realized=${realized_equity:.2f}) "
                f"is {drawdown_pct:.1f}% below realized peak ${peak_equity:.2f} (limit: {max_drawdown_pct}%)"
            )
            return {
                "ok": False,
                "drawdown_pct": round(drawdown_pct, 1),
                "current_equity": current_equity,
                "realized_equity": realized_equity,
                "unrealized_pnl": unrealized_pnl,
                "peak_equity": peak_equity,
                "reason": f"Portfolio drawdown {drawdown_pct:.1f}% exceeds {max_drawdown_pct}% limit",
            }

        return {"ok": True, "drawdown_pct": round(drawdown_pct, 1), "peak_equity": peak_equity}

    def score_position_weakness(self, trade: dict, positions_status: dict = None) -> float:
        """
        Weakness score 0.0–2.0. Higher = weaker = displacement candidate.
        Formula: (1 - conviction) + max(0, -pnl_pct / 100)
        conviction is abs(combined_score) already in [0, 1].
        """
        conviction = min(float(trade.get('conviction', 0.5)), 1.0)
        pnl_pct    = 0.0
        ticker     = trade.get('ticker', '')
        if positions_status and ticker in positions_status:
            pnl_pct = float(positions_status[ticker].get('pnl_pct', 0.0))
        return round((1.0 - conviction) + max(0.0, -pnl_pct / 100.0), 4)

    def find_displacement_candidate(self, open_trades: list, positions_status: dict = None):
        candidates = [t for t in open_trades if t.get('status') in ('OPEN', 'PLACED')]
        if not candidates:
            return None
        scored = sorted(
            [(t, self.score_position_weakness(t, positions_status)) for t in candidates],
            key=lambda x: x[1], reverse=True
        )
        weakest, score = scored[0]
        self.logger.info(
            f"[DISPLACEMENT] Weakest candidate: {weakest.get('ticker')} "
            f"weakness={score:.3f} (threshold={self.displacement_weakness_threshold})"
        )
        return weakest if score >= self.displacement_weakness_threshold else None

    # Setup-aware spread thresholds (bps of mid price). Swings mogen wijder: langer hold
    # amortiseert spread-fee. Macro trades moeten strak — ronde-trip eet edge op korte termijn.
    SPREAD_MAX_BPS = {"1h Macro": 15.0, "Macro News": 20.0, "4h Swing": 25.0}
    SPREAD_MAX_DEFAULT = 15.0

    def _check_spread(self, ticker: str, timeframe: str = None) -> dict:
        """
        Fetches L1 orderbook and rejects trade if spread exceeds setup-aware threshold.
        Fail-open on any fetch/parse failure (don't block trades over transient errors).
        """
        if not self.exchange_client or not hasattr(self.exchange_client, 'get_l1_orderbook'):
            return {'ok': True, 'spread_bps': None, 'reason': 'no exchange client'}
        try:
            ob = self.exchange_client.get_l1_orderbook(ticker)
            if not ob or not ob.get('bid') or not ob.get('ask'):
                return {'ok': True, 'spread_bps': None, 'reason': 'OB unavailable (fail-open)'}
            bid = float(ob['bid']); ask = float(ob['ask'])
            if bid <= 0 or ask <= 0 or ask <= bid:
                return {'ok': True, 'spread_bps': None, 'reason': 'OB invalid (fail-open)'}
            mid = (bid + ask) / 2.0
            spread_bps = (ask - bid) / mid * 10000.0
            tf = (timeframe or '').strip()
            limit = self.SPREAD_MAX_BPS.get(tf, self.SPREAD_MAX_DEFAULT)
            if spread_bps > limit:
                self.logger.info(
                    f"[SPREAD_GATE] {ticker}: blocked — spread {spread_bps:.1f} bps > {limit:.0f} bps (setup={tf or 'default'})"
                )
                return {'ok': False, 'spread_bps': round(spread_bps, 2),
                        'reason': f"Spread {spread_bps:.1f} bps exceeds {limit:.0f} bps for {tf or 'default'}"}
            return {'ok': True, 'spread_bps': round(spread_bps, 2), 'reason': f'{spread_bps:.1f} bps'}
        except Exception as e:
            self.logger.debug(f"_check_spread failed for {ticker} (fail-open): {e}")
            return {'ok': True, 'spread_bps': None, 'reason': f'check failed: {e}'}

    def validate_trade_proposal(self, trade_proposal: dict, open_trades: list = None, positions_status: dict = None) -> dict:
        """
        Validates a trade proposal against Sharpe Ratio and Kelly Criterion.
        NOW INCLUDES: Anomaly detection with circuit breaker integration.
        
        Protocol:
        0. Detect anomalies in data (NEW)
        1. Check Sharpe Ratio (Sa > 1.5).
        2. Check Kelly Criterion (f > 0).
        """
        ticker = trade_proposal.get('ticker', 'UNKNOWN')

        # STEP -3: CIRCUIT BREAKER
        if not self.circuit_breaker.can_trade():
            return {'approved': False, 'reason': 'Circuit breaker open — trading paused',
                    'metrics': {}, 'displacement_candidate': None}

        # STEP -2.5: MACRO REGIME GATE
        # Reads market_regime.json (written each scan cycle by ResearchAgent).
        # Gate fires only on confirmed strong trends — RANGING and VOLATILE pass both
        # directions (shadow data: RANGING_SHORT WR=47% vs TRENDING_BULL_SHORT WR=0%).
        # XYZ-* assets are exempt: stock/commodity correlation with BTC 4h is negligible.
        _action = trade_proposal.get('action', 'BUY')
        _is_xyz = str(ticker).startswith('XYZ-')
        if not _is_xyz:
            _regime = self._get_btc_regime()
            if _action == 'BUY' and _regime == 'TRENDING_BEAR':
                self.logger.info(f"[MACRO_GATE] {ticker}: BUY blocked — BTC TRENDING_BEAR")
                return {'approved': False,
                        'reason': 'Macro regime TRENDING_BEAR: long entries blocked',
                        'metrics': {'regime': _regime}, 'displacement_candidate': None}
            if _action == 'SELL' and _regime == 'TRENDING_BULL':
                self.logger.info(f"[MACRO_GATE] {ticker}: SELL blocked — BTC TRENDING_BULL")
                return {'approved': False,
                        'reason': 'Macro regime TRENDING_BULL: short entries blocked',
                        'metrics': {'regime': _regime}, 'displacement_candidate': None}
            self.logger.info(f"[MACRO_GATE] {ticker}: {_action} passes — regime={_regime}")
        else:
            self.logger.info(f"[MACRO_GATE] {ticker}: XYZ asset — BTC regime gate skipped")

        # STEP -2.4: FUNDAMENTAL DIRECTION GATE
        # Negative fundamental score on a LONG = fundamentally weak asset going up.
        # Negative fundamental score on a SHORT = fundamentally weak asset (correct for short).
        _fa = (trade_proposal.get('analyst_signals') or {}).get('fundamental', 0.0)
        if _action == 'BUY' and isinstance(_fa, (int, float)) and _fa < 0:
            self.logger.info(f"[FA_GATE] {ticker}: BUY blocked — FA score {_fa:.3f} < 0")
            return {'approved': False,
                    'reason': f'Fundamental score negative ({_fa:.3f}): long entry blocked',
                    'metrics': {'fa_score': _fa}, 'displacement_candidate': None}

        # STEP -2.3: SENTIMENT GATE
        # Low sentiment on BUY = market narrative against us; analysis shows SA is the
        # strongest discriminator between winners (avg 0.467) and losers (avg 0.394).
        # Only applied to BUY — SELL direction uses inverted SA logic.
        # XYZ stocks/commodities: SA is global macro vibe, not crypto social — lower bar
        SA_MIN_BUY = 0.20 if _is_xyz else 0.35
        _sa = (trade_proposal.get('analyst_signals') or {}).get('sentiment')
        if _action == 'BUY' and isinstance(_sa, (int, float)) and _sa < SA_MIN_BUY:
            self.logger.info(f"[SA_GATE] {ticker}: BUY blocked — SA score {_sa:.3f} < {SA_MIN_BUY}")
            return {'approved': False,
                    'reason': f'Sentiment score too low ({_sa:.3f} < {SA_MIN_BUY}): long entry blocked',
                    'metrics': {'sa_score': _sa}, 'displacement_candidate': None}

        # STEP -2.2: RSI ENTRY FILTER
        # Block entries in overbought/oversold territory — empirically the weakest
        # entry zone for trend-following. XYZ stocks use wider thresholds (70/30)
        # because underlying volatility is lower than crypto (65/35).
        _rsi = (trade_proposal.get('metrics') or {}).get('rsi_1h')
        if isinstance(_rsi, (int, float)) and _rsi > 0:
            _is_stock = str(ticker).startswith('XYZ-')
            _rsi_buy_max  = 70 if _is_stock else 65
            _rsi_sell_min = 30 if _is_stock else 35
            if _action == 'BUY' and _rsi > _rsi_buy_max:
                self.logger.info(
                    f"[RSI_GATE] {ticker}: BUY blocked — RSI {_rsi:.1f} > {_rsi_buy_max} (overbought)"
                )
                return {'approved': False,
                        'reason': f'RSI {_rsi:.1f} overbought (>{_rsi_buy_max}): wacht op pullback',
                        'metrics': {'rsi_1h': _rsi}, 'displacement_candidate': None}
            if _action == 'SELL' and _rsi < _rsi_sell_min:
                self.logger.info(
                    f"[RSI_GATE] {ticker}: SELL blocked — RSI {_rsi:.1f} < {_rsi_sell_min} (oversold)"
                )
                return {'approved': False,
                        'reason': f'RSI {_rsi:.1f} oversold (<{_rsi_sell_min}): wacht op bounce',
                        'metrics': {'rsi_1h': _rsi}, 'displacement_candidate': None}

        # STEP -2: SPREAD GATE
        # Illiquide perps (bv. Hyperliquid XYZ-* RWA) hebben spreads van 30-150 bps.
        # Round-trip eet dan >0.6% vóór je edge realiseert. Setup-aware threshold.
        spread_check = self._check_spread(ticker, trade_proposal.get('timeframe'))
        if not spread_check['ok']:
            return {'approved': False, 'reason': spread_check['reason'],
                    'metrics': {'spread_bps': spread_check.get('spread_bps')},
                    'displacement_candidate': None}

        # STEP -1.7: CORRELATION GATE
        # Block trades that would stack correlated same-direction exposure.
        # Fail-open on missing tracker or unknown correlation (don't block on ignorance).
        if open_trades and self.correlation_tracker is not None:
            try:
                _live = [t for t in open_trades if t.get('status') in ('OPEN', 'PLACED')]
                if _live:
                    _corr = self.correlation_tracker.weighted_exposure_correlation(
                        new_ticker=ticker,
                        new_direction=(trade_proposal.get('action') or 'BUY'),
                        open_positions=_live,
                    )
                    if abs(_corr.get('weighted_corr', 0.0)) > self.correlation_max:
                        self.logger.info(
                            f"[CORRELATION_GATE] {ticker}: blocked — weighted_corr="
                            f"{_corr['weighted_corr']:.2f} > {self.correlation_max} "
                            f"(ref={_corr['reference_ticker']}, max={_corr['max_corr']:.2f})"
                        )
                        return {'approved': False,
                                'reason': (f"Correlation cap: weighted {_corr['weighted_corr']:.2f} "
                                           f"vs open positions > {self.correlation_max} "
                                           f"(ref {_corr['reference_ticker']})"),
                                'metrics': {'weighted_corr': _corr['weighted_corr'],
                                            'max_corr': _corr['max_corr'],
                                            'reference_ticker': _corr['reference_ticker']},
                                'displacement_candidate': None}
            except Exception as e:
                self.logger.debug(f"Correlation gate failed for {ticker} (fail-open): {e}")

        # STEP -1.5: SETUP CONCURRENCY CAP
        # Swings bind margin for days — reserve portfolio slots for faster setups.
        # Caps are split per asset class: XYZ-* tickers = macro (equities/commodities/indices),
        # everything else = crypto. Separate pools prevent crypto volume from blocking equity entries.
        if open_trades is not None:
            _proposed_tf = (trade_proposal.get('timeframe') or '').strip()
            SETUP_MAX_CONCURRENT = {
                "4h Swing": {"crypto": 1, "macro": 1},
                "1h Macro": {"crypto": 3, "macro": 3},
            }
            if _proposed_tf in SETUP_MAX_CONCURRENT:
                _asset_cls = "macro" if (ticker or "").split("/")[0].startswith("XYZ-") else "crypto"
                _cap = SETUP_MAX_CONCURRENT[_proposed_tf][_asset_cls]
                _live = [t for t in open_trades
                         if t.get('status') in ('OPEN', 'PLACED')
                         and (t.get('timeframe') or '').strip() == _proposed_tf
                         and (("macro" if (t.get('ticker') or "").split("/")[0].startswith("XYZ-") else "crypto") == _asset_cls)]
                if len(_live) >= _cap:
                    self.logger.info(
                        f"[SETUP_CAP] {ticker}: blocked — {len(_live)} {_proposed_tf} ({_asset_cls}) already open "
                        f"(cap {_cap})"
                    )
                    return {'approved': False,
                            'reason': f"{_proposed_tf} concurrency cap ({_cap}) reached",
                            'metrics': {}, 'displacement_candidate': None}

        # STEP -1: PORTFOLIO CAPACITY
        if open_trades is not None:
            capacity = self.check_portfolio_capacity(open_trades)
            if not capacity['has_room']:
                conviction = float(trade_proposal.get('conviction', 0.0))
                if conviction < self.displacement_min_conviction:
                    self.logger.info(
                        f"[CAPACITY] {ticker}: blocked — {capacity['reason']} "
                        f"(conviction {conviction:.2f} below displacement threshold {self.displacement_min_conviction})"
                    )
                    return {'approved': False, 'reason': f"Portfolio at capacity: {capacity['reason']}",
                            'metrics': {}, 'displacement_candidate': None}
                candidate = self.find_displacement_candidate(open_trades, positions_status)
                if candidate is None:
                    self.logger.info(f"[CAPACITY] {ticker}: blocked — no weak position to displace")
                    return {'approved': False, 'reason': "Portfolio at capacity, no displacement candidate",
                            'metrics': {}, 'displacement_candidate': None}
                self.logger.info(
                    f"[CAPACITY] {ticker}: will displace {candidate.get('ticker')} "
                    f"(conviction={conviction:.2f} >= {self.displacement_min_conviction})"
                )
                trade_proposal['_displacement_candidate'] = candidate

        # STEP -0.5: PORTFOLIO DRAWDOWN CHECK
        drawdown = self.check_portfolio_drawdown()
        if not drawdown.get("ok", True):
            return {
                'approved': False,
                'reason': drawdown['reason'],
                'metrics': {'drawdown_pct': drawdown['drawdown_pct']},
            }

        # STEP 0: ANOMALY DETECTION (Adversarial Testing)
        anomaly_result = self.detect_anomalies(trade_proposal)
        
        if anomaly_result['has_anomaly']:
            critical_anomalies = [a for a in anomaly_result['anomalies'] if a['severity'] == 'CRITICAL']
            
            if critical_anomalies:
                # CRITICAL anomalies trigger circuit breaker
                self.logger.critical(f"🚨 CRITICAL ANOMALIES DETECTED for {ticker}!")
                for anomaly in critical_anomalies:
                    self.logger.critical(f"  - {anomaly['type']}: {anomaly['detail']}")
                
                # Trigger circuit breaker
                self.circuit_breaker.pause_system(reason=f"CRITICAL anomaly on {ticker}: {critical_anomalies[0]['type']}")
                self.logger.critical("⛔ CIRCUIT BREAKER ACTIVATED - System PAUSED")
                
                # Circuit breaker is triggered - alert logged above
                
                return {
                    "approved": False,
                    "reason": "CRITICAL ANOMALY DETECTED - Circuit Breaker OPEN",
                    "anomalies": anomaly_result['anomalies'],
                    "circuit_breaker": "OPEN",
                    "metrics": {}
                }
            else:
                # Non-critical anomalies: log warning but continue
                self.logger.warning(f"⚠️ Anomalies detected for {ticker} (non-critical):")
                for anomaly in anomaly_result['anomalies']:
                    self.logger.warning(f"  - {anomaly['type']}: {anomaly['detail']}")
        
        # 1. Trade Expectancy Score Check (Replacing Mock Sharpe)
        # Expected Return per risked dollar: E[R] = (Probability of Win * Potential Reward) - (Probability of Loss * 1)
        p = trade_proposal.get('win_probability', 0.5)
        b = trade_proposal.get('net_odds', 1.0)
        
        expectancy_score = (p * b) - ((1 - p) * 1.0)
        
        # 2. Kelly Criterion Check 
        # Queries live exchange balance internally
        kelly_result = self.check_trade_safety(p, b) 
        
        if not kelly_result['safe']:
             return {"approved": False, "reason": "Kelly criterion failed (negative edge)", "metrics": kelly_result}

        # Expectancy must be decidedly positive to approve trade
        # Setting a minimum threshold (e.g., 0.1 means we expect a 10% return on risk over time)
        MIN_EXPECTANCY = 0.1
        
        if expectancy_score < MIN_EXPECTANCY:
             return {
                 "approved": False, 
                 "reason": f"Trade Expectancy Score too low ({expectancy_score:.2f} < {MIN_EXPECTANCY})",
                 "metrics": {"expectancy_score": expectancy_score}
             }
             
        return {
            "approved": True,
            "reason": "All risk checks passed successfully",
            "metrics": {
                "expectancy_score": round(expectancy_score, 2),
                "kelly": kelly_result,
                "anomaly_check": "PASSED" if not anomaly_result['has_anomaly'] else "WARNING"
            }
        }

    async def listen_for_trade_requests(self):
        """
        Placeholder pattern for listening to trade requests.
        In a real scenario, this might consume from a Pub/Sub queue or an Event stream.
        """
        # Example:
        # while True:
        #     request = await get_next_request()
        #     safety = self.check_trade_safety(...)
        pass
