"""
CorrelationTracker — computes and caches a rolling daily-return correlation matrix
across USDC-quoted perps on Hyperliquid. Used by RiskManager to block trades that
would stack correlated exposure.

Cache: correlation_matrix.json (24h TTL). Refresh on miss or stale.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional

try:
    import ccxt  # type: ignore
except Exception:  # pragma: no cover
    ccxt = None


class CorrelationTracker:
    CACHE_PATH = "correlation_matrix.json"
    TTL_SECONDS = 24 * 3600
    LOOKBACK_DAYS = 30

    def __init__(self, exchange=None):
        self.logger = logging.getLogger("CorrelationTracker")
        if exchange is not None:
            self.exchange = exchange
        elif ccxt is not None:
            self.exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        else:
            self.exchange = None
        self._matrix: Dict[str, Dict[str, float]] = {}
        self._loaded_at = 0.0
        self._load_cache()

    # ---------------- cache ----------------
    def _load_cache(self) -> None:
        try:
            with open(self.CACHE_PATH, "r") as f:
                data = json.load(f)
            self._matrix = data.get("matrix", {})
            self._loaded_at = float(data.get("updated_at", 0))
        except (FileNotFoundError, json.JSONDecodeError):
            self._matrix = {}
            self._loaded_at = 0.0

    def _save_cache(self) -> None:
        try:
            with open(self.CACHE_PATH, "w") as f:
                json.dump({"updated_at": self._loaded_at, "matrix": self._matrix}, f)
        except Exception as e:
            self.logger.warning(f"Failed to persist correlation cache: {e}")

    def _is_stale(self) -> bool:
        return (time.time() - self._loaded_at) > self.TTL_SECONDS

    # ---------------- building the matrix ----------------
    @staticmethod
    def _clean_symbol(sym: str) -> str:
        return sym.split(':')[0].replace('/USDC', '').replace('/USDT', '')

    @staticmethod
    def _pct_returns(closes: List[float]) -> List[float]:
        if len(closes) < 2:
            return []
        rets = []
        for i in range(1, len(closes)):
            prev = closes[i-1]
            if prev > 0:
                rets.append((closes[i] - prev) / prev)
        return rets

    @staticmethod
    def _pearson(a: List[float], b: List[float]) -> float:
        n = min(len(a), len(b))
        if n < 5:
            return 0.0
        a = a[-n:]; b = b[-n:]
        mean_a = sum(a) / n
        mean_b = sum(b) / n
        num = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
        den_a = (sum((x - mean_a) ** 2 for x in a)) ** 0.5
        den_b = (sum((x - mean_b) ** 2 for x in b)) ** 0.5
        if den_a == 0 or den_b == 0:
            return 0.0
        return num / (den_a * den_b)

    def refresh(self, tickers: Optional[List[str]] = None) -> None:
        if self.exchange is None:
            self.logger.warning("No exchange — cannot refresh correlation matrix")
            return
        if tickers is None:
            try:
                all_tickers = self.exchange.fetch_tickers()
                vol_sorted = sorted(
                    [(s, d.get('quoteVolume') or 0) for s, d in all_tickers.items() if '/USDC' in s],
                    key=lambda x: x[1], reverse=True
                )
                tickers = [self._clean_symbol(s) for s, _ in vol_sorted[:40]]
                tickers = list(dict.fromkeys(tickers))  # dedup, preserve order
            except Exception as e:
                self.logger.error(f"Could not fetch ticker universe: {e}")
                return

        self.logger.info(f"Correlation refresh on {len(tickers)} tickers ({self.LOOKBACK_DAYS}d lookback)")
        returns: Dict[str, List[float]] = {}
        for t in tickers:
            sym = f"{t}/USDC:USDC"
            try:
                ohlcv = self.exchange.fetch_ohlcv(sym, timeframe='1d', limit=self.LOOKBACK_DAYS + 1)
                if not ohlcv or len(ohlcv) < 10:
                    continue
                closes = [c[4] for c in ohlcv]
                rets = self._pct_returns(closes)
                if len(rets) >= 10:
                    returns[t] = rets
            except Exception as e:
                self.logger.debug(f"OHLCV fetch failed for {sym}: {e}")
                continue

        keys = sorted(returns.keys())
        matrix: Dict[str, Dict[str, float]] = {}
        for i, a in enumerate(keys):
            matrix[a] = {}
            for b in keys:
                if a == b:
                    matrix[a][b] = 1.0
                elif b in matrix and a in matrix[b]:
                    matrix[a][b] = matrix[b][a]
                else:
                    matrix[a][b] = round(self._pearson(returns[a], returns[b]), 4)
        self._matrix = matrix
        self._loaded_at = time.time()
        self._save_cache()
        self.logger.info(f"Correlation matrix updated with {len(matrix)} tickers")

    def _refresh_if_stale(self) -> None:
        if not self._matrix or self._is_stale():
            try:
                self.refresh()
            except Exception as e:
                self.logger.warning(f"Correlation refresh failed (using stale matrix): {e}")

    # ---------------- query ----------------
    def get_correlation(self, a: str, b: str) -> Optional[float]:
        self._refresh_if_stale()
        a = self._clean_symbol(a); b = self._clean_symbol(b)
        row = self._matrix.get(a) or {}
        if b in row:
            return row[b]
        row_b = self._matrix.get(b) or {}
        return row_b.get(a)

    def weighted_exposure_correlation(self, new_ticker: str, new_direction: str,
                                       open_positions: List[dict]) -> Dict[str, float]:
        """
        Returns weighted correlation of `new_ticker` against open positions in the
        SAME direction (sign-aware). Weight = position notional value.

        {weighted_corr: float, max_corr: float, reference_ticker: str}
        """
        if not open_positions:
            return {"weighted_corr": 0.0, "max_corr": 0.0, "reference_ticker": None}

        new_is_long = (new_direction or "").upper() in ("BUY", "LONG")
        num, den, max_abs, ref = 0.0, 0.0, 0.0, None
        for p in open_positions:
            p_action = (p.get('action') or '').upper()
            p_is_long = p_action in ('BUY', 'LONG')
            # Only stack same-direction exposure as risk. Opposite direction = partial hedge.
            same_dir = (new_is_long == p_is_long)
            if not same_dir:
                continue
            p_ticker = p.get('ticker') or ''
            size = abs(float(p.get('trade_value') or p.get('quantity', 0) * p.get('entry_price', 0) or 0))
            if size <= 0:
                size = 1.0
            corr = self.get_correlation(new_ticker, p_ticker)
            if corr is None:
                continue
            num += corr * size
            den += size
            if abs(corr) > abs(max_abs):
                max_abs = corr
                ref = p_ticker

        weighted = num / den if den > 0 else 0.0
        return {"weighted_corr": round(weighted, 4),
                "max_corr": round(max_abs, 4),
                "reference_ticker": ref}
