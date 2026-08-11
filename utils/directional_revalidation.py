"""Re-validatie-lus voor de directional tech-LONG trader (F1 G2c).

Waarom
------
F0-diagnose (2026-07-23) toonde: de tech-stock LONG-edge is ECHT maar BESCHEIDEN,
LUMPY en CONDITIONEEL (werkt in tech-uptrends, niet daarbuiten). "Long-only tech is
best" geldt vóór de huidige condities — verandert de markt, dan verandert wat werkt.

Deze lus meet daarom periodiek (dagelijks) of de gedeployde config nog een edge heeft
op RECENTE data, en beschermt autonoom door te DE-RISKEN (pauzeren) als de edge
wegzakt. Belangrijk (les uit het oude systeem dat faalde op reactief auto-switchen):
de lus mag alleen DE-RISKEN autonoom; risico TOEVOEGEN (shorts/crypto aanzetten,
loslaten) vereist menselijke review via een Telegram-alert.

Veiligheids-gefaseerd
---------------------
- Draait + meet + schrijft `directional_revalidation.json` + Telegram-samenvatting.
- De auto-pauze-ACTIE zit achter `revalidation_autopause_enabled` (default False):
  je promoveert 'm van observeren naar handelen zodra je 'm vertrouwt.

Methode: herbruikt de F0-harness (equity-gated tech-LONG, echte StrategyManager,
portfolio-sim met concurrency+sizing) over een rollend trailing venster.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("DirectionalRevalidation")

_STATE_FILE = "directional_revalidation.json"
_TICKERS = ["XYZ-MU", "XYZ-AMD", "XYZ-NVDA", "XYZ-SNDK", "XYZ-INTC", "XYZ-META",
            "XYZ-AAPL", "XYZ-MSFT", "XYZ-ORCL", "XYZ-SP500", "XYZ-XYZ100", "XYZ-CRCL", "XYZ-SMSN"]
_TRAILING_DAYS = 90
_MAX_CONCURRENT = 5
_COST = 0.0012
_INTERVAL_S = 24 * 3600  # dagelijks


def _cfg(key: str, default):
    try:
        with open("config/auto_params.json") as f:
            v = json.load(f).get(key)
            return v if v is not None else default
    except Exception:
        return default


def _equity_bull_series(ex, since, until):
    import numpy as np, pandas as pd
    from utils.exchange_client import HyperliquidExchange  # noqa: F401
    df = _fetch(ex, "XYZ-XYZ100/USDC", since, until)
    if df is None:
        return None, None
    ema = df["close"].ewm(span=200, adjust=False).mean()
    return df["ts"].values.astype("int64"), (df["close"] > ema).values


def _fetch(ex, sym, since, until):
    import pandas as pd
    hl = sym if ":" in sym else f"{sym}:USDC"
    out = []
    cur = since
    for _ in range(30):
        try:
            b = ex.fetch_ohlcv(hl, "1h", since=cur, limit=5000)
        except Exception:
            break
        if not b:
            break
        out += b
        last = b[-1][0]
        if last >= until or len(b) < 2:
            break
        cur = last + 1
        time.sleep(0.1)
    if not out:
        return None
    return pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts").reset_index(drop=True)


def _portfolio_return(trades, maxc=_MAX_CONCURRENT):
    """Event-driven portfolio-sim: max concurrency, sizing = kapitaal/maxc, compounding."""
    ev = []
    for idx, (ets, xts, ret) in enumerate(trades):
        ev.append((ets, 1, idx, ret)); ev.append((xts, 0, idx, ret))
    ev.sort(key=lambda x: (x[0], x[1]))
    cap = 1.0; openc = 0; taken = {}
    for ts, typ, idx, ret in ev:
        if typ == 0:
            if idx in taken:
                cap += taken[idx] * ret; openc -= 1; del taken[idx]
        elif openc < maxc:
            taken[idx] = cap / maxc; openc += 1
    return cap - 1.0


def run_revalidation(force: bool = False) -> dict | None:
    """Draai de re-validatie als het interval verstreken is (of force). Returns het
    resultaat-dict of None (geen run / fout)."""
    try:
        prev = {}
        try:
            with open(_STATE_FILE) as f:
                prev = json.load(f)
        except Exception:
            pass
        if not force and prev.get("ran_at_epoch") and (time.time() - prev["ran_at_epoch"]) < _INTERVAL_S:
            return None  # nog geen 24u

        import numpy as np, pandas as pd
        import agents.strategy_manager as sm
        from agents.strategy_manager import StrategyManager
        from agents.technical_analyst import _get_shared_exchange, get_ohlcv_df  # noqa: F401
        from core.directional_signals import add_directional_indicators, signal_for_ticker

        class _Clock:
            t = 0.0
            def time(self): return self.t
        clock = _Clock(); sm.time = clock; sm._us_market_is_open = lambda: True
        mgr = StrategyManager()
        ex = _get_shared_exchange()
        now_ms = int(time.time() * 1000)
        since = now_ms - _TRAILING_DAYS * 24 * 3600 * 1000

        eq_ts, eq_bull = _equity_bull_series(ex, since - 300 * 3600 * 1000, now_ms)
        if eq_ts is None:
            logger.warning("Revalidation: geen equity-index data")
            return None

        def ebull(ts):
            i = np.searchsorted(eq_ts, ts, side="right") - 1
            return bool(eq_bull[i]) if i >= 0 else False

        trades = []
        for t in _TICKERS:
            df = _fetch(ex, t + "/USDC", since - 300 * 3600 * 1000, now_ms)
            if df is None or len(df) < 260:
                continue
            df2 = add_directional_indicators(df).reset_index(drop=True)
            ta = df["ts"].values.astype("int64")
            pos = None
            for i in range(210, len(df2)):
                r = df2.iloc[i]; cl = float(r["close"]); hi = float(r["high"]); lo = float(r["low"])
                clock.t = ta[i] / 1000.0
                if pos:
                    tr = pos["trade"]; tr["peak_price"] = max(tr["peak_price"], hi)
                    sl = tr["stop_loss"]; tp = tr["take_profit"]; e = None
                    if lo <= sl: e = sl
                    elif hi >= tp: e = tp
                    if e is None:
                        rr = mgr.evaluate_position(tr, cl)
                        if "peak_price" in rr: tr["peak_price"] = rr["peak_price"]
                        a = rr.get("action")
                        if a == "CLOSE_FULL": e = cl
                        elif a == "CLOSE_PARTIAL":
                            f = rr.get("close_fraction", 0.40)
                            pos["r"] += pos["rem"] * f * ((cl - pos["entry"]) / pos["entry"])
                            pos["rem"] *= (1 - f); tr["partial_tp1_taken"] = True
                        elif a == "UPDATE_SL":
                            tr["stop_loss"] = rr["new_sl"]; tr["sl_stage"] = rr["sl_stage"]
                    if e is not None:
                        pos["r"] += pos["rem"] * ((e - pos["entry"]) / pos["entry"])
                        trades.append((pos["ets"], ta[i], pos["r"] - _COST))  # entry al ≥ since
                        pos = None
                if not pos:
                    s = signal_for_ticker(t + "/USDC", df2, i)
                    if s == 1 and ebull(ta[i]) and ta[i] >= since:
                        lv = mgr.calculate_levels(cl, "BUY", 1.5, 5.0, timeframe="1h Macro")
                        tr = {"entry_price": cl, "action": "BUY", "take_profit": lv["take_profit"],
                              "stop_loss": lv["stop_loss"], "sl_pct": lv["sl_pct"], "sl_stage": 0,
                              "partial_tp1_taken": False, "entry_time": ta[i] / 1000.0,
                              "timeframe": "1h Macro", "ticker": t + "/USDC", "peak_price": cl, "funding_rate": 0.0}
                        pos = {"trade": tr, "entry": cl, "r": 0.0, "rem": 1.0, "ets": ta[i]}

        n = len(trades)
        wr = round(sum(1 for x in trades if x[2] > 0) / n * 100, 1) if n else 0.0
        sum_ret = round(sum(x[2] for x in trades) * 100, 1)
        port_ret = round(_portfolio_return(trades) * 100, 1)

        result = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "ran_at_epoch": time.time(),
            "trailing_days": _TRAILING_DAYS,
            "config": "equity-gated tech-LONG",
            "n_trades": n, "win_rate": wr,
            "sum_returns_pct": sum_ret,
            "portfolio_return_pct": port_ret,
        }

        min_edge = float(_cfg("revalidation_min_edge_pct", 0.0))
        autopause = bool(_cfg("revalidation_autopause_enabled", False))
        decayed = port_ret < min_edge
        result["edge_ok"] = not decayed
        result["autopause_enabled"] = autopause

        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(result, f, indent=2)
        except Exception as e:
            logger.error(f"Revalidation: schrijven state mislukt: {e}")

        _notify(result, decayed, autopause)
        if decayed and autopause:
            _autopause()
            result["action"] = "AUTO_PAUSED"
        logger.info(f"[Revalidation] {result['config']}: portfolio {port_ret:+.1f}% "
                    f"(n={n}, WR={wr}%) edge_ok={not decayed} autopause={autopause}")
        return result
    except Exception as e:
        logger.error(f"Revalidation run mislukt: {e}")
        return None


def _autopause():
    """De-risk: pauzeer de directional trader (armed_mode uit + hoge drempel)."""
    try:
        p = "config/auto_params.json"
        with open(p) as f:
            d = json.load(f)
        d["armed_mode_enabled"] = False
        d["score_threshold"] = max(float(d.get("score_threshold", 0.20)), 0.40)
        d["_meta"] = {"last_changed_by": "directional_revalidation_autopause",
                      "change_reason": "Edge weggezakt op trailing data — directional trader autonoom gepauzeerd (de-risk)."}
        with open(p, "w") as f:
            json.dump(d, f, indent=2)
        logger.warning("[Revalidation] AUTO-PAUSED directional trader (edge decayed)")
    except Exception as e:
        logger.error(f"Revalidation autopause mislukt: {e}")


def _notify(result, decayed, autopause):
    try:
        import os
        import urllib.parse, urllib.request
        token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        status = ("🔴 EDGE WEGGEZAKT" if decayed else "🟢 edge intact")
        action = ""
        if decayed:
            action = ("\n→ AUTO-GEPAUZEERD (de-risk)" if autopause
                      else "\n→ ⚠️ auto-pauze staat UIT — overweeg handmatig pauzeren of review")
        msg = (f"📊 *Directional re-validatie* ({result['trailing_days']}d)\n"
               f"{status}: portfolio {result['portfolio_return_pct']:+.1f}% "
               f"(n={result['n_trades']}, WR={result['win_rate']}%){action}")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "Markdown"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass
