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
        self.backtester = AutoBacktester()
        self.min_volume_usdt = 100_000  # $100K minimum daily volume
        self.dashboard_provider = DashboardDataProvider(db_client=db_client)
        
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
        
        try:
            # 1. Fetch Top Assets
            tickers = self.exchange.fetch_tickers()
            
            # Filter for USDC pairs and sort by Volume
            candidates = []
            for symbol, data in tickers.items():
                if '/USDC' in symbol and data['quoteVolume'] is not None:
                     clean_symbol = symbol.split(':')[0]
                     if data['quoteVolume'] > self.min_volume_usdt:
                         candidates.append((clean_symbol, data['quoteVolume']))
            
            candidates.sort(key=lambda x: x[1], reverse=True)
            
            checked_count = 0
            
            self.dashboard_provider.update_agent_status(
                "Scout", "ACTIVE",
                task=f"Found {len(candidates)} pairs above $100K volume",
                reasoning="Filtering by backtest quality...",
                meta={
                    "scanning": [c[0] for c in candidates[:12]],
                    "total_candidates": len(candidates),
                    "reason": "Quality filter: PnL > 0, trades >= 2, volume > $100K"
                },
                cycle_count=cycle_count
            )
            
            for symbol, volume in candidates:
                if checked_count >= 12: break
                
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
                    task=f"Backtesting {symbol} ({checked_count}/12)",
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
                
                result_entry = {
                    "ticker": symbol,
                    "volume_m": round(volume/1e6, 1),
                    "pnl": round(best_pnl, 2),
                    "trades": best_trades,
                    "win_rate": round(best_win_rate, 2),
                    "volatility": round(volatility_score, 2),
                }
                
                if best_pnl > 0 and best_trades >= 2:
                    self.logger.info(f"Candidate {symbol} PASSED {best_direction}. PnL: {best_pnl:.1f}%, Trades: {best_trades}")
                    result_entry["status"] = "APPROVED"
                    result_entry["reason"] = f"Positive {best_direction} backtest: PnL {best_pnl:+.1f}%, {best_trades} trades, WR {best_win_rate:.0%}"
                    proposals.append({
                        "ticker": symbol,
                        "metrics": best_metrics,
                        "reason": f"High Volume (${volume/1e6:.1f}M) & Positive {best_direction} Backtest (PnL: {best_pnl:+.1f}%)",
                        "catalyst_reason": "TA_BACKTEST",
                        "timeframe": "1h Macro",
                        "strategy": "Mean Reversion + Trend",
                        "direction": best_direction
                    })
                else:
                    reasons = []
                    if best_pnl <= 0: reasons.append(f"Negative PnL ({best_pnl:+.1f}%)")
                    if best_trades < 2: reasons.append(f"Too few trades ({best_trades})")
                    
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
                                "metrics": metrics, # Fallback to LONG metrics
                                "reason": f"High Volume with Bullish News Catalyst (Score: {sig:.2f}). Rationale: {rationale}",
                                "catalyst_reason": "NEWS_SENTIMENT",
                                "timeframe": "Macro News",
                                "strategy": "Sentiment Breakout",
                                "direction": "LONG"
                            })
                        elif sig <= 0.3:
                            self.logger.info(f"Candidate {symbol} PASSED on Sentiment breakdown (SHORT). Score: {sig:.2f}")
                            result_entry["status"] = "APPROVED_NEWS"
                            result_entry["reason"] = f"Bearish Catalyst (Score: {sig:.2f}): {rationale[:30]}..."
                            proposals.append({
                                "ticker": symbol,
                                "metrics": short_metrics, # Use SHORT metrics
                                "reason": f"High Volume with Bearish News Catalyst (Score: {sig:.2f}). Rationale: {rationale}",
                                "catalyst_reason": "NEWS_SENTIMENT",
                                "timeframe": "Macro News",
                                "strategy": "Sentiment Breakdown",
                                "direction": "SHORT"
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
            
            # Phase 7 UI Sync: Inject/Override Monitored items
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
            rejected = len([r for r in scan_results if r['status'] == 'REJECTED'])
            skipped = len([r for r in scan_results if r['status'] == 'SKIPPED'])
            monitored_count = len([r for r in scan_results if r['status'] == 'MONITORED'])
            
            self.dashboard_provider.update_agent_status(
                "Scout", "IDLE", 
                task="Waiting for next cycle", 
                reasoning=f"Scan complete. {approved} approved, {monitored_count} monitored, {skipped} skipped, {rejected} rejected.",
                meta={
                    "scan_results": scan_results,
                    "scanned_count": checked_count, 
                    "approved_count": approved,
                    "rejected_count": rejected,
                    "skipped_count": skipped,
                    "monitored_count": monitored_count,
                    "total_universe": len(candidates),
                    "proposals_count": approved
                }, 
                cycle_count=cycle_count
            )
            return proposals

        except Exception as e:
            self.logger.error(f"Error during market scan: {e}")
            self.dashboard_provider.update_agent_status("Scout", "ERROR", task="Error during scan", reasoning=str(e), cycle_count=cycle_count)
            return []
