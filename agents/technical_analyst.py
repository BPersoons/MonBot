import ccxt
import pandas as pd
import numpy as np
import time
import logging
import threading
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# Shared, rate-limited exchange + short-TTL OHLCV cache.
#
# fetch_data previously built a fresh ccxt.hyperliquid() on EVERY call, which
# reloaded the whole HL market list (~11.6s) per fetch and bypassed rate limiting
# → 429s → empty fetches → XYZ TA scored 0.00 ("0 rows after filter") and every
# cycle crawled. One shared instance (markets loaded once, enableRateLimit) is
# ~33x faster and eliminates the 429s. Validated 2026-06-07.
# ──────────────────────────────────────────────────────────────────────────────
_EXCHANGE = None
_INIT_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()            # serialize fetches (thread-safety + rate limit)
_OHLCV_CACHE = {}                         # (symbol, timeframe, limit) -> (epoch, DataFrame)
_OHLCV_CACHE_LOCK = threading.Lock()
_OHLCV_TTL = {'1d': 1800, '4h': 900, '1h': 300, '15m': 120}  # seconds


def _get_shared_exchange():
    """Lazily build one ccxt.hyperliquid() with markets loaded once + rate limiting."""
    global _EXCHANGE
    if _EXCHANGE is None:
        with _INIT_LOCK:
            if _EXCHANGE is None:
                ex = ccxt.hyperliquid({'options': {'defaultType': 'swap'},
                                       'enableRateLimit': True})
                ex.load_markets()
                _EXCHANGE = ex
    return _EXCHANGE


def get_ohlcv_df(symbol, timeframe='1h', limit=600):
    """Module-level cached OHLCV fetch for non-TA callers (e.g. the directional
    rule-direction source in ProjectLead). Reuses the shared exchange + TTL cache
    so it does not add a second network round-trip per candidate within the TTL.

    Returns a DataFrame with columns [timestamp, open, high, low, close, volume],
    or None on hard failure (serves stale cache if present).
    """
    sym = symbol.replace('/USDT', '/USDC')
    if ':' not in sym:
        sym = f"{sym}:USDC"
    cache_key = (sym, timeframe, limit)
    ttl = _OHLCV_TTL.get(timeframe, 300)
    now = time.time()
    with _OHLCV_CACHE_LOCK:
        hit = _OHLCV_CACHE.get(cache_key)
        if hit and (now - hit[0]) < ttl:
            return hit[1].copy()
    for attempt in range(3):
        try:
            exchange = _get_shared_exchange()
            with _FETCH_LOCK:
                ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            with _OHLCV_CACHE_LOCK:
                _OHLCV_CACHE[cache_key] = (now, df)
            return df
        except ccxt.RateLimitExceeded:
            time.sleep(2 * (attempt + 1))
        except Exception:
            break
    with _OHLCV_CACHE_LOCK:
        hit = _OHLCV_CACHE.get(cache_key)
    return hit[1].copy() if hit else None


class TechnicalAnalyst:
    """
    Technical Analyst Agent — Multi-Timeframe, Multi-Indicator scoring.

    Uses 7 research-backed indicators with evidence-based weights:
      MACD  (0.22) — Strongest trend+momentum signal (77-86% win rate in crypto)
      RSI   (0.18) — Highest individual win rate in comparative studies
      EMA   (0.17) — Reliable trend direction + drawdown control
      BB    (0.13) — Best net profit in comparative study
      ADX   (0.12) — Trend strength filter, reduces false breakouts
      STOCH (0.10) — Fast reversal detection, complements RSI
      VOL   (0.08) — Confirmation indicator, validates breakouts

    Each indicator outputs ±1.0, weighted sum gives per-timeframe score in full ±1.0 range.
    Multi-timeframe (4h/1h/15m) scores are then weighted for the final signal.
    """

    INDICATOR_WEIGHTS = {
        'macd':       0.22,
        'rsi':        0.18,
        'ema':        0.17,
        'bb':         0.13,
        'adx':        0.12,  # Trend strength — prevents false breakout signals in choppy markets
        'stochastic': 0.10,  # Fast reversal detection — catches turns 1-2 candles before RSI
        'volume':     0.08,
    }

    # Mean-reversion weights for RANGING regime: RSI and BB dominate.
    # MACD and EMA are trend/momentum indicators — noisy in sideways markets.
    # ADX is near-zero in RANGING by definition; its weight is slashed to avoid wasted computation.
    MEAN_REVERSION_WEIGHTS = {
        'macd':       0.08,
        'rsi':        0.32,
        'ema':        0.08,
        'bb':         0.28,
        'adx':        0.04,
        'stochastic': 0.13,
        'volume':     0.07,
    }

    # Commodity weights: EMA ribbon and ADX are primary; RSI/BB secondary.
    # Backtest evidence: EMA ribbon + Supertrend + ADX outperform in commodity trends.
    COMMODITY_WEIGHTS = {
        'macd':       0.15,
        'rsi':        0.10,
        'ema':        0.28,  # EMA ribbon is the primary long signal
        'bb':         0.09,
        'adx':        0.22,  # ADX critical — commodities trend hard or chop
        'stochastic': 0.08,
        'volume':     0.08,
    }

    # Multi-timeframe weights
    TF_WEIGHTS    = {'4h': 0.5,  '1h': 0.3,  '15m': 0.2}
    # Swing bias: lean heavy on 4h so higher-timeframe trend dominates scoring.
    SWING_WEIGHTS = {'4h': 0.75, '1h': 0.20, '15m': 0.05}

    def __init__(self, exchange_id='hyperliquid', symbol='BTC/USDC'):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.logger = logging.getLogger("TechnicalAnalyst")
        # Use MAINNET for analysis data (real volume/prices), even if trading on Testnet
        # Hyperliquid CCXT default is mainnet

    def fetch_data(self, timeframe='1h', limit=100):
        """Fetch OHLCV via the shared rate-limited exchange + short-TTL cache.

        Avoids the per-call market reload (~11.6s) and 429 rate limits that starved
        the XYZ TA and slowed every cycle. On hard failure serves stale cache rather
        than None, so a transient blip no longer zeroes a whole timeframe.
        """
        sym = self.symbol.replace('/USDT', '/USDC')
        # Hyperliquid swap symbols in CCXT require the ':USDC' suffix (e.g., 'XRP/USDC:USDC')
        if self.exchange_id == 'hyperliquid' and ':' not in sym:
            sym = f"{sym}:USDC"

        cache_key = (sym, timeframe, limit)
        ttl = _OHLCV_TTL.get(timeframe, 300)
        now = time.time()

        with _OHLCV_CACHE_LOCK:
            hit = _OHLCV_CACHE.get(cache_key)
            if hit and (now - hit[0]) < ttl:
                return hit[1].copy()

        for attempt in range(3):
            try:
                exchange = _get_shared_exchange()
                with _FETCH_LOCK:
                    ohlcv = exchange.fetch_ohlcv(sym, timeframe=timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                with _OHLCV_CACHE_LOCK:
                    _OHLCV_CACHE[cache_key] = (now, df)
                return df
            except ccxt.RateLimitExceeded:
                time.sleep(2 * (attempt + 1))
            except Exception as e:
                self.logger.error(f"Error fetching data for {self.symbol} ({timeframe}): {e}")
                break

        # Retries/error exhausted — serve stale cache if available, else None.
        with _OHLCV_CACHE_LOCK:
            hit = _OHLCV_CACHE.get(cache_key)
        return hit[1].copy() if hit else None

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

        # --- EMA (20, 50, 200) ---
        df['ema_20']  = df['close'].ewm(span=20,  adjust=False).mean()
        df['ema_50']  = df['close'].ewm(span=50,  adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()

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

        # --- ADX (Average Directional Index, 14-period) ---
        adx_period = 14
        prev_high = df['high'].shift(1)
        prev_low = df['low'].shift(1)
        prev_close = df['close'].shift(1)

        tr = pd.concat([
            df['high'] - df['low'],
            (df['high'] - prev_close).abs(),
            (df['low'] - prev_close).abs()
        ], axis=1).max(axis=1)

        plus_dm = np.where(
            (df['high'] - prev_high > prev_low - df['low']) & (df['high'] - prev_high > 0),
            df['high'] - prev_high, 0.0
        )
        minus_dm = np.where(
            (prev_low - df['low'] > df['high'] - prev_high) & (prev_low - df['low'] > 0),
            prev_low - df['low'], 0.0
        )

        atr_smooth = pd.Series(tr, index=df.index).ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()
        plus_dm_smooth = pd.Series(plus_dm, index=df.index).ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()
        minus_dm_smooth = pd.Series(minus_dm, index=df.index).ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()

        df['atr'] = atr_smooth  # Store ATR for volatility-based stop loss
        atr_safe = atr_smooth.replace(0, 1e-10)
        df['plus_di'] = 100 * plus_dm_smooth / atr_safe
        df['minus_di'] = 100 * minus_dm_smooth / atr_safe
        di_sum = df['plus_di'] + df['minus_di']
        di_sum_safe = di_sum.replace(0, 1e-10)
        dx = 100 * (df['plus_di'] - df['minus_di']).abs() / di_sum_safe
        df['adx'] = dx.ewm(alpha=1/adx_period, min_periods=adx_period, adjust=False).mean()

        # --- Stochastic Oscillator (9, 3, 3) ---
        stoch_k_period = 9
        low_min = df['low'].rolling(window=stoch_k_period).min()
        high_max = df['high'].rolling(window=stoch_k_period).max()
        stoch_range = high_max - low_min
        df['stoch_k_raw'] = np.where(stoch_range > 0, 100 * (df['close'] - low_min) / stoch_range, 50.0)
        df['stoch_k'] = pd.Series(df['stoch_k_raw'], index=df.index).rolling(window=3).mean()  # Smoothed %K
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()  # %D signal line

        return df

    def _score_macd(self, latest, prev, direction="LONG"):
        """MACD signal cross scoring. ±1.0 range. Direction-aware."""
        macd = latest['macd_line']
        signal = latest['macd_signal']
        prev_macd = prev['macd_line']
        prev_signal = prev['macd_signal']

        # Fresh crossover = strongest signal
        if prev_macd <= prev_signal and macd > signal:
            raw = 1.0  # Bullish crossover
        elif prev_macd >= prev_signal and macd < signal:
            raw = -1.0  # Bearish crossover
        elif macd > signal:
            # Already above = moderate bullish signal, scale by histogram strength
            hist_strength = min(abs(latest['macd_histogram']) / (abs(latest['close']) * 0.001 + 1e-10), 1.0)
            raw = 0.3 + (0.4 * hist_strength)
        else:
            hist_strength = min(abs(latest['macd_histogram']) / (abs(latest['close']) * 0.001 + 1e-10), 1.0)
            raw = -(0.3 + (0.4 * hist_strength))

        # For SHORT: invert — bearish MACD confirms SHORT, bullish MACD hurts SHORT
        return raw if direction == "LONG" else -raw

    def _score_rsi(self, rsi_value, direction="LONG"):
        """RSI zone scoring. ±1.0 range. Narrowed neutral zone (45-55) with gradients.

        Convention (both directions): positive = confirms the trade direction, negative = hurts it.
        SHORT: low RSI = bearish momentum = +score. High RSI = squeeze risk = -score.
        """
        if direction == "SHORT":
            # Positive = confirms SHORT (bearish momentum), negative = squeeze/reversal risk
            if rsi_value < 20:   return  1.0   # Extreme momentum down — confirms SHORT
            elif rsi_value < 30: return  0.7   # Strong momentum down
            elif rsi_value > 80: return -1.0   # Extremely overbought — squeeze risk (bad for SHORT)
            elif rsi_value > 70: return -0.7   # Overbought — reversal risk
            elif rsi_value < 45:
                # Gradient 20→45: momentum building (positive SHORT signal)
                return 0.1 + (45 - rsi_value) / 15.0 * 0.4
            elif rsi_value > 55:
                # Gradient 55→70: reversal risk building (negative SHORT signal)
                return -(0.1 + (rsi_value - 55) / 15.0 * 0.4)
            else:
                # 45-55 true neutral: tiny lean toward SHORT (below midpoint = slight bear)
                return (50 - rsi_value) / 50.0 * 0.1
        # LONG:
        if rsi_value > 80:
            return -1.0  # Extremely overbought
        elif rsi_value > 70:
            return -0.7  # Overbought
        elif rsi_value < 20:
            return 1.0   # Extremely oversold (bounce likely)
        elif rsi_value < 30:
            return 0.7   # Oversold
        elif rsi_value > 55:
            # Gradient 55→70: 0.1→0.5 (bullish momentum building)
            return 0.1 + (rsi_value - 55) / 15.0 * 0.4
        elif rsi_value < 45:
            # Gradient 30→45: 0.5→0.1 (accumulation fading)
            return 0.1 + (45 - rsi_value) / 15.0 * 0.4
        else:
            # 45-55 true neutral: tiny lean
            return (50 - rsi_value) / 50.0 * 0.1

    def _score_ema(self, latest, direction="LONG"):
        """EMA 20/50 cross scoring. ±1.0 range. Direction-aware."""
        ema20 = latest['ema_20']
        ema50 = latest['ema_50']
        price = latest['close']

        if ema20 > ema50:
            spread_pct = (ema20 - ema50) / ema50 * 100 if ema50 > 0 else 0
            if price > ema20:
                raw = min(0.5 + spread_pct * 0.1, 1.0)  # Price above both EMAs
            else:
                raw = 0.3  # EMA bullish but price pulling back
        else:
            spread_pct = (ema50 - ema20) / ema50 * 100 if ema50 > 0 else 0
            if price < ema20:
                raw = max(-(0.5 + spread_pct * 0.1), -1.0)  # Price below both EMAs
            else:
                raw = -0.3  # EMA bearish but price bouncing

        # For SHORT: invert — downtrend EMA confirms SHORT, uptrend EMA hurts SHORT
        return raw if direction == "LONG" else -raw

    def _score_bollinger(self, latest, direction="LONG"):
        """Bollinger %B scoring. ±1.0 range."""
        pct_b = latest['bb_pct_b']

        if direction == "SHORT":
            # Convention: positive = confirms SHORT, negative = squeeze/reversal risk.
            if pct_b < 0.0:   return  1.0   # Breaking below lower band — confirms SHORT
            elif pct_b < 0.2: return  0.7   # Near lower band — bearish continuation
            elif pct_b > 1.0: return -1.0   # Above upper band — squeeze risk (bad for SHORT)
            elif pct_b > 0.8: return -0.7   # Near upper band — reversal risk
            else: return (0.5 - pct_b) * 0.6  # Middle zone: below midpoint leans SHORT (positive)
        # LONG (existing logic):
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

    def _score_volume(self, latest, direction="LONG"):
        """Volume trend scoring. ±1.0 range. Direction + candle-aware."""
        ratio = latest['vol_ratio']

        # Low volume = weak trend regardless of direction
        if ratio < 0.5:
            return -0.7
        elif ratio < 0.7:
            return -0.3
        elif ratio <= 1.1:
            return 0.0  # Normal volume

        # High volume: magnitude depends on surge strength
        if ratio > 2.0:
            magnitude = 1.0
        elif ratio > 1.5:
            magnitude = 0.7
        else:
            magnitude = 0.3

        # Determine candle direction to assign sign
        candle_bullish = latest['close'] >= latest['open']
        if direction == "LONG":
            return magnitude if candle_bullish else -magnitude
        else:  # SHORT
            return magnitude if not candle_bullish else -magnitude

    def _score_adx(self, latest, direction="LONG"):
        """ADX trend strength scoring. ±1.0 range. Direction-aware via DI lines."""
        adx = latest.get('adx', 0)
        plus_di = latest.get('plus_di', 0)
        minus_di = latest.get('minus_di', 0)

        if pd.isna(adx) or adx < 20:
            return 0.0  # Ranging/choppy — no directional conviction

        # Determine trend direction from DI lines
        trend_bullish = plus_di > minus_di

        if adx > 40:
            strength = 1.0  # Very strong trend
        elif adx > 30:
            strength = 0.7
        elif adx > 25:
            strength = 0.4
        else:  # 20-25
            strength = 0.2

        if direction == "LONG":
            return strength if trend_bullish else -strength
        else:  # SHORT
            return strength if not trend_bullish else -strength

    def _score_stochastic(self, latest, prev, direction="LONG"):
        """Stochastic Oscillator (9,3,3) scoring. ±1.0 range. Direction-aware."""
        k = latest.get('stoch_k', 50)
        d = latest.get('stoch_d', 50)
        prev_k = prev.get('stoch_k', 50)
        prev_d = prev.get('stoch_d', 50)

        if pd.isna(k) or pd.isna(d) or pd.isna(prev_k) or pd.isna(prev_d):
            return 0.0

        cross_up = prev_k <= prev_d and k > d
        cross_down = prev_k >= prev_d and k < d

        if direction == "LONG":
            if k < 20 and cross_up:    return 1.0   # Oversold bullish crossover
            elif k < 20:               return 0.7   # Oversold, waiting for cross
            elif k > 80 and cross_down: return -1.0  # Overbought bearish crossover
            elif k > 80:               return -0.7  # Overbought
            elif cross_up:             return 0.4   # Mid-range bullish cross
            elif cross_down:           return -0.4  # Mid-range bearish cross
            else:                      return (50 - k) / 100.0 * 0.3
        else:  # SHORT
            if k > 80 and cross_down:   return 1.0   # Overbought bearish cross confirms SHORT
            elif k > 80:               return 0.7
            elif k < 20 and cross_up:   return -1.0  # Oversold bullish cross = bad for SHORT
            elif k < 20:               return -0.7
            elif cross_down:           return 0.4
            elif cross_up:             return -0.4
            else:                      return (k - 50) / 100.0 * 0.3

    def analyze_signal(self, df, direction="LONG", regime="TRENDING", asset_class="crypto"):
        """
        Generates a composite technical signal score (-1.0 to 1.0).
        Uses 7 weighted indicators, each scored ±1.0.

        regime="RANGING" switches to MEAN_REVERSION_WEIGHTS (RSI+BB dominant).
        asset_class="commodity" switches to COMMODITY_WEIGHTS (EMA+ADX dominant).
        EMA200 regime gate: score boosted when aligned, penalised when fighting the macro trend.
        """
        if df is None or len(df) < 2:
            return 0.0, "No Data", {}

        if regime == "RANGING":
            weights = self.MEAN_REVERSION_WEIGHTS
        elif asset_class == "commodity":
            weights = self.COMMODITY_WEIGHTS
        else:
            weights = self.INDICATOR_WEIGHTS
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Score each indicator (all direction-aware)
        # In RANGING mean-reversion mode for SHORT: RSI and BB use inverted LONG logic.
        # Overbought (RSI>70, %B>0.8) is a SHORT ENTRY in MR, not squeeze risk.
        # This mirrors the LONG MR logic where oversold is an entry — both extremes revert.
        # MACD/EMA/Stoch/Volume keep their normal SHORT logic (directional confirmation).
        if regime == "RANGING" and direction == "SHORT":
            scores = {
                'macd':       self._score_macd(latest, prev, direction="SHORT"),
                'rsi':        -self._score_rsi(latest['rsi'], direction="LONG"),
                'ema':        self._score_ema(latest, direction="SHORT"),
                'bb':         -self._score_bollinger(latest, direction="LONG"),
                'adx':        self._score_adx(latest, direction="SHORT"),
                'stochastic': self._score_stochastic(latest, prev, direction="SHORT"),
                'volume':     self._score_volume(latest, direction="SHORT"),
            }
        else:
            scores = {
                'macd':       self._score_macd(latest, prev, direction=direction),
                'rsi':        self._score_rsi(latest['rsi'], direction=direction),
                'ema':        self._score_ema(latest, direction=direction),
                'bb':         self._score_bollinger(latest, direction=direction),
                'adx':        self._score_adx(latest, direction=direction),
                'stochastic': self._score_stochastic(latest, prev, direction=direction),
                'volume':     self._score_volume(latest, direction=direction),
            }

        # Weighted combination
        composite = sum(scores[k] * weights[k] for k in scores)

        # ADX confidence damping: in momentum mode, reduce composite when market is ranging (ADX < 20).
        # Skipped in RANGING regime — mean reversion signals are EXPECTED to have low ADX.
        # Damping momentum signals in ranging markets prevents chasing false breakouts.
        adx_val = latest.get('adx', 25)
        if regime != "RANGING" and not pd.isna(adx_val) and adx_val < 20:
            if (direction == "SHORT"
                    and not pd.isna(latest.get('minus_di', float('nan')))
                    and latest.get('minus_di', 0) > latest.get('plus_di', 0)):
                composite *= 0.85
            else:
                composite *= 0.7

        # EMA200 regime gate: boost when trading with macro trend, penalise against it.
        # Only applied in TRENDING regime — RANGING uses mean-reversion logic where EMA200 is less relevant.
        ema_200 = latest.get('ema_200')
        price   = latest.get('close', 0)
        if regime != "RANGING" and ema_200 is not None and not pd.isna(ema_200) and ema_200 > 0 and price > 0:
            above_200 = price > ema_200
            if direction == "LONG":
                composite *= 1.10 if above_200 else 0.85   # bull regime: +10%; bear regime: -15%
            else:  # SHORT
                composite *= 1.10 if not above_200 else 0.85  # bear regime: +10%; bull regime: -15%

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

    async def analyze_async(self, ticker=None, catalyst="TA_BACKTEST", direction="LONG", regime="TRENDING", asset_class="crypto"):
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker, catalyst, direction, regime, asset_class)

    def analyze(self, ticker=None, catalyst="TA_BACKTEST", direction="LONG", regime="TRENDING", asset_class="crypto"):
        """Standardized interface for Project Lead. Multi-Timeframe Analysis with 7 indicators.

        regime="RANGING" activates mean-reversion mode: RSI/BB-dominant weights, no ADX damping.
        asset_class in ('crypto', 'tech_stock', 'commodity') selects indicator weight profile
        and enables EMA200 regime gating.
        """
        if ticker:
            self.symbol = ticker.replace('/USDT', '/USDC')

        mode_label = "MeanRev" if regime == "RANGING" else "Momentum"
        self.logger.info(
            f"Analyzing {self.symbol} ({mode_label}, MTF 7 indicators) "
            f"Catalyst:{catalyst} Dir:{direction} Regime:{regime}"
        )

        # Adjust timeframe weights based on catalyst and regime.
        # RANGING / mean-reversion: 1h dominant (actionable reversal signals are clearer on 1h).
        active_tf_weights = self.TF_WEIGHTS.copy()
        if regime == "RANGING":
            active_tf_weights = {'4h': 0.20, '1h': 0.55, '15m': 0.25}
        elif catalyst == "NEWS_SENTIMENT":
            self.logger.info(f"News catalyst detected for {self.symbol}. Shifting TA weights to favor short-term momentum (15m).")
            active_tf_weights = {'4h': 0.1, '1h': 0.3, '15m': 0.6}
        elif catalyst == "SWING_4H":
            self.logger.info(f"Swing catalyst detected for {self.symbol}. Weighting 4h at 0.75.")
            active_tf_weights = self.SWING_WEIGHTS.copy()

        combined_score = 0.0
        details = []
        latest_price = 0.0
        current_rsi = 0.0
        atr_pct = 0.0

        tf_data = {}
        tf_dfs  = {}  # keep raw dfs for swing-level calculation

        for tf in ['4h', '1h', '15m']:
            df = self.fetch_data(timeframe=tf)
            df = self.calculate_indicators(df)

            if df is not None and len(df) >= 50:
                score, trend_str, indicator_scores = self.analyze_signal(df, direction=direction, regime=regime, asset_class=asset_class)
                combined_score += score * active_tf_weights[tf]

                latest = df.iloc[-1]
                if tf == '1h':
                    latest_price = latest['close']
                    current_rsi = latest['rsi']
                    current_atr = latest.get('atr', 0.0)
                    atr_pct = (current_atr / latest_price * 100) if latest_price > 0 else 0.0

                tf_data[tf] = {
                    "signal": "BULLISH" if score > 0.2 else "BEARISH" if score < -0.2 else "NEUTRAL",
                    "score": round(score, 3),
                    "trend": trend_str,
                    "indicators": {k: round(v, 2) for k, v in indicator_scores.items()}
                }
                details.append(f"{tf}: {trend_str} (Score: {score:.2f})")
                tf_dfs[tf] = df
            else:
                tf_data[tf] = {"signal": "NO_DATA", "score": 0.0, "indicators": {}}
                details.append(f"{tf}: No Data")

        reason_str = " | ".join(details)

        # Structure-based levels: use 4h for swings, 1h for macro/news.
        structure_tf = '4h' if catalyst == "SWING_4H" else '1h'
        swing_levels = self._compute_swing_levels(
            tf_dfs.get(structure_tf), direction, latest_price, atr_pct
        )
        swing_levels["structure_tf"] = structure_tf

        return {
            "ticker": self.symbol,
            "signal": round(combined_score, 3),
            "reason": f"MTF Score {combined_score:.2f} [{reason_str}]",
            "timeframes": tf_data,
            "price": latest_price,
            "metrics": {
                "rsi_1h": round(current_rsi, 1) if current_rsi else 0,
                "atr_pct": round(atr_pct, 2) if atr_pct else 0,
            },
            "swing_levels": swing_levels,
            "summary": f"Tech: {combined_score:+.2f} across 3 TFs, 7 indicators"
        }

    def _compute_swing_levels(self, df, direction: str, price: float, atr_pct: float) -> dict:
        """
        Compute structure-based SL/TP levels from recent swing points + Fib extensions.

        Returns dict with:
          swing_low, swing_high       — recent 20-bar range on the chosen timeframe
          fib_1272, fib_1618          — Fibonacci extensions of the impulse leg
          sl_suggest, tp_suggest      — LONG/SHORT-appropriate structural levels
          implied_rrr                 — (tp - entry) / (entry - sl)
          valid                       — True if all inputs sane
        Fail-silent: returns {"valid": False} if data insufficient.
        """
        out = {"valid": False}
        try:
            if df is None or len(df) < 30 or price <= 0:
                return out
            lookback = 20
            recent = df.tail(lookback)
            swing_low  = float(recent['low'].min())
            swing_high = float(recent['high'].max())
            if swing_high <= swing_low or swing_low <= 0:
                return out
            impulse = swing_high - swing_low
            # Fib extensions of the impulse leg
            fib_1272_up   = swing_low  + 1.272 * impulse
            fib_1618_up   = swing_low  + 1.618 * impulse
            fib_1272_down = swing_high - 1.272 * impulse
            fib_1618_down = swing_high - 1.618 * impulse

            # Buffer to avoid stop-hunts exactly at swing (30 bps, adjusted with ATR)
            buffer_pct = max(0.003, (atr_pct / 100.0) * 0.3) if atr_pct > 0 else 0.003

            if (direction or "").upper() == "LONG":
                sl_suggest = swing_low * (1.0 - buffer_pct)
                tp_suggest = fib_1618_up   # primary target = 1.618 ext
                risk = price - sl_suggest
                reward = tp_suggest - price
            else:  # SHORT
                sl_suggest = swing_high * (1.0 + buffer_pct)
                tp_suggest = fib_1618_down
                risk = sl_suggest - price
                reward = price - tp_suggest

            if risk <= 0 or reward <= 0:
                return out
            implied_rrr = round(reward / risk, 2)

            return {
                "valid": True,
                "swing_low":   round(swing_low, 6),
                "swing_high":  round(swing_high, 6),
                "fib_1272_up": round(fib_1272_up, 6),
                "fib_1618_up": round(fib_1618_up, 6),
                "fib_1272_down": round(fib_1272_down, 6),
                "fib_1618_down": round(fib_1618_down, 6),
                "sl_suggest":  round(sl_suggest, 6),
                "tp_suggest":  round(tp_suggest, 6),
                "implied_rrr": implied_rrr,
                "buffer_pct":  round(buffer_pct * 100, 3),
                "lookback":    lookback,
            }
        except Exception as e:
            self.logger.debug(f"_compute_swing_levels failed: {e}")
            return out

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
