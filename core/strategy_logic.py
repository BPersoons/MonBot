import pandas as pd
import numpy as np
from typing import Tuple, List

class StrategyLogic:
    """
    Centralized logic for Technical Analysis strategies.
    Used by both the Live Agent and the Backtester to ensure consistency.
    """

    @staticmethod
    def calculate_indicators(closes: List[float]) -> dict:
        """
        Calculate indicators manually (without pandas_ta dependency).
        """
        series = pd.Series(closes)
        
        # RSI (14)
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        # EMA (20, 50)
        ema_20 = series.ewm(span=20, adjust=False).mean()
        ema_50 = series.ewm(span=50, adjust=False).mean()
        
        # MACD (12, 26, 9)
        exp1 = series.ewm(span=12, adjust=False).mean()
        exp2 = series.ewm(span=26, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        # Bollinger Bands (20, 2)
        sma_20 = series.rolling(window=20).mean()
        std_20 = series.rolling(window=20).std()
        bb_upper = sma_20 + (std_20 * 2)
        bb_lower = sma_20 - (std_20 * 2)
        
        return {
            'rsi': rsi.fillna(50),
            'ema_20': ema_20.fillna(series),
            'ema_50': ema_50.fillna(series),
            'macd_line': macd_line.fillna(0),
            'macd_signal': signal_line.fillna(0),
            'bb_upper': bb_upper.fillna(series),
            'bb_lower': bb_lower.fillna(series),
            'sma_20': sma_20.fillna(series)
        }

    @staticmethod
    def get_agent_signal(price: float, indicators: dict) -> Tuple[float, str]:
        """
        The Official Agent Strategy.
        Logic:
        - RSI Overbought/Oversold
        - EMA Trend Confirmation
        - Momentum
        """
        rsi = indicators['rsi']
        ema_20 = indicators['ema_20']
        ema_50 = indicators['ema_50']
        
        signal = 0.0
        reasons = []
        
        # RSI
        if rsi > 70:
            signal -= 0.4
            reasons.append(f"RSI overbought ({rsi:.0f})")
        elif rsi > 60:
            signal += 0.2
            reasons.append(f"RSI bullish ({rsi:.0f})")
        elif rsi < 30:
            signal += 0.4
            reasons.append(f"RSI oversold ({rsi:.0f})")
        elif rsi < 40:
            signal -= 0.2
            reasons.append(f"RSI bearish ({rsi:.0f})")
        
        # EMA Trend
        if price > ema_20 > ema_50:
            signal += 0.5
            reasons.append("Bullish EMA crossover")
        elif price > ema_20:
            signal += 0.3
            reasons.append("Price above EMA-20")
        elif price < ema_20 < ema_50:
            signal -= 0.5
            reasons.append("Bearish EMA crossover")
        elif price < ema_20:
            signal -= 0.3
            reasons.append("Price below EMA-20")
            
        # Clamp
        signal = max(-1.0, min(1.0, signal))
        reason = "; ".join(reasons) if reasons else "Neutral"
        
        return signal, reason

    @staticmethod
    def get_macd_signal(indicators: dict, prev_indicators: dict) -> float:
        """
        MACD Crossover Strategy.
        Buy: MACD crosses above Signal
        Sell: MACD crosses below Signal
        """
        macd = indicators['macd_line']
        sig = indicators['macd_signal']
        prev_macd = prev_indicators['macd_line']
        prev_sig = prev_indicators['macd_signal']
        
        # Crossover Up
        if prev_macd < prev_sig and macd > sig:
            return 1.0 # Buy
        # Crossover Down
        if prev_macd > prev_sig and macd < sig:
            return -1.0 # Sell
            
        return 0.0 # Hold

    @staticmethod
    def get_bollinger_signal(price: float, indicators: dict) -> float:
        """
        Bollinger Mean Reversion.
        Buy: Price touches Lower Band
        Sell: Price touches Upper Band
        """
        if price <= indicators['bb_lower']:
            return 1.0 # Buy
        if price >= indicators['bb_upper']:
            return -1.0 # Sell
        return 0.0
