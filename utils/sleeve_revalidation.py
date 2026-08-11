"""Re-validatie-lus voor de Thematic Exposure Sleeve (dip-buy, EXP-008).

Waarom
------
De sleeve-validatie (2026-07-24, zie feedback_sleeve_validation) toonde: de dip-buy-
edge is echt (+5,3%/positie) MAAR 100% favorable-regime — de hele ~10mnd backtest was
bull, dus het bear-gedrag is ONTESTBAAR. De gedeployde guards (sector-circuit-breaker
+ downside-stop) beschermen by-design, maar de énige manier om een echte regime-shift
te vangen is LIVE decay-detectie. Deze lus geeft de sleeve dezelfde vangnet-symmetrie
als F1's directional-re-validatie.

Methode: draai (dagelijks, self-throttled) de sleeve-strategie MÉT de guards over een
trailing venster; meet avg per-positie-return, WR en falling-knife-risico. De-riskt
autonoom (pauzeert nieuwe entries via `sleeve_entries_enabled=False`) ALLEEN als
`sleeve_revalidation_autopause_enabled=True` (default False = observeren+alarmeren) —
zelfde veiligheids-fasering als F1.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger("SleeveRevalidation")

_STATE_FILE = "sleeve_revalidation.json"
_THEMES_FILE = "config/thematic_exposure_themes.json"
_INTERVAL_S = 24 * 3600
_TRAILING_DAYS = 180


def _cfg(key, default):
    try:
        with open("config/auto_params.json") as f:
            v = json.load(f).get(key)
            return v if v is not None else default
    except Exception:
        return default


def _fetch_daily(ex, sym, since_ms):
    import pandas as pd
    hl = sym + "/USDC:USDC"
    out = []
    cur = since_ms
    for _ in range(10):
        try:
            b = ex.fetch_ohlcv(hl, "1d", since=cur, limit=5000)
        except Exception:
            return None
        if not b:
            break
        out += b
        if len(b) < 2:
            break
        cur = b[-1][0] + 1
        time.sleep(0.1)
    if not out:
        return None
    df = pd.DataFrame(out, columns=["ts", "o", "h", "l", "close", "v"]).drop_duplicates("ts")
    return {int(r.ts // 86400000): float(r.close) for r in df.itertuples()}


def run_sleeve_revalidation(force: bool = False) -> dict | None:
    """Draai de sleeve-re-validatie als het interval verstreken is (of force)."""
    try:
        prev = {}
        try:
            with open(_STATE_FILE) as f:
                prev = json.load(f)
        except Exception:
            pass
        if not force and prev.get("ran_at_epoch") and (time.time() - prev["ran_at_epoch"]) < _INTERVAL_S:
            return None

        import pandas as pd
        from utils.thematic_exposure_lab import (
            ThematicExposureLab, PULLBACK_VOL_THRESHOLD, BREADTH_THRESHOLD,
            SLEEVE_CIRCUIT_BREAKER_DD_PCT, SLEEVE_MAX_DRAWDOWN_STOP_PCT)
        from agents.technical_analyst import _get_shared_exchange

        lab = ThematicExposureLab()
        ex = _get_shared_exchange()
        with open(_THEMES_FILE) as f:
            cfg = json.load(f)
        conf = {t: c for t, c in cfg.get("tickers", {}).items()
                if c.get("status") == "CONFIRMED" and c.get("real_symbol")}
        themes = cfg.get("themes", {})
        since = int(time.time() * 1000) - _TRAILING_DAYS * 24 * 3600 * 1000

        DATA = {}
        for t in conf:
            d = _fetch_daily(ex, t, since)
            if d and len(d) >= 25:
                DATA[t] = d
        if len(DATA) < 3:
            logger.warning("SleeveRevalidation: te weinig data")
            return None

        eq = _fetch_daily(ex, "XYZ-XYZ100", since)
        eqs = pd.Series(dict(sorted(eq.items()))) if eq else None
        roll_high = eqs.rolling(60, min_periods=20).max() if eqs is not None else None

        all_days = sorted(set().union(*[set(v.keys()) for v in DATA.values()]))
        theme_members = {th: [t for t in DATA if th in (conf[t].get("themes") or {})] for th in themes}
        hist = {t: sorted(v.items()) for t, v in DATA.items()}

        positions = {}; closed = []; knife = []
        for day in all_days:
            cb_on = False
            if roll_high is not None and day in roll_high.index and roll_high[day] > 0:
                cb_on = ((roll_high[day] - eqs[day]) / roll_high[day] * 100) >= SLEEVE_CIRCUIT_BREAKER_DD_PCT
            sc = {}
            for t in DATA:
                cl = [c for d, c in hist[t] if d <= day]
                if len(cl) < 20 or day not in DATA[t]:
                    continue
                sc[t] = lab._pullback_score(cl[:-1], cl[-1])
            breadth = {}
            for th, mem in theme_members.items():
                scr = [t for t in mem if t in sc]
                breadth[th] = (sum(1 for t in scr if sc[t]["pullback_z"] >= PULLBACK_VOL_THRESHOLD) / len(scr)) if scr else 0.0
            for t in list(positions):
                if day not in DATA[t]:
                    continue
                pos = positions[t]; mark = DATA[t][day]; entry = pos["entry"]
                gain = (mark - entry) / entry * 100
                pos["peak"] = max(pos["peak"], mark); pos["min_gain"] = min(pos["min_gain"], gain)
                ef = 0.0; full = False
                if gain <= -SLEEVE_MAX_DRAWDOWN_STOP_PCT: full = True
                elif gain >= 100 and not pos["t3"]: ef = 0.25; pos["t3"] = True
                elif gain >= 60 and not pos["t2"]: ef = 0.25; pos["t2"] = True
                elif gain >= 30 and not pos["t1"]: ef = 0.25; pos["t1"] = True
                elif gain > 0 and mark < pos["peak"] * 0.80: full = True
                if ef > 0:
                    pos["realized"] += pos["rem"] * ef * ((mark - entry) / entry); pos["rem"] *= (1 - ef)
                if full:
                    pos["realized"] += pos["rem"] * ((mark - entry) / entry)
                    closed.append(pos["realized"]); knife.append(pos["min_gain"]); del positions[t]
            if not cb_on:
                for t in sc:
                    if t in positions:
                        continue
                    s = sc[t]; tb = max((breadth.get(th, 0.0) for th in (conf[t].get("themes") or {})), default=0.0)
                    if s["pullback_z"] >= PULLBACK_VOL_THRESHOLD and tb >= BREADTH_THRESHOLD and s["stabilized"]:
                        positions[t] = {"entry": DATA[t][day], "peak": DATA[t][day], "rem": 1.0,
                                        "realized": 0.0, "t1": False, "t2": False, "t3": False, "min_gain": 0.0}
        ld = all_days[-1]
        for t, pos in positions.items():
            m = DATA[t].get(ld) or sorted(DATA[t].items())[-1][1]
            pos["realized"] += pos["rem"] * ((m - pos["entry"]) / pos["entry"])
            closed.append(pos["realized"]); knife.append(pos["min_gain"])

        n = len(closed)
        wr = round(sum(1 for x in closed if x > 0) / n * 100, 1) if n else 0.0
        avg = round(sum(closed) / n * 100, 2) if n else 0.0
        deep = sum(1 for k in knife if k < -20)
        result = {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "ran_at_epoch": time.time(),
            "trailing_days": _TRAILING_DAYS, "config": "thematic dip-buy (met guards)",
            "n_entries": n, "win_rate": wr, "avg_return_pct": avg,
            "deep_underwater_frac": round(deep / n, 2) if n else 0.0,
            "worst_pct": round(min(knife), 1) if knife else 0.0,
        }

        min_edge = float(_cfg("sleeve_revalidation_min_edge_pct", 0.0))
        autopause = bool(_cfg("sleeve_revalidation_autopause_enabled", False))
        decayed = avg < min_edge
        result["edge_ok"] = not decayed
        result["autopause_enabled"] = autopause

        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(result, f, indent=2)
        except Exception as e:
            logger.error(f"SleeveRevalidation: schrijven state mislukt: {e}")

        _notify(result, decayed, autopause)
        if decayed and autopause:
            _set_flag("sleeve_entries_enabled", False)
            result["action"] = "AUTO_PAUSED"
        logger.info(f"[SleeveRevalidation] avg {avg:+.2f}%/positie (n={n}, WR={wr}%, "
                    f"deep-underwater {result['deep_underwater_frac']:.0%}) edge_ok={not decayed}")
        return result
    except Exception as e:
        logger.error(f"SleeveRevalidation run mislukt: {e}")
        return None


def _set_flag(key, value):
    try:
        p = "config/auto_params.json"
        with open(p) as f:
            d = json.load(f)
        d[key] = value
        with open(p, "w") as f:
            json.dump(d, f, indent=2)
        logger.warning(f"[SleeveRevalidation] {key} -> {value} (de-risk)")
    except Exception as e:
        logger.error(f"SleeveRevalidation _set_flag mislukt: {e}")


def _notify(result, decayed, autopause):
    try:
        import os
        import urllib.parse, urllib.request
        token = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return
        status = "🔴 EDGE WEGGEZAKT" if decayed else "🟢 edge intact"
        action = ""
        if decayed:
            action = ("\n→ AUTO-GEPAUZEERD (de-risk)" if autopause
                      else "\n→ ⚠️ auto-pauze UIT — overweeg review/pauze")
        msg = (f"📊 *Sleeve re-validatie* ({result['trailing_days']}d dip-buy)\n"
               f"{status}: avg {result['avg_return_pct']:+.2f}%/positie "
               f"(n={result['n_entries']}, WR={result['win_rate']}%, "
               f"diep-onder {result['deep_underwater_frac']:.0%}){action}")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat, "text": msg, "parse_mode": "Markdown"}).encode()
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass
