"""
ShadowBook — virtual-outcome engine for short feedback loops.

Records every scored decision (|score| >= _MIN_SCORE with a real price) as a
VIRTUAL trade — including the NO_GO and MONITOR rejects that never reach the
exchange — and resolves them against real OHLCV candles. Outcomes are
aggregated per score band / direction / asset class / decision so signal
quality is measurable at 10-40x the real trade volume, within hours instead
of weeks, without risking capital and without extra LLM calls (the signals
were already computed by the pipeline).

Design choice: the bracket is deliberately UNIFORM (SL 3%, TP 4.5% = 1:1.5,
24h time exit) so bands are comparable. It does NOT simulate the live
trailing/partial-exit engine — real trades carry management alpha on top
(the sl_stage-2 effect), so shadow numbers measure ENTRY quality only.
Candle walk is pessimistic: when SL and TP fall inside the same candle the
SL wins.

Files:
  shadow_book.json   — open + resolved virtual trades (bounded)
  shadow_report.json — aggregated band report, rewritten after each resolve
"""

import json
import logging
import math
import os
import time
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("ShadowBook")

_BOOK_FILE   = "shadow_book.json"
_REPORT_FILE = "shadow_report.json"

_MIN_SCORE    = 0.10   # record decisions from just below the gate-1 SHORT floor
_SL_PCT       = 3.0    # uniform bracket: stop loss %
_TP_PCT       = 4.5    # uniform bracket: take profit % (1:1.5)
_TIME_EXIT_H  = 24     # uniform time exit
_COOLDOWN_H   = 6      # max one virtual trade per setup+direction per window
_MAX_OPEN     = 80
_MAX_RESOLVED = 1500
_REPORT_DAYS  = 14     # aggregation window
_BANDS = [(0.10, 0.15), (0.15, 0.20), (0.20, 0.25), (0.25, 1.01)]


def _sanitize(obj):
    if isinstance(obj, float):
        return 0.0 if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


class ShadowBook:
    def __init__(self, exchange_client=None):
        # HyperliquidExchange instance — used for symbol normalization and
        # OHLCV fetches via its rate-limited public ccxt client.
        self.exchange_client = exchange_client
        self._regime_cache = (0.0, "UNKNOWN")

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> list:
        try:
            if os.path.exists(_BOOK_FILE):
                with open(_BOOK_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"ShadowBook: could not read {_BOOK_FILE}: {e}")
        return []

    def _save(self, book: list):
        try:
            with open(_BOOK_FILE, "w", encoding="utf-8") as f:
                json.dump(_sanitize(book), f, indent=1)
        except Exception as e:
            logger.warning(f"ShadowBook: could not write {_BOOK_FILE}: {e}")

    def _regime(self) -> str:
        ts, cached = self._regime_cache
        if time.time() - ts < 300:
            return cached
        regime = "UNKNOWN"
        try:
            with open("market_regime.json", "r", encoding="utf-8") as f:
                regime = json.load(f).get("regime", "UNKNOWN")
        except Exception:
            pass
        self._regime_cache = (time.time(), regime)
        return regime

    # ── recording ─────────────────────────────────────────────────────────────

    def record(self, setup_id, ticker, direction, score, price, decision,
               analyst_signals=None):
        """Register one scored decision as a virtual trade. Fail-open."""
        try:
            score = float(score or 0)
            price = float(price or 0)
            if abs(score) < _MIN_SCORE or price <= 0:
                return
            # XYZ price placeholder: details['technical']['price'] defaults to
            # 100.0 when the TA had no data (closed market). A virtual entry at
            # a fake price poisons every aggregate (audit B7).
            if price == 100.0 and str(ticker).upper().startswith("XYZ-"):
                return

            book = self._load()
            now = time.time()
            key = f"{setup_id}|{direction}"
            for t in book:
                if t.get("key") == key and (
                    t.get("status") == "OPEN"
                    or now - float(t.get("opened_at", 0)) < _COOLDOWN_H * 3600
                ):
                    return  # cooldown — same setup already booked recently
            if sum(1 for t in book if t.get("status") == "OPEN") >= _MAX_OPEN:
                return

            try:
                from core.strategy_logic import detect_asset_class
                asset_class = detect_asset_class(ticker)
            except Exception:
                asset_class = "crypto"

            is_long = str(direction).upper() != "SHORT"
            sl = price * (1 - _SL_PCT / 100) if is_long else price * (1 + _SL_PCT / 100)
            tp = price * (1 + _TP_PCT / 100) if is_long else price * (1 - _TP_PCT / 100)
            book.append({
                "key": key,
                "setup_id": setup_id,
                "ticker": ticker,
                "direction": "LONG" if is_long else "SHORT",
                "score": round(score, 3),
                "decision": decision,
                "entry_price": price,
                "sl_price": sl,
                "tp_price": tp,
                "asset_class": asset_class,
                "regime": self._regime(),
                "analyst_signals": _sanitize(analyst_signals or {}),
                "opened_at": now,
                "opened_iso": datetime.utcnow().isoformat(),
                "status": "OPEN",
            })
            self._save(book)
        except Exception as e:
            logger.warning(f"ShadowBook.record failed for {ticker}: {e}")

    # ── resolution ────────────────────────────────────────────────────────────

    def _fetch_candles(self, ticker, since_ms):
        ex = self.exchange_client
        if not ex or not getattr(ex, "public_client", None):
            return None
        try:
            symbol = ex._normalize_symbol(ticker)
            if symbol is None:
                return None
            return ex.public_client.fetch_ohlcv(symbol, "15m", since=int(since_ms), limit=200)
        except Exception as e:
            logger.debug(f"ShadowBook: candle fetch failed for {ticker}: {e}")
            return None

    def resolve_open(self):
        """Walk OHLCV since entry for every OPEN virtual trade; mark outcomes.
        One candle fetch per ticker per pass. Fail-open."""
        try:
            book = self._load()
            open_trades = [t for t in book if t.get("status") == "OPEN"]
            if not open_trades:
                return

            by_ticker = defaultdict(list)
            for t in open_trades:
                by_ticker[t["ticker"]].append(t)

            resolved_n = 0
            for ticker, trades in by_ticker.items():
                oldest = min(float(t["opened_at"]) for t in trades)
                candles = self._fetch_candles(ticker, oldest * 1000)
                if not candles:
                    continue
                for t in trades:
                    outcome = self._walk(t, candles)
                    if outcome:
                        t.update(outcome)
                        t["status"] = "RESOLVED"
                        resolved_n += 1

            if resolved_n:
                logger.info(f"ShadowBook: resolved {resolved_n} virtual trade(s)")
            # prune resolved history
            resolved = [t for t in book if t.get("status") == "RESOLVED"]
            if len(resolved) > _MAX_RESOLVED:
                drop = len(resolved) - _MAX_RESOLVED
                kept, dropped = [], 0
                for t in book:
                    if t.get("status") == "RESOLVED" and dropped < drop:
                        dropped += 1
                        continue
                    kept.append(t)
                book = kept
            self._save(book)
            self._write_report(book)
        except Exception as e:
            logger.warning(f"ShadowBook.resolve_open failed: {e}")

    @staticmethod
    def _walk(trade, candles):
        """Pessimistic candle walk → outcome dict or None (still open)."""
        entry_ts = float(trade["opened_at"])
        deadline = entry_ts + _TIME_EXIT_H * 3600
        is_long = trade["direction"] == "LONG"
        sl, tp = float(trade["sl_price"]), float(trade["tp_price"])
        entry = float(trade["entry_price"])

        for c in candles:
            ts, high, low, close = c[0] / 1000.0, float(c[2]), float(c[3]), float(c[4])
            if ts < entry_ts:
                continue
            hit_sl = (low <= sl) if is_long else (high >= sl)
            hit_tp = (high >= tp) if is_long else (low <= tp)
            if hit_sl:  # pessimistic: SL wins inside the same candle
                pnl = -_SL_PCT
                reason = "SL"
            elif hit_tp:
                pnl = _TP_PCT
                reason = "TP"
            elif ts >= deadline:
                pnl = (close / entry - 1) * 100 * (1 if is_long else -1)
                reason = "TIME"
            else:
                continue
            return {
                "pnl_pct": round(pnl, 3),
                "exit_reason": reason,
                "closed_at": ts,
                "closed_iso": datetime.utcfromtimestamp(ts).isoformat(),
            }
        return None

    # ── reporting ─────────────────────────────────────────────────────────────

    @staticmethod
    def _stats(trades):
        pnls = [float(t.get("pnl_pct", 0)) for t in trades]
        if not pnls:
            return {"n": 0}
        wins = [p for p in pnls if p > 0]
        return {
            "n": len(pnls),
            "wr": round(len(wins) / len(pnls) * 100, 1),
            "avg_pnl_pct": round(sum(pnls) / len(pnls), 3),
            "total_pnl_pct": round(sum(pnls), 2),
        }

    def _write_report(self, book):
        cutoff = time.time() - _REPORT_DAYS * 86400
        resolved = [
            t for t in book
            if t.get("status") == "RESOLVED" and float(t.get("closed_at", 0)) >= cutoff
        ]
        report = {
            "generated_at": datetime.utcnow().isoformat(),
            "window_days": _REPORT_DAYS,
            "bracket": {"sl_pct": _SL_PCT, "tp_pct": _TP_PCT, "time_exit_h": _TIME_EXIT_H},
            "open_count": sum(1 for t in book if t.get("status") == "OPEN"),
            "overall": self._stats(resolved),
            "by_band": {},
            "by_direction": {},
            "by_asset_class": {},
            "by_decision": {},
            "by_regime": {},
        }
        for lo, hi in _BANDS:
            sel = [t for t in resolved if lo <= abs(float(t.get("score", 0))) < hi]
            report["by_band"][f"{lo:.2f}-{hi:.2f}"] = self._stats(sel)
        for field, key in (("direction", "by_direction"), ("asset_class", "by_asset_class"),
                           ("decision", "by_decision"), ("regime", "by_regime")):
            groups = defaultdict(list)
            for t in resolved:
                groups[str(t.get(field, "?"))].append(t)
            for g, sel in groups.items():
                report[key][g] = self._stats(sel)
        try:
            with open(_REPORT_FILE, "w", encoding="utf-8") as f:
                json.dump(_sanitize(report), f, indent=1)
        except Exception as e:
            logger.warning(f"ShadowBook: could not write {_REPORT_FILE}: {e}")
