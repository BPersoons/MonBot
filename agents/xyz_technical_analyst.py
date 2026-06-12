"""
StockTechnicalAnalyst — market-hours-aware TA for XYZ stock CFDs on Hyperliquid.

XYZ assets (e.g. XYZ-INTC, XYZ-NVDA, XYZ-GOOGL) trade 24/7 on Hyperliquid but the
underlying only moves during US market hours (14:30-21:00 UTC, Mon-Fri). Standard
24/7 OHLCV is ~70% noise (flat/micro-drift candles outside the session), which
distorts RSI, ADX, and volume signals.

Key differences vs TechnicalAnalyst:
  - 1h data filtered to US market hours before indicator calculation
  - Primary timeframes: 1d (60 candles) + market-hours 1h (no 15m)
  - Adjusted RSI thresholds (stocks rarely hit 80/20 extremes)
  - Signal dampened when entry is near session close (20:30+ UTC)
"""

import logging
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from agents.technical_analyst import TechnicalAnalyst


def _market_is_open(asset_class: str, now_utc: datetime) -> bool:
    """Is the underlying market currently open (for entry decisions)?

    Equities: Mon-Fri 14:30-21:00 UTC.
    Commodities: Sun 23:00 → Fri 22:00 UTC, with a daily 22:00-23:00 maintenance break.
    """
    wd = now_utc.weekday()  # Mon=0 .. Sun=6
    if asset_class == "commodity":
        if wd == 5:                              # Saturday — closed
            return False
        if wd == 6:                              # Sunday — opens 23:00 UTC
            return now_utc.hour >= 23
        if wd == 4 and now_utc.hour >= 22:       # Friday — closes 22:00 UTC
            return False
        return now_utc.hour != 22                # Mon-Fri daily 22:00-23:00 break
    # Equities
    if wd >= 5:
        return False
    minutes = now_utc.hour * 60 + now_utc.minute
    return 14 * 60 + 30 <= minutes < 21 * 60


class StockTechnicalAnalyst(TechnicalAnalyst):
    """Market-hours-aware TA for XYZ stock CFDs on Hyperliquid."""

    # US market hours in UTC (14:30 open → 21:00 close; 1h candle at 14:xx covers open)
    MARKET_OPEN_HOUR  = 14
    MARKET_CLOSE_HOUR = 20  # last full 1h candle before 21:00 close

    # Timeframe weights: daily dominates (one candle = one full session), no 15m
    TF_WEIGHTS    = {'1d': 0.55, '1h': 0.45}
    SWING_WEIGHTS = {'1d': 0.70, '1h': 0.30}

    # Indicator weights: MACD + EMA more reliable on daily; drop Stochastic (noisy on stocks)
    INDICATOR_WEIGHTS = {
        'macd':       0.28,
        'ema':        0.24,
        'rsi':        0.18,
        'bb':         0.14,
        'adx':        0.12,
        'volume':     0.04,
        'stochastic': 0.00,
    }

    def __init__(self, exchange_id='hyperliquid', symbol='BTC/USDC'):
        super().__init__(exchange_id, symbol)
        self.logger = logging.getLogger("StockTechnicalAnalyst")

    @staticmethod
    def is_xyz_ticker(ticker: str) -> bool:
        return str(ticker).startswith('XYZ-')

    # ── Data fetching ──────────────────────────────────────────────────────────

    def fetch_data(self, timeframe='1h', limit=100):
        """Fetch OHLCV; filter 1h candles to the asset's market hours."""
        df = super().fetch_data(timeframe=timeframe, limit=limit)
        if df is None or df.empty:
            return df
        if timeframe == '1h':
            df = self._filter_market_hours(df, getattr(self, '_asset_class', 'tech_stock'))
        return df

    def _filter_market_hours(self, df: pd.DataFrame, asset_class: str = "tech_stock") -> pd.DataFrame:
        """Keep only candles during the asset's market hours.

        Equities: Mon-Fri 14:00-20:00 UTC. Commodities trade ~23h/day (Sun 23:00 →
        Fri 22:00 UTC, daily 22:00-23:00 break); applying equity hours to them threw
        away ~17h/day of valid candles and starved the TA of data.
        """
        if df is None or df.empty:
            return df
        ts = pd.to_datetime(df['timestamp'])
        wd = ts.dt.dayofweek
        hr = ts.dt.hour
        if asset_class == "commodity":
            weekday_open = (wd < 5) & (hr != 22) & ~((wd == 4) & (hr >= 22))
            sunday_open = (wd == 6) & (hr >= 23)
            mask = weekday_open | sunday_open
        else:
            mask = (wd < 5) & (hr >= self.MARKET_OPEN_HOUR) & (hr <= self.MARKET_CLOSE_HOUR)
        filtered = df[mask].reset_index(drop=True)
        # Fall back to unfiltered if we don't have enough rows for indicators
        return filtered if len(filtered) >= 20 else df

    # ── Adjusted indicator scoring ─────────────────────────────────────────────

    def _score_rsi(self, rsi_value, direction="LONG"):
        """
        Stock-adjusted RSI thresholds.
        Stocks rarely hit crypto extremes (80/20); use 70/30 as overbought/oversold.
        """
        if pd.isna(rsi_value):
            return 0.0
        if direction == "SHORT":
            if rsi_value > 70:    return  1.0   # Overbought — confirms SHORT
            elif rsi_value > 60:  return  0.4
            elif rsi_value < 30:  return -1.0   # Oversold — bad for SHORT
            elif rsi_value < 40:  return -0.4
            else:                 return (rsi_value - 50) / 50.0 * 0.2
        # LONG:
        if rsi_value > 70:        return -1.0   # Overbought
        elif rsi_value > 60:      return -0.4
        elif rsi_value < 30:      return  1.0   # Oversold — bounce likely
        elif rsi_value < 40:      return  0.5
        else:                     return (50 - rsi_value) / 50.0 * 0.2

    def _score_volume(self, latest, direction="LONG"):
        """
        Volume on XYZ stocks is near-zero outside market hours.
        Only meaningful on market-hours-filtered data; use a gentler scale.
        """
        vol_ratio = latest.get('vol_ratio', 1.0)
        if pd.isna(vol_ratio):
            return 0.0
        # High volume confirms breakout; low volume = no conviction
        if vol_ratio >= 2.0:   raw =  0.8
        elif vol_ratio >= 1.3: raw =  0.4
        elif vol_ratio >= 0.7: raw =  0.1
        else:                  raw = -0.3   # Volume drying up
        return raw if direction == "LONG" else -raw * 0.5  # volume less directional for shorts

    # ── Main analysis ──────────────────────────────────────────────────────────

    def analyze(self, ticker=None, catalyst="TA_BACKTEST", direction="LONG", regime="TRENDING", asset_class="tech_stock"):
        """
        Stock-specific MTF analysis: 1d (primary) + market-hours 1h.
        Returns same schema as TechnicalAnalyst.analyze() for seamless pipeline integration.
        regime is accepted for API compatibility but ignored — XYZ assets don't correlate
        with BTC-derived market regimes and are always analyzed in momentum mode.
        asset_class in ('tech_stock', 'commodity') selects indicator weights and EMA200 gate.
        """
        if ticker:
            self.symbol = ticker.replace('/USDT', '/USDC')

        self.logger.info(
            f"[Stock TA] {self.symbol} — 1d+1h(market-hours) | Direction: {direction}"
        )
        # Make asset_class available to fetch_data → _filter_market_hours.
        self._asset_class = asset_class

        active_tf_weights = (
            self.SWING_WEIGHTS if catalyst == "SWING_4H" else self.TF_WEIGHTS
        )

        combined_score = 0.0
        details        = []
        latest_price   = 0.0
        current_rsi    = 0.0
        atr_pct        = 0.0
        tf_data        = {}
        tf_dfs         = {}

        # calculate_indicators() returns None below 50 candles. The 1h market-hours
        # filter keeps only ~21% of candles, so 200 raw → ~35 usable → ALWAYS None
        # (the structural reason XYZ scored 0.00). 500 raw → ~105 usable; 365 daily
        # covers EMA200 for established tokens (young tokens get whatever exists).
        fetch_limits = {'1d': 365, '1h': 500}

        for tf in ('1d', '1h'):
            df = self.fetch_data(timeframe=tf, limit=fetch_limits[tf])
            df = self.calculate_indicators(df)

            if df is not None and len(df) >= 20:
                score, trend_str, indicator_scores = self.analyze_signal(
                    df, direction=direction, asset_class=asset_class
                )
                combined_score += score * active_tf_weights[tf]

                latest = df.iloc[-1]
                if tf == '1h':
                    latest_price = latest['close']
                    current_rsi  = latest.get('rsi', 0.0)
                    current_atr  = latest.get('atr', 0.0)
                    atr_pct = (
                        (current_atr / latest_price * 100) if latest_price > 0 else 0.0
                    )
                elif tf == '1d' and latest_price == 0.0:
                    latest_price = latest['close']

                tf_data[tf] = {
                    "signal": (
                        "BULLISH" if score > 0.2
                        else "BEARISH" if score < -0.2
                        else "NEUTRAL"
                    ),
                    "score": round(score, 3),
                    "trend": trend_str,
                    "indicators": {k: round(v, 2) for k, v in indicator_scores.items()},
                }
                details.append(f"{tf}: {trend_str} ({score:.2f})")
                tf_dfs[tf] = df
            else:
                n = len(df) if df is not None else 0
                self.logger.warning(
                    f"[Stock TA] {self.symbol} {tf}: only {n} rows after filter"
                )
                tf_data[tf] = {"signal": "NO_DATA", "score": 0.0, "indicators": {}}
                details.append(f"{tf}: insufficient data ({n} rows)")

        # Market-hours gate: outside the asset's session the score is based on stale
        # candles and any entry can't be acted on until the next open → neutral.
        now_utc = datetime.now(timezone.utc)
        if not _market_is_open(asset_class, now_utc):
            combined_score = 0.0
            details.append("market closed — no entry")
            self.logger.info(f"[Stock TA] {self.symbol}: market closed ({asset_class}) — neutral signal")
        elif asset_class != "commodity" and now_utc.hour == 20 and now_utc.minute >= 30:
            # Equity near-close damping (last 30 min of the 14:30-21:00 session)
            combined_score *= 0.4
            details.append("⚠️ near session close — signal dampened")
            self.logger.info(f"[Stock TA] {self.symbol}: near session close, dampening signal")

        combined_score = float(np.clip(combined_score, -1.0, 1.0))

        _swing_df = tf_dfs.get('1d') if tf_dfs.get('1d') is not None else tf_dfs.get('1h')
        swing_levels = self._compute_swing_levels(
            _swing_df,
            direction,
            latest_price,
            atr_pct,
        )
        swing_levels["structure_tf"] = "1d"

        return {
            "ticker":     self.symbol,
            "signal":     round(combined_score, 3),
            "reason":     f"Stock TA {combined_score:.2f} [{' | '.join(details)}]",
            "timeframes": tf_data,
            "price":      latest_price,
            "metrics": {
                "rsi_1h":  round(current_rsi, 1) if current_rsi else 0,
                "atr_pct": round(atr_pct, 2)    if atr_pct    else 0,
            },
            "swing_levels": swing_levels,
            "summary": f"Stock TA: {combined_score:+.2f} (1d+1h mkt-hours)",
        }

    async def analyze_async(self, ticker=None, catalyst="TA_BACKTEST", direction="LONG", regime="TRENDING", asset_class="tech_stock"):
        import asyncio
        return await asyncio.to_thread(self.analyze, ticker, catalyst, direction, regime, asset_class)
