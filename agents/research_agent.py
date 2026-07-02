import logging
import ccxt
from utils.auto_backtester import AutoBacktester

from utils.dashboard_query_layer import DashboardDataProvider
from agents.sentiment_analyst import SentimentAnalyst
import os # Added for key check

class ResearchAgent:
    def __init__(self, db_client=None):
        self.logger = logging.getLogger("ResearchAgent")
        self.sentiment_analyst = SentimentAnalyst()
        self.logger.info("⚡ SCOUT (ResearchAgent) FORCED RE-INITIALIZATION ⚡")
        
        # Hyperliquid Key Check (per User Mission)
        hl_address = os.getenv("HL_WALLET_ADDRESS")
        hl_key = os.getenv("HL_PRIVATE_KEY")
        if hl_address and hl_key:
             self.logger.info("   ✅ Hyperliquid Keys Detected (Ready for On-Chain)")
        else:
             self.logger.warning("   ⚠️ Hyperliquid Keys MISSING (Scout running in Observation Mode)")

        self.exchange = ccxt.hyperliquid({'options': {'defaultType': 'swap'}})
        from utils.exchange_client import HyperliquidExchange
        self.hl = HyperliquidExchange(testnet=False)
        self.exchange = self.hl.public_client
        # Separate scanner client without market-type filter — needed to see XYZ-* (RWA/equity/commodity)
        # assets which Hyperliquid classifies differently from standard perp swaps.
        self.scanner_exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
        # Workaround: CCXT Hyperliquid fetch_spot_markets crashes with NoneType+str when
        # Hyperliquid lists a new spot token whose base currency CCXT can't map.
        # Patch to return [] on TypeError so perp markets still load correctly.
        _orig_fetch_spot = self.scanner_exchange.fetch_spot_markets
        def _safe_fetch_spot(*a, **kw):
            try:
                return _orig_fetch_spot(*a, **kw)
            except TypeError:
                self.logger.warning("fetch_spot_markets: skipping unmapped spot token (CCXT bug)")
                return []
        self.scanner_exchange.fetch_spot_markets = _safe_fetch_spot
        self.backtester = AutoBacktester()
        self.min_volume_usdt = 100_000  # $100K minimum daily volume
        self.dashboard_provider = DashboardDataProvider(db_client=db_client)
        try:
            from utils.auto_params import AutoParams
            self._auto_params = AutoParams()
        except Exception:
            self._auto_params = None
        
    def _get_market_regime(self) -> dict:
        """
        Detect market regime from BTC 4h data using ADX (trend strength) + ATR (volatility).

        Returns dict:
          regime:    TRENDING_BULL | TRENDING_BEAR | RANGING | VOLATILE
          adx:       float — ADX(14) trend strength
          direction: BULLISH | BEARISH | NEUTRAL — BTC price vs SMA20
          atr_rank:  float 0–1 — current ATR percentile vs last 30 candles

        RANGING fires when ADX ≤ 25 (choppy, no clear trend).
        VOLATILE fires when ATR is in the top 20% of recent history (overrides trend).
        TRENDING_BULL/BEAR when ADX > 25 and direction is clear.
        Falls back to {"regime": "NEUTRAL", ...} on any error.
        """
        _FALLBACK = {"regime": "NEUTRAL", "adx": 20.0, "direction": "NEUTRAL", "atr_rank": 0.5}
        try:
            import pandas as _pd
            import numpy as _np

            candles = self.exchange.fetch_ohlcv("BTC/USDC:USDC", timeframe="4h", limit=50)
            if not candles or len(candles) < 25:
                return _FALLBACK

            df = _pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])

            # Direction: price vs SMA20
            sma20 = float(df["close"].rolling(20).mean().iloc[-1])
            current = float(df["close"].iloc[-1])
            if current < sma20 * 0.995:
                direction = "BEARISH"
            elif current > sma20 * 1.005:
                direction = "BULLISH"
            else:
                direction = "NEUTRAL"

            # ADX(14)
            period = 14
            prev_high  = df["high"].shift(1)
            prev_low   = df["low"].shift(1)
            prev_close = df["close"].shift(1)
            tr = _pd.concat([
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"]  - prev_close).abs(),
            ], axis=1).max(axis=1)
            plus_dm  = _np.where(
                (df["high"] - prev_high > prev_low - df["low"]) & (df["high"] - prev_high > 0),
                df["high"] - prev_high, 0.0
            )
            minus_dm = _np.where(
                (prev_low - df["low"] > df["high"] - prev_high) & (prev_low - df["low"] > 0),
                prev_low - df["low"], 0.0
            )
            atr_s      = _pd.Series(tr.values,        index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            plus_dm_s  = _pd.Series(plus_dm,          index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            minus_dm_s = _pd.Series(minus_dm,         index=df.index).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
            atr_safe   = atr_s.replace(0, 1e-10)
            plus_di    = 100 * plus_dm_s  / atr_safe
            minus_di   = 100 * minus_dm_s / atr_safe
            di_sum     = (plus_di + minus_di).replace(0, 1e-10)
            dx         = 100 * (plus_di - minus_di).abs() / di_sum
            adx        = float(dx.ewm(alpha=1/period, min_periods=period, adjust=False).mean().iloc[-1])

            # ATR rank: percentile of current ATR vs last 30 candles
            recent_atrs = atr_s.dropna().tail(30).values
            atr_now     = float(atr_s.iloc[-1])
            atr_rank    = float(_np.mean(recent_atrs < atr_now)) if len(recent_atrs) > 5 else 0.5

            # Regime classification
            if atr_rank > 0.80:
                regime = "VOLATILE"
            elif adx > 25:
                regime = "TRENDING_BULL" if direction == "BULLISH" else "TRENDING_BEAR"
            else:
                regime = "RANGING"

            self.logger.info(
                f"Market regime: {regime} | ADX={adx:.1f} | dir={direction} | ATR-rank={atr_rank:.2f}"
            )
            return {"regime": regime, "adx": round(adx, 1), "direction": direction, "atr_rank": round(atr_rank, 2)}

        except Exception as e:
            self.logger.debug(f"Market regime check failed: {e}")
            return _FALLBACK

    def _check_4h_swing(self, symbol: str, direction: str) -> bool:
        """
        4h Swing setup promotion test. Returns True if all criteria pass:
          1. 4h RSI(14) in [45, 70]         — not exhausted, not oversold-bounce.
          2. 4h SMA50 vs SMA200 trend align  — SMA50>SMA200 for LONG, reverse for SHORT.
          3. Last 4h candle volume >= 2x avg of previous 10 candles (liquidity check).

        Fundamental gate is NOT enforced here — the downstream MIN_CONVICTION=0.40 gate
        in ProjectLead effectively requires strong fund/sent contribution for swing setups.
        """
        try:
            sym = symbol if ':' in symbol else f"{symbol}:USDC"
            candles = self.scanner_exchange.fetch_ohlcv(sym, timeframe='4h', limit=210)
            if not candles or len(candles) < 200:
                return False

            closes  = [c[4] for c in candles]
            volumes = [c[5] for c in candles]

            # RSI(14) on 4h — direction-aware range
            import pandas as _pd
            cs = _pd.Series(closes)
            delta = cs.diff()
            gains = delta.where(delta > 0, 0).rolling(14).mean()
            losses = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gains / losses.replace(0, 1e-9)
            rsi = 100 - (100 / (1 + rs))
            latest_rsi = float(rsi.iloc[-1]) if not rsi.empty else 50.0
            if direction == "LONG" and not (45.0 <= latest_rsi <= 70.0):
                return False
            if direction == "SHORT" and not (30.0 <= latest_rsi <= 65.0):
                return False

            # Trend alignment: LONG needs SMA50>SMA200 (golden cross); SHORT uses faster
            # SMA20<SMA50 (momentum cross) — death cross (SMA50<SMA200) requires months of
            # downtrend and filters out nearly all short candidates.
            sma20  = sum(closes[-20:])  / 20.0
            sma50  = sum(closes[-50:])  / 50.0
            sma200 = sum(closes[-200:]) / 200.0
            if direction == "LONG" and not (sma50 > sma200):
                return False
            if direction == "SHORT" and not (sma20 < sma50):
                return False

            # Volume confirmation: last 4h candle >= 2x avg of prior 10 candles
            if len(volumes) < 11:
                return False
            prior_avg = sum(volumes[-11:-1]) / 10.0
            if prior_avg <= 0 or volumes[-1] < prior_avg * 2.0:
                return False

            self.logger.info(
                f"4h Swing: {symbol} {direction} passed "
                f"(RSI={latest_rsi:.1f}, SMA50/200 aligned, vol={volumes[-1]/prior_avg:.1f}x)"
            )
            return True
        except Exception as e:
            self.logger.debug(f"4h swing check failed for {symbol}: {e}")
            return False

    def _check_mean_reversion_setup(self, symbol: str) -> dict | None:
        """
        Check if a ticker is at an RSI/BB extreme suitable for mean reversion.
        Returns {"direction": "LONG"|"SHORT", "rsi": float, "pct_b": float} or None.

        Entry criteria (1h timeframe):
          LONG:  RSI(14) < 35  AND  BB %B < 0.25  (oversold, price near lower band)
          SHORT: RSI(14) > 65  AND  BB %B > 0.75  (overbought, price near upper band)
        Requires at least 50 candles for reliable BB/RSI calculation.
        """
        try:
            import pandas as _pd
            import numpy as _np

            sym = symbol if ':' in symbol else f"{symbol}:USDC"
            candles = self.scanner_exchange.fetch_ohlcv(sym, timeframe='1h', limit=60)
            if not candles or len(candles) < 50:
                return None

            df = _pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            close = df['close']

            # RSI(14)
            delta = close.diff()
            gain  = delta.where(delta > 0, 0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            loss  = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
            rs    = gain / loss.replace(0, 1e-9)
            rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

            # BB %B (20, 2)
            mid   = close.rolling(20).mean()
            std   = close.rolling(20).std()
            upper = mid + 2 * std
            lower = mid - 2 * std
            bb_range = upper - lower
            pct_b = float(((close - lower) / bb_range.replace(0, 1e-10)).iloc[-1])

            if rsi < 35 and pct_b < 0.25:
                return {"direction": "LONG",  "rsi": round(rsi, 1), "pct_b": round(pct_b, 2)}
            if rsi > 65 and pct_b > 0.75:
                return {"direction": "SHORT", "rsi": round(rsi, 1), "pct_b": round(pct_b, 2)}
            return None

        except Exception as e:
            self.logger.debug(f"Mean reversion check failed for {symbol}: {e}")
            return None

    def scan_market(self, current_active_assets: list, cycle_count: int = 0, monitored_tickers: list = None) -> list:
        """
        Scans top assets, backtests them, and returns promotion proposals.
        Logs per-ticker results for dashboard visibility.
        """
        self.logger.info("Research Agent: Starting Market Scan...")
        self.dashboard_provider.update_agent_status(
            "Scout", "ACTIVE", 
            task="Scanning Market", 
            reasoning="Starting scan (Quality Filter Active)", 
            meta={"quality_filter": True, "min_volume": "$100K"},
            cycle_count=cycle_count
        )
        
        proposals = []
        scan_results = []  # Per-ticker results for Scout dashboard page

        # Detect macro market regime before scanning
        market_regime = self._get_market_regime()  # dict: {regime, adx, direction, atr_rank}
        regime_label  = market_regime.get("regime", "NEUTRAL")
        self.logger.info(f"Macro regime: {regime_label} (ADX={market_regime.get('adx')}, dir={market_regime.get('direction')})")

        try:
            # 1. Fetch Top Assets — use scanner_exchange (no market-type filter) to include XYZ-* RWA/equity assets
            tickers = self.scanner_exchange.fetch_tickers()

            # Filter for USDC pairs, deduplicate on clean_symbol (keep highest volume), sort by volume
            best_volume: dict = {}
            for symbol, data in tickers.items():
                if '/USDC' in symbol and data.get('quoteVolume') is not None:
                    clean_symbol = symbol.split(':')[0]
                    vol = data['quoteVolume']
                    if vol > self.min_volume_usdt and vol > best_volume.get(clean_symbol, 0):
                        best_volume[clean_symbol] = vol

            candidates = sorted(best_volume.items(), key=lambda x: x[1], reverse=True)

            scan_universe_size = int(
                self._auto_params.get_candidate_value("scan_universe_size")
                if self._auto_params else 12
            )

            # BL-002 universe tilt (2026-07-02): guarantee XYZ equities a floor of
            # ~1/3 of the scan universe. Shadow data (n=534): tech_stock is the only
            # consistently profitable asset class (WR 49.6% vs crypto 36.7%), but XYZ
            # volume is dwarfed by major crypto pairs, so a pure volume sort crowds
            # them out of the top-N window. Reserve slots for the highest-volume XYZ
            # equities and re-merge; the tail keeps volume order as overflow.
            from core.strategy_logic import detect_asset_class
            xyz_slots = max(0, scan_universe_size // 3)
            _xyz_eq = [c for c in candidates if detect_asset_class(c[0]) == 'tech_stock']
            _rest   = [c for c in candidates if detect_asset_class(c[0]) != 'tech_stock']
            _guaranteed = _xyz_eq[:xyz_slots]
            _head = _rest[:scan_universe_size - len(_guaranteed)]
            _selected = sorted(_head + _guaranteed, key=lambda x: x[1], reverse=True)
            _tail = [c for c in candidates if c not in _selected]
            candidates = _selected + _tail
            if _guaranteed:
                self.logger.info(
                    f"[UniverseTilt] {len(_guaranteed)} XYZ equity slots guaranteed in top {scan_universe_size}: "
                    f"{[c[0] for c in _guaranteed]}"
                )

            checked_count = 0

            self.dashboard_provider.update_agent_status(
                "Scout", "ACTIVE",
                task=f"Found {len(candidates)} pairs above $100K volume",
                reasoning="Filtering by backtest quality...",
                meta={
                    "scanning": [c[0] for c in candidates[:scan_universe_size]],
                    "total_candidates": len(candidates),
                    "reason": "Quality filter: PnL > 0, trades >= 2, volume > $100K"
                },
                cycle_count=cycle_count
            )
            
            for symbol, volume in candidates:
                if checked_count >= scan_universe_size: break
                
                # Exclude existing active assets
                if symbol in current_active_assets:
                    continue
                    
                # Exclude Stablecoins since they do not trend and have no volatility
                if any(x in symbol for x in ['TUSD', 'FDUSD', 'DAI', 'USDT']):
                    scan_results.append({
                        "ticker": symbol,
                        "volume_m": round(volume/1e6, 1),
                        "pnl": 0, "trades": 0, "win_rate": 0, "volatility": 0,
                        "status": "SKIPPED",
                        "reason": "Excluded (stablecoin)"
                    })
                    continue
                
                checked_count += 1
                self.logger.info(f"Researching candidate: {symbol}...")
                
                self.dashboard_provider.update_agent_status(
                    "Scout", "ACTIVE", 
                    task=f"Backtesting {symbol} ({checked_count}/{scan_universe_size})",
                    reasoning=f"Vol: ${volume/1e6:.0f}M | Running backtest...",
                    meta={"scan_results": scan_results[-10:], "current_target": symbol}, 
                    cycle_count=cycle_count
                )
                
                # 2. Backtest & Volatility
                df = self.backtester.fetch_historical_data(symbol)
                metrics = self.backtester.run_simulation(df)
                
                volatility_score = 0.0
                if df is not None and not df.empty:
                    pct_change = df['close'].pct_change()
                    volatility_score = pct_change.std() * 100
                
                # 3. Validation (Bi-Directional)
                pnl_long = metrics.get('total_pnl_pct', -999)
                trades_long = metrics.get('trades', 0)
                win_rate_long = metrics.get('win_rate', 0)

                short_metrics = metrics.get('agent_short', {})
                pnl_short = short_metrics.get('total_pnl_pct', -999)
                trades_short = short_metrics.get('trades', 0)
                win_rate_short = short_metrics.get('win_rate', 0)

                # Determine best direction by PnL
                best_direction = "LONG"
                best_metrics = metrics
                best_pnl = pnl_long
                best_trades = trades_long
                best_win_rate = win_rate_long

                if pnl_short > pnl_long and trades_short >= 2:
                    best_direction = "SHORT"
                    best_metrics = short_metrics
                    best_pnl = pnl_short
                    best_trades = trades_short
                    best_win_rate = win_rate_short

                # Macro regime override: in TRENDING_BEAR market, force SHORT when it outperforms.
                # XYZ-* assets (stocks/commodities) are exempt — they don't correlate with BTC.
                _is_xyz = symbol.startswith('XYZ-')
                if regime_label in ("TRENDING_BEAR", "BEARISH") and not _is_xyz:
                    if trades_short >= 2 and (pnl_short > pnl_long or pnl_long < 0):
                        self.logger.info(
                            f"Macro regime BEARISH — forcing {symbol} SHORT "
                            f"(long PnL {pnl_long:+.1f}%, short PnL {pnl_short:+.1f}%)"
                        )
                        best_direction = "SHORT"
                        best_metrics = short_metrics
                        best_pnl = pnl_short
                        best_trades = trades_short
                        best_win_rate = win_rate_short
                
                result_entry = {
                    "ticker": symbol,
                    "volume_m": round(volume/1e6, 1),
                    "pnl": round(best_pnl, 2),
                    "trades": best_trades,
                    "win_rate": round(best_win_rate, 2),
                    "volatility": round(volatility_score, 2),
                }
                
                # Gate: positive PnL, min trade sample, AND realised R after costs >= 1.5.
                # rr_after_costs (auto_backtester) deducts round-trip fee+slippage from
                # avg win/loss before computing R, killing marginal-edge strategies that
                # only "work" without transaction costs.
                rr_after = best_metrics.get('rr_after_costs', 0.0)
                MIN_RR_AFTER_COSTS = 1.5
                if best_pnl > 0 and best_trades >= 2 and rr_after >= MIN_RR_AFTER_COSTS:
                    self.logger.info(
                        f"Candidate {symbol} PASSED {best_direction}. "
                        f"PnL: {best_pnl:.1f}%, Trades: {best_trades}, RR-after-costs: {rr_after:.2f}"
                    )
                    result_entry["status"] = "APPROVED"
                    result_entry["reason"] = (
                        f"Positive {best_direction} backtest: PnL {best_pnl:+.1f}%, "
                        f"{best_trades} trades, WR {best_win_rate:.0%}, RR/costs {rr_after:.2f}"
                    )

                    # Promote to 4h Swing if structural criteria pass (RSI/SMA/volume on 4h)
                    is_swing = self._check_4h_swing(symbol, best_direction)
                    _timeframe       = "4h Swing" if is_swing else "1h Macro"
                    _catalyst_reason = "SWING_4H" if is_swing else "TA_BACKTEST"
                    _strategy        = "Swing Trend-Follow" if is_swing else "Mean Reversion + Trend"
                    if is_swing:
                        result_entry["reason"] += " | 4h Swing upgraded"

                    proposals.append({
                        "ticker": symbol,
                        "metrics": best_metrics,
                        "reason": f"High Volume (${volume/1e6:.1f}M) & Positive {best_direction} Backtest (PnL: {best_pnl:+.1f}%)",
                        "catalyst_reason": _catalyst_reason,
                        "timeframe": _timeframe,
                        "strategy": _strategy,
                        "direction": best_direction,
                        "market_regime": market_regime,
                    })
                else:
                    reasons = []
                    if best_pnl <= 0: reasons.append(f"Negative PnL ({best_pnl:+.1f}%)")
                    if best_trades < 2: reasons.append(f"Too few trades ({best_trades})")
                    if best_pnl > 0 and best_trades >= 2 and rr_after < MIN_RR_AFTER_COSTS:
                        reasons.append(f"RR after costs {rr_after:.2f} < {MIN_RR_AFTER_COSTS}")
                    
                    # Discovery Expansion: Fallback to news sentiment for top 5 highest volume tokens
                    if checked_count <= 5:
                        self.logger.info(f"TA failed for {symbol}. Checking news sentiment for breakout/breakdown potential...")
                        sentiment_res = self.sentiment_analyst.analyze(symbol)
                        sig = sentiment_res.get("signal", 0.0)
                        rationale = sentiment_res.get("metrics", {}).get("rationale", "")
                        
                        if sig >= 0.6:
                            self.logger.info(f"Candidate {symbol} PASSED on Sentiment breakout (LONG). Score: {sig:.2f}")
                            result_entry["status"] = "APPROVED_NEWS"
                            result_entry["reason"] = f"Bullish Catalyst (Score: {sig:.2f}): {rationale[:30]}..."
                            proposals.append({
                                "ticker": symbol,
                                "metrics": metrics,
                                "reason": f"High Volume with Bullish News Catalyst (Score: {sig:.2f}). Rationale: {rationale}",
                                "catalyst_reason": "NEWS_SENTIMENT",
                                "timeframe": "Macro News",
                                "strategy": "Sentiment Breakout",
                                "direction": "LONG",
                                "market_regime": market_regime,
                            })
                        elif sig <= 0.3:
                            self.logger.info(f"Candidate {symbol} PASSED on Sentiment breakdown (SHORT). Score: {sig:.2f}")
                            result_entry["status"] = "APPROVED_NEWS"
                            result_entry["reason"] = f"Bearish Catalyst (Score: {sig:.2f}): {rationale[:30]}..."
                            proposals.append({
                                "ticker": symbol,
                                "metrics": short_metrics,
                                "reason": f"High Volume with Bearish News Catalyst (Score: {sig:.2f}). Rationale: {rationale}",
                                "catalyst_reason": "NEWS_SENTIMENT",
                                "timeframe": "Macro News",
                                "strategy": "Sentiment Breakdown",
                                "direction": "SHORT",
                                "market_regime": market_regime,
                            })
                        else:
                            result_entry["status"] = "REJECTED"
                            result_entry["reason"] = " & ".join(reasons) + f" | Neutral News ({sig:.2f})"
                            self.logger.info(f"Candidate {symbol} rejected on TA and Sentiment. {result_entry['reason']}")
                    else:
                        result_entry["status"] = "REJECTED"
                        result_entry["reason"] = " & ".join(reasons)
                        self.logger.info(f"Candidate {symbol} rejected. {result_entry['reason']}")
                
                scan_results.append(result_entry)
            
            # Phase 7: Mean Reversion scan — only in RANGING regime.
            # Scans the same top-volume universe for RSI/BB extremes that momentum
            # signals miss. Adds proposals with catalyst="MEAN_REVERSION" so ProjectLead
            # and TechnicalAnalyst know to use mean-reversion weights and skip ADX damping.
            if regime_label == "RANGING":
                approved_tickers = {p["ticker"] for p in proposals}
                mr_count = 0
                _MR_MAX = 4  # don't flood the pipeline with mean reversion proposals
                for symbol, volume in candidates[:scan_universe_size]:
                    if mr_count >= _MR_MAX:
                        break
                    if symbol in current_active_assets or symbol in approved_tickers:
                        continue
                    if any(x in symbol for x in ['TUSD', 'FDUSD', 'DAI', 'USDT']):
                        continue
                    mr = self._check_mean_reversion_setup(symbol)
                    if mr is None:
                        continue
                    direction = mr["direction"]
                    self.logger.info(
                        f"[MeanRev] {symbol} {direction}: RSI={mr['rsi']} %B={mr['pct_b']} — RANGING extreme"
                    )
                    proposals.append({
                        "ticker": symbol,
                        "metrics": {},
                        "reason": (
                            f"RANGING mean reversion {direction}: RSI={mr['rsi']} %B={mr['pct_b']} "
                            f"(vol ${volume/1e6:.1f}M)"
                        ),
                        "catalyst_reason": "MEAN_REVERSION",
                        "timeframe":       "1h MeanRev",
                        "strategy":        f"Mean Reversion ({direction})",
                        "direction":       direction,
                        "market_regime":   market_regime,
                    })
                    scan_results.append({
                        "ticker":     symbol,
                        "volume_m":   round(volume / 1e6, 1),
                        "pnl":        0.0, "trades": 0, "win_rate": 0.0,
                        "volatility": 0.0,
                        "status":     "APPROVED_MR",
                        "reason":     f"MeanRev {direction}: RSI={mr['rsi']} %B={mr['pct_b']}",
                    })
                    approved_tickers.add(symbol)
                    mr_count += 1
                if mr_count:
                    self.logger.info(f"Mean reversion scan: {mr_count} setup(s) found in RANGING regime")

            # Phase 8 UI Sync: Inject/Override Monitored items
            if monitored_tickers:
                for mt in monitored_tickers:
                    # Check if already in scan_results
                    existing = next((r for r in scan_results if r['ticker'] == mt), None)
                    if existing:
                        existing['status'] = 'MONITORED'
                        existing['reason'] = 'Active Watchlist: Awaiting Micro Setup'
                    else:
                        scan_results.append({
                            "ticker": mt,
                            "volume_m": 0.0,
                            "pnl": 0.0, "trades": 0, "win_rate": 0.0, "volatility": 0.0,
                            "status": "MONITORED",
                            "reason": "Tracking in Watchlist"
                        })
            
            # Sort scan_results (approved -> monitored -> skipped -> rejected)
            order_val = {"APPROVED": 0, "APPROVED_NEWS": 1, "MONITORED": 2, "SKIPPED": 3, "REJECTED": 4}
            scan_results.sort(key=lambda x: order_val.get(x.get("status"), 99))
            
            approved = len(proposals)
            mr_approved = len([r for r in scan_results if r['status'] == 'APPROVED_MR'])
            rejected = len([r for r in scan_results if r['status'] == 'REJECTED'])
            skipped = len([r for r in scan_results if r['status'] == 'SKIPPED'])
            monitored_count = len([r for r in scan_results if r['status'] == 'MONITORED'])
            
            # Persist regime for TreasuryAgent allocation decisions
            try:
                import json as _j
                with open("market_regime.json", "w") as _f:
                    _j.dump(market_regime, _f)
            except Exception as _e:
                self.logger.debug(f"Could not write market_regime.json: {_e}")

            self.dashboard_provider.update_agent_status(
                "Scout", "IDLE",
                task="Waiting for next cycle",
                reasoning=f"Scan complete. {approved} approved ({mr_approved} MR), {monitored_count} monitored, {skipped} skipped, {rejected} rejected. Regime: {regime_label}",
                meta={
                    "scan_results": scan_results,
                    "scanned_count": checked_count,
                    "approved_count": approved,
                    "rejected_count": rejected,
                    "skipped_count": skipped,
                    "monitored_count": monitored_count,
                    "total_universe": len(candidates),
                    "proposals_count": approved,
                    "market_regime": market_regime,
                },
                cycle_count=cycle_count
            )
            return proposals

        except Exception as e:
            self.logger.error(f"Error during market scan: {e}")
            self.dashboard_provider.update_agent_status("Scout", "ERROR", task="Error during scan", reasoning=str(e), cycle_count=cycle_count)
            return []
