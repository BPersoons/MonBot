"""Equity-market regime for the tech-stock directional trader (F1).

F0-diagnose (2026-07-23) toonde: XYZ tech-equity LONGs hebben een edge, MAAR alleen
wanneer de aandelenmarkt in uptrend is — tech-stocks volgen de equity-markt, NIET
BTC. De live pipeline gebruikte overal het BTC-regime; voor stocks is dat verkeerd.

Deze module levert de equity-gate: `equity_bull = XYZ100 (tech-index) 1h close > EMA200`.
De funnel laat tech-stock LONG-entries alleen door als equity_bull True is (anders
cash). Backtest F0f/F0g: die gate zette de verliesgevende choppy-periodes om in
cash i.p.v. verlies (RECENT −44,6% → +15,8%), en maakte beide vensters positief.

Fail-closed: kan het regime niet worden bepaald, dan blokkeert de gate (geen blinde
trades). Gecachet met TTL zodat het per cyclus goedkoop is.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("EquityRegime")

_FILE = "equity_regime.json"
_TTL_S = 900  # 15 min — trend-gate hoeft niet elke cyclus te herrekenen
_EQUITY_INDEX = "XYZ-XYZ100/USDC"  # tech-index als proxy voor de equity-markt
_EMA_SPAN = 200
_cache: dict = {"ts": 0.0, "data": None}


def compute_equity_regime() -> dict | None:
    """Bereken + persisteer het equity-regime uit XYZ100 1h vs EMA200."""
    try:
        from agents.technical_analyst import get_ohlcv_df
        df = get_ohlcv_df(_EQUITY_INDEX, "1h", 250)
        if df is None or len(df) < _EMA_SPAN + 5:
            logger.warning(f"EquityRegime: onvoldoende {_EQUITY_INDEX} data "
                           f"({0 if df is None else len(df)} candles)")
            return None
        ema200 = float(df["close"].ewm(span=_EMA_SPAN, adjust=False).mean().iloc[-1])
        price = float(df["close"].iloc[-1])
        data = {
            "equity_bull": bool(price > ema200),
            "xyz100_price": round(price, 4),
            "ema200": round(ema200, 4),
            "dist_pct": round((price - ema200) / ema200 * 100, 2) if ema200 else 0.0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"EquityRegime: schrijven {_FILE} mislukt: {e}")
        return data
    except Exception as e:
        logger.error(f"EquityRegime: compute mislukt: {e}")
        return None


def refresh_equity_regime() -> dict | None:
    """Cached refresh (TTL) — veilig elke cyclus aan te roepen."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < _TTL_S:
        return _cache["data"]
    d = compute_equity_regime()
    if d:
        _cache.update(ts=now, data=d)
    return _cache["data"]


def is_equity_bull(default: bool = False) -> bool:
    """Equity-gate voor de funnel. Fail-closed: onbekend regime -> default (False =
    blokkeer). Leest cache, dan het bestand, dan default."""
    if _cache["data"] is not None:
        return bool(_cache["data"].get("equity_bull", default))
    try:
        with open(_FILE) as f:
            return bool(json.load(f).get("equity_bull", default))
    except Exception:
        return default


# ── Sector circuit-breaker voor de thematic sleeve (2026-07-24) ──────────────
# De sleeve is MEAN-REVERSION (koopt dips) — de equity-uptrend-gate (voor F1's
# momentum) is fout voor de sleeve want die blokkeert juist de normale pullbacks
# waar de edge zit (backtest bevestigd: gate schaadt de sleeve-edge). Het echte
# risico is een STRUCTURELE sector-bear (dip-buyen in een aanhoudende daling zonder
# downside-stop). Deze circuit-breaker pauzeert nieuwe dip-buys ALLEEN bij een grote
# sector-drawdown (XYZ100 >X% onder z'n trailing 60d-high) — niet bij normale dips.
# In de ~10mnd (gunstige) backtest triggerde hij 0/205 dagen → kosteloos in bull,
# beschermend in een echte bear (die niet in de data zat, dus by-design).
_CB_LOOKBACK_DAYS = 60


def sector_drawdown_pct() -> float:
    """XYZ100 huidige drawdown (%) vanaf z'n trailing 60d-high (dagelijks). 0 bij
    onvoldoende data. Positief = onder de high."""
    try:
        from agents.technical_analyst import get_ohlcv_df
        df = get_ohlcv_df(_EQUITY_INDEX, "1d", 90)
        if df is None or len(df) < 20:
            return 0.0
        window = df["close"].tail(_CB_LOOKBACK_DAYS)
        high = float(window.max())
        cur = float(df["close"].iloc[-1])
        return round((high - cur) / high * 100, 2) if high > 0 else 0.0
    except Exception as e:
        logger.debug(f"sector_drawdown_pct faalde: {e}")
        return 0.0


def sector_circuit_breaker(threshold_pct: float = 15.0) -> bool:
    """True als de sector in een structurele daling zit (drawdown >= drempel) —
    dan pauzeert de sleeve nieuwe dip-buys. Fail-open (False) bij onbekend, want
    de sleeve heeft z'n eigen positie-management; blindelings blokkeren bij een
    data-hik is erger dan doorgaan."""
    return sector_drawdown_pct() >= threshold_pct
