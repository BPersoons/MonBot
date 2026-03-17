import ccxt
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime

class TechnicalAnalyst:
    """
    Technical Analyst Agent — Multi-Timeframe, Multi-Indicator scoring.
    
    Uses 5 research-backed indicators with evidence-based weights:
      MACD (0.30)  — Strongest trend+momentum signal (77-86% win rate in crypto)
      RSI  (0.25)  — Highest individual win rate in comparative studies
      EMA  (0.20)  — Reliable trend direction + drawdown control
      BB   (0.15)  — Best net profit in comparative study
      VOL  (0.10)  — Confirmation indicator, validates breakouts
    
    Each indicator outputs ±1.0, weighted sum gives per-timeframe score in full ±1.0 range.
    Multi-timeframe (4h/1h/15m) scores are then weighted for the final signal.
    """

    # Evidence-based indicator weights (crypto backtest research)
    INDICATOR_WEIGHTS = {
        'macd':   0.30,  # MACD+RSI combo: 77-86% win rate (Kraken research)
        'rsi':    0.25,  # Highest individual win rate (LUT.fi study)
        'ema':    0.20,  # EMA crossover outperforms buy-and-hold on drawdown
        'bb':     0.15,  # Best net profit (comparative study, 285% on BTC/7.5yr)
        'volume': 0.10,  # Confirmation — validates breakouts, reduces false signals
    }

    # Multi-timeframe weights
    TF_WEIGHTS = {'4h': 0.5, '1h': 0.3, '15m': 0.2}

    def __init__(self, exchange_id='hyperliquid', symbol='BTC/USDC'):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.logger = logging.getLogger("TechnicalAnalyst")
        # Use MAINNET for analysis data (real volume/prices), even if trading on Testnet
        # Hyperliquid CCXT default is mainnet

    def fetch_data(self, timeframe='1h', limit=100):
        """Fetches OHLCV data from the exchange. Stateless — fresh instance each call."""
        try:
            sym = self.symbol.replace('/USDT', '/USDC')
            # Hyperliquid swap symbols in CCXT require the ':USDC' suffix (e.g., 'XRP/USDC:USDC')
            if self.exchange_id == 'hyperliquid' and ':' not in sym:
                sym = f"{sym}:USDC"
                
            exchange = ccxt.hyperliquid({'options': {'defaultType': 'swap'}})
            ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            self.logger.error(f"Error fetching data for {self.symbol} ({timeframe}): {e}")
            return None

    def calculate_indicators(self, df):
        """Calculates all 5 technical indicators: RSI, EMA, MACD, Bollinger Bands, Volume trend."""
        if df is None or df.empty or len(df) < 50:
            return None

        # --- RSI (Wilder's Smoothing via EWM) ---
        window_length = 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/window_length, min_periods=window_length, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/window_length, min_periods=window_length, adjust=False).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # --- EMA (20 & 50) ---
        df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()

        # --- MACD (12, 26, 9) ---
        df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd_line'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd_line'] - df['macd_signal']

        # --- Bollinger Bands (20, 2) ---
        df['bb_mid'] = df['close'].rolling(window=20).mean()
        df['bb_std'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_mid'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_mid'] - (df['bb_std'] * 2)
        # %B = (price - lower) / (upper - lower), ranges ~0 to ~1
        bb_range = df['bb_upper'] - df['bb_lower']
        df['bb_pct_b'] = np.where(bb_range > 0, (df['close'] - df['bb_lower']) / bb_range, 0.5)

        # --- Volume Trend (SMA ratio) ---
        df['vol_sma_20'] = df['volume'].rolling(window=20).mean()
        df['vol_ratio'] = np.where(df['vol_sma_20'] > 0, df['volume'] / df['vol_sma_20'], 1.0)

        return df

    def _score_macd(self, latest, prev):
        """MACD signal cross scoring. ±1.0 range."""
        macd = latest['macd_line']
        signal = latest['macd_signal']
        prev_macd = prev['macd_line']
        prev_signal = prev['macd_signal']
        
        # Fresh crossover = strongest signal
        if prev_macd <= prev_signal and macd > signal:
            return 1.0  # Bullish crossover
        elif prev_macd >= prev_signal and macd < signal:
            return -1.0  # Bearish crossover
        
        # Already above/below = moderate signal
        if macd > signal:
            # Scale by histogram strength (0.3 to 0.7)
            hist_strength = min(abs(latest['macd_histogram']) / (abs(latest['close']) * 0.001 + 1e-10), 1.0)
            return 0.3 + (0.4 * hist_strength)
        else:
            hist_strength = min(abs(latest['macd_histogram']) / (abs(latest['close']) * 0.001 + 1e-10), 1.0)
            return -(0.3 + (0.4 * hist_strength))

    def _score_rsi(self, rsi_value):
        """RSI zone scoring. ±1.0 range."""
        if rsi_value > 80:
            return -1.0  # Extremely overbought
        elif rsi_value > 70:
            return -0.7  # Overbought
        elif rsi_value < 20:
            return 1.0   # Extremely oversold (bounce likely)
        elif rsi_value < 30:
            return 0.7   # Oversold
        elif rsi_value > 60:
            return -0.3  # Mild bearish momentum
        elif rsi_value < 40:
            return 0.3   # Mild bullish momentum (accumulation zone)
        else:
            # 40-60: neutral, slight lean based on exact position
            return (50 - rsi_value) / 50.0 * 0.2  # Very small signal

    def _score_ema(self, latest):
        """EMA 20/50 cross scoring. ±1.0 range."""
        ema20 = latest['ema_20']
        ema50 = latest['ema_50']
        price = latest['close']
        
        if ema20 > ema50:
            # In uptrend — score based on how strong
            spread_pct = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
            if price > ema20:
                return min(0.5 + spread_pct * 0.1, 1.0)  # Price above both EMAs
            else:
                return 0.3  # EMA bullish but price pulling back
        else:
            spread_pct = (ema50 - ema20) / ema50 * 100 if ema50 > 0 else 0
            if price < ema20:
                return max(-(0.5 + spread_pct * 0.1), -1.0)  # Price below both EMAs
            else:
                return -0.3  # EMA bearish but price bouncing

    def _score_bollinger(self, latest):
        """Bollinger %B scoring. ±1.0 range."""
        pct_b = latest['bb_pct_b']
        
        if pct_b < 0.0:
            return 1.0   # Below lower band — strong oversold/bounce signal
        elif pct_b < 0.2:
            return 0.7   # Near lower band
        elif pct_b > 1.0:
            return -1.0  # Above upper band — strong overbought
        elif pct_b > 0.8:
            return -0.7  # Near upper band
        else:
            # Middle zone: slight lean based on position relative to midpoint
            return (0.5 - pct_b) * 0.6  # ±0.3 max in neutral zone

    def _score_volume(self, latest):
        """Volume trend scoring. ±1.0 range (direction-agnostic, confirms moves)."""
        ratio = latest['vol_ratio']
        
        if ratio > 2.0:
            return 1.0   # Very strong volume surge — confirms current direction
        elif ratio > 1.5:
            return 0.7
        elif ratio > 1.1:
            return 0.3
        elif ratio < 0.5:
            return -0.7  # Very low volume — trend weakening  
        elif ratio < 0.7:
            return -0.3
        else:
            return 0.0   # Normal volume

    def analyze_signal(self, df):
        """
        Generates a composite technical signal score (-1.0 to 1.0).
        Uses 5 weighted indicators, each scored ±1.0.
        """
        if df is None or len(df) < 2:
            return 0.0, "No Data", {}

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Score each indicator
        scores = {
            'macd':   self._score_macd(latest, prev),
            'rsi':    self._score_rsi(latest['rsi']),
            'ema':    self._score_ema(latest),
            'bb':     self._score_bollinger(latest),
            'volume': self._score_volume(latest),
        }
        
        # Weighted combination
        composite = sum(scores[k] * self.INDICATOR_WEIGHTS[k] for k in scores)
        composite = max(min(composite, 1.0), -1.0)
        
        # Trend label
        if composite > 0.3:
            trend = "Bullish"
        elif composite < -0.3:
            trend = "Bearish"
        else:
            trend = "Neutral"
        
        # Detailed breakdown string
        parts = []
        for k, v in scores.items():
            label = "+" if v > 0 else ""
            parts.append(f"{k.upper()}:{label}{v:.1f}")
        detail_str = f"{trend} ({', '.join(parts)})"
        
        return composite, detail_str, scores

    async def analyze_async(self, ticker=None, catalyst="TA_BACKTEST"):
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker, catalyst)

    def analyze(self, ticker=None, catalyst="TA_BACKTEST"):
        """Standardized interface for Project Lead. Multi-Timeframe Analysis with 5 indicators."""
        if ticker:
            self.symbol = ticker.replace('/USDT', '/USDC')
        
        self.logger.info(f"Analyzing {self.symbol} (MTF with 5 indicators)... Catalyst: {catalyst}")
        
        # Adjust timeframe weights based on the discovery catalyst (The Handshake)
        active_tf_weights = self.TF_WEIGHTS.copy()
        if catalyst == "NEWS_SENTIMENT":
            self.logger.info(f"News catalyst detected for {self.symbol}. Shifting TA weights to favor short-term momentum (15m).")
            active_tf_weights = {'4h': 0.1, '1h': 0.3, '15m': 0.6}
            
        combined_score = 0.0
        details = []
        latest_price = 0.0
        current_rsi = 0.0
        
        tf_data = {}
        
        for tf in ['4h', '1h', '15m']:
            df = self.fetch_data(timeframe=tf)
            df = self.calculate_indicators(df)
            
            if df is not None and len(df) >= 50:
                score, trend_str, indicator_scores = self.analyze_signal(df)
                combined_score += score * active_tf_weights[tf]
                
                latest = df.iloc[-1]
                if tf == '1h':
                    latest_price = latest['close']
                    current_rsi = latest['rsi']
                
                tf_data[tf] = {
                    "signal": "BULLISH" if score > 0.2 else "BEARISH" if score < -0.2 else "NEUTRAL",
                    "score": round(score, 3),
                    "trend": trend_str,
                    "indicators": {k: round(v, 2) for k, v in indicator_scores.items()}
                }
                details.append(f"{tf}: {trend_str} (Score: {score:.2f})")
            else:
                tf_data[tf] = {"signal": "NO_DATA", "score": 0.0, "indicators": {}}
                details.append(f"{tf}: No Data")
                
        reason_str = " | ".join(details)
        
        return {
            "ticker": self.symbol,
            "signal": round(combined_score, 3),
            "reason": f"MTF Score {combined_score:.2f} [{reason_str}]",
            "timeframes": tf_data,
            "price": latest_price,
            "metrics": {"rsi_1h": round(current_rsi, 1) if current_rsi else 0},
            "summary": f"Tech: {combined_score:+.2f} across 3 TFs, 5 indicators"
        }

    def run_analysis(self):
        """Standalone analysis for debugging."""
        print(f"Analyzing {self.symbol}...")
        result = self.analyze()
        
        print("\n--- Technical Analysis Report ---")
        print(f"Ticker: {result['ticker']}")
        print(f"Price:  ${result['price']:.2f}")
        print(f"Signal: {result['signal']:.3f}")
        print(f"RSI:    {result['metrics']['rsi_1h']:.1f}")
        print(f"\nTimeframe Breakdown:")
        for tf, data in result['timeframes'].items():
            print(f"  {tf}: {data['signal']} (score: {data['score']:.3f})")
            if data.get('indicators'):
                for ind, val in data['indicators'].items():
                    print(f"    {ind}: {val:+.2f}")
        
        return result

if __name__ == "__main__":
    analyst = TechnicalAnalyst()
    analyst.run_analysis()
