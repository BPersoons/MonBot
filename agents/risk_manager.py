import logging
import os
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
                bankroll = self.exchange_client.get_balance()
                self.logger.info(f"Fetched live USDC balance: ${bankroll:.2f}")
            else:
                self.logger.warning("No exchange client or bankroll provided. Defaulting to $0.0 to block trade.")
                bankroll = 0.0

        if net_odds <= 0:
            return {"safe": False, "reason": "Net odds must be positive", "recommended_size": 0.0}
        
        p = win_probability
        q = 1.0 - p
        b = net_odds

        # Kelly Criterion Calculation
        kelly_fraction = (b * p - q) / b

        # Safety constraints
        # Often we use "Half Kelly" or a fraction of Kelly to be safer
        # But per spec, we implement the raw calculation first.
        
        is_safe = kelly_fraction > 0
        recommended_size = 0.0
        
        if is_safe:
            recommended_size = kelly_fraction * bankroll
            max_size = bankroll * self.max_position_pct
            if recommended_size > max_size:
                self.logger.info(
                    f"Kelly size ${recommended_size:.2f} capped to ${max_size:.2f} "
                    f"({self.max_position_pct*100:.0f}% of ${bankroll:.2f} balance)"
                )
                recommended_size = max_size

        result = {
            "safe": is_safe,
            "kelly_fraction": round(kelly_fraction, 4),
            "recommended_size": round(recommended_size, 2),
            "details": {
                "p": p,
                "b": b,
                "q": q
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
                self.circuit_breaker.pause_system()
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
