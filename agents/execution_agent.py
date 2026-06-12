import json
import math
import os
import time
import logging
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
from utils.db_client import DatabaseClient

load_dotenv()

TRADE_LOG_FILE = "trade_log.json"
APPROVAL_THRESHOLD = float(os.getenv("APPROVAL_THRESHOLD", "1000"))  # Default $1000

def _sanitize_trade(obj):
    """Recursively replace NaN/Inf with safe values so json.dump never fails."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_trade(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_trade(v) for v in obj]
    return obj

from utils.pipeline_events import log_event as log_pipeline_event
from utils.exchange_client import HyperliquidExchange


def _entry_ts_ms(trade) -> int | None:
    """Entry timestamp in ms for ledger queries. Trade logs hold a mix of
    ISO strings and unix-epoch floats (import scripts) — parse both."""
    raw = trade.get('entry_time') or trade.get('approval_time')
    if not raw:
        return None
    try:
        return int(float(raw) * 1000)  # epoch seconds (possibly fractional)
    except (TypeError, ValueError):
        pass
    try:
        return int(datetime.fromisoformat(str(raw)).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _send_telegram(text: str):
    """Send a Telegram notification. Reads secrets lazily so they are available after startup injection."""
    try:
        from utils.gcp_secrets import get_secret
        token = os.getenv("TELEGRAM_BOT_TOKEN") or get_secret("TELEGRAM_BOT_TOKEN") or ""
        chat_id = os.getenv("TELEGRAM_CHAT_ID") or get_secret("TELEGRAM_CHAT_ID") or ""
        if not token or not chat_id:
            return
        import urllib.request, urllib.parse
        params = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=params, method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as _tg_err:
        logging.getLogger("ExecutionAgent").warning(f"Telegram send failed: {_tg_err}")

class ExecutionAgent:
    """
    Handles trade execution on Hyperliquid L1.
    Includes Human-in-the-Loop (HITL) approval workflow.
    """
    def __init__(self):
        self.logger = logging.getLogger("ExecutionAgent")
        self.exchange = HyperliquidExchange(testnet=False) # Mainnet

        self.dashboard_file = "dashboard.json"
        self.ensure_log_file()
        self.db = DatabaseClient()
        self._in_flight = set()        # tickers with live orders not yet logged
        self._in_flight_lock = threading.Lock()
        self.logger.info(f"Execution Agent initialized with approval threshold: ${APPROVAL_THRESHOLD}")
        self._sync_open_positions_on_startup()
        try:
            from agents.strategy_manager import StrategyManager
            self.strategy_manager = StrategyManager()
        except Exception as e:
            self.logger.error(f"Failed to load StrategyManager: {e}")
            self.strategy_manager = None

    def ensure_log_file(self):
        if not os.path.exists(TRADE_LOG_FILE):
            with open(TRADE_LOG_FILE, "w") as f:
                json.dump([], f)

    def _sync_open_positions_on_startup(self):
        """On startup, reconcile live HL open positions into trade_log.json.

        Prevents the dashboard from showing 0 open trades after a container
        restart when positions were already open on Hyperliquid.
        Any position not already tracked as OPEN/PLACED is added as an OPEN record
        with source='HL_POSITION_SYNC'.
        """
        try:
            ex = self.exchange
            if not ex.signing_client:
                return
            positions = ex.fetch_all_positions()
        except Exception as e:
            self.logger.warning(f"Startup position sync skipped: {e}")
            return

        open_positions = [
            p for p in positions
            if abs(float((p.get('info') or {}).get('szi', 0) or p.get('contracts') or 0)) > 1e-9
        ]
        if not open_positions:
            return

        try:
            with open(TRADE_LOG_FILE) as f:
                trades = json.load(f)
        except Exception:
            trades = []

        open_tickers = {
            t["ticker"].split("/")[0].upper()
            for t in trades
            if t.get("status") in ("OPEN", "PLACED")
        }

        # Load StrategyManager locally for TP/SL calculation
        try:
            from agents.strategy_manager import StrategyManager
            _sm = StrategyManager()
        except Exception:
            _sm = None

        DEFAULT_SL_PCT = 10.0   # 10% SL from entry for synced positions
        DEFAULT_RRR    = 1.5    # 1:1.5 risk/reward

        # --- Backfill pass: patch existing OPEN trades that are missing TP/SL ---
        backfilled = 0
        if _sm:
            for t in trades:
                if t.get("status") not in ("OPEN", "PLACED"):
                    continue
                if t.get("harvest"):
                    continue  # Treasury harvest positions: managed by TreasuryAgent
                if t.get("take_profit") and t.get("stop_loss"):
                    continue  # Already has levels
                ep = t.get("entry_price", 0.0)
                if not ep:
                    continue
                act = t.get("action", "BUY")
                levels = _sm.calculate_levels(ep, act, DEFAULT_RRR, DEFAULT_SL_PCT)
                t["take_profit"] = levels.get("take_profit", 0.0)
                t["stop_loss"]   = levels.get("stop_loss", 0.0)
                t.setdefault("sl_pct", DEFAULT_SL_PCT)
                t.setdefault("sl_stage", 0)
                t.setdefault("partial_tp1_taken", False)
                t.setdefault("partial_exits", [])
                backfilled += 1
            if backfilled:
                try:
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=2, default=str)
                    self.logger.info(f"Startup position sync: backfilled TP/SL for {backfilled} existing OPEN trade(s)")
                except Exception as e:
                    self.logger.error(f"Startup position sync: failed to write backfilled TP/SL: {e}")

        added = 0
        now_ts = datetime.utcnow()
        for pos in open_positions:
            info = pos.get("info") or {}
            symbol = pos.get("symbol", "")
            base = symbol.split("/")[0].upper()
            if base in open_tickers:
                continue

            ticker = symbol.split(":")[0]
            # Determine direction: prefer szi (signed), then CCXT 'side', then contracts
            _szi = float(info.get("szi") or 0)
            _ccxt_side = pos.get("side", "")  # "long" or "short" — reliable for XYZ assets
            _contracts_raw = float(pos.get("contracts") or 0)
            if _szi != 0:
                direction = "long" if _szi > 0 else "short"
                qty = abs(_szi)
            elif _ccxt_side in ("long", "short"):
                direction = _ccxt_side
                qty = abs(_contracts_raw)
            else:
                direction = "long" if _contracts_raw > 0 else "short"
                qty = abs(_contracts_raw)
            entry_price = float(pos.get("entryPrice") or info.get("entryPx") or 0)
            mark_price = float(pos.get("markPrice") or info.get("markPx") or entry_price)
            unrealized_pnl = float(pos.get("unrealizedPnl") or info.get("unrealizedPnl") or 0)
            trade_id = f"HL_OPEN_{base}_{int(now_ts.timestamp() * 1000)}"

            # Compute TP/SL from entry price so evaluate_position can manage this trade
            action = "BUY" if direction == "long" else "SELL"
            tp, sl, sl_pct = 0.0, 0.0, DEFAULT_SL_PCT
            if _sm and entry_price:
                levels = _sm.calculate_levels(entry_price, action, DEFAULT_RRR, DEFAULT_SL_PCT)
                tp    = levels.get("take_profit", 0.0)
                sl    = levels.get("stop_loss", 0.0)
                sl_pct = levels.get("sl_pct", DEFAULT_SL_PCT)

            record = {
                "id": trade_id,
                "ticker": ticker,
                "action": action,
                "status": "OPEN",
                "entry_price": entry_price,
                "exit_price": None,
                "quantity": qty,
                "pnl": round(unrealized_pnl, 4),
                "pnl_percent": round(
                    ((entry_price - mark_price) / entry_price * 100 if direction == "short"
                     else (mark_price - entry_price) / entry_price * 100), 2
                ) if entry_price else 0.0,
                "entry_fmt": now_ts.strftime("%Y-%m-%dT%H:%M:%S"),
                "entry_time": now_ts.timestamp(),
                "exit_time": None,
                "close_reason": None,
                "source": "HL_POSITION_SYNC",
                "conviction": 0.0,
                "fees": 0.0,
                "take_profit": tp,
                "stop_loss": sl,
                "sl_pct": sl_pct,
                "sl_stage": 0,
                "partial_tp1_taken": False,
                "partial_exits": [],
                "analyst_signals": {},
            }
            trades.append(record)
            open_tickers.add(base)
            added += 1
            try:
                self.db.log_trade({
                    "ticker": ticker, "action": action, "conviction": 0.0,
                    "price": entry_price, "quantity": qty,
                    "risk_metrics": {"source": "HL_POSITION_SYNC", "take_profit": tp, "stop_loss": sl, "sl_pct": sl_pct},
                    "analyst_signals": {},
                })
            except Exception as _dbe:
                self.logger.warning(f"Startup sync: Supabase log failed for {ticker}: {_dbe}")

        if added:
            try:
                with open(TRADE_LOG_FILE, "w") as f:
                    json.dump(trades, f, indent=2, default=str)
                self.logger.info(f"Startup position sync: added {added} OPEN trade(s) from Hyperliquid (with TP/SL)")
            except Exception as e:
                self.logger.error(f"Startup position sync: failed to write trade_log.json: {e}")

        # ── Startup Pass 3: close OPEN trades no longer on HL ────────────────
        hl_bases_live = {
            p.get("symbol", "").split("/")[0].upper()
            for p in open_positions
        }
        startup_closed = 0
        _now_iso = datetime.utcnow().isoformat()
        _now_epoch = datetime.utcnow().timestamp()
        for t in trades:
            if t.get("status") not in ("OPEN", "PLACED"):
                continue
            if t.get("harvest"):
                continue  # Treasury harvest positions: managed by TreasuryAgent
            _base = (t.get("ticker") or "").split("/")[0].upper()
            if _base in hl_bases_live:
                continue
            _age_min = (_now_epoch - float(t.get("entry_time") or 0)) / 60
            if _age_min < 5:
                continue
            t["status"]       = "CLOSED"
            t["exit_price"]   = t.get("entry_price", 0)  # best approx at startup
            t["exit_time"]    = _now_iso
            t["close_reason"] = "EXTERNAL_CLOSURE"
            startup_closed += 1
            self.logger.warning(
                f"Startup sync: {t['ticker']} marked CLOSED — "
                f"OPEN in trade_log but not on HL (age={_age_min:.0f}min)"
            )
        if startup_closed:
            try:
                with open(TRADE_LOG_FILE, "w") as f:
                    json.dump(trades, f, indent=2, default=str)
                self.logger.info(
                    f"Startup sync: closed {startup_closed} phantom OPEN trade(s) via EXTERNAL_CLOSURE"
                )
            except Exception as e:
                self.logger.error(f"Startup sync Pass 3: failed to write trade_log: {e}")

    def log_trade(self, trade_data):
        """
        Appends the trade to the JSON log and persists to Supabase.
        """
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                history = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            history = []
            
        history.append(_sanitize_trade(trade_data))

        try:
            with open(TRADE_LOG_FILE, "w") as f:
                json.dump(history, f, indent=4)
        except Exception as dump_err:
            self.logger.critical(
                f"CRITICAL: Failed to write trade_log.json for {trade_data.get('ticker')} — "
                f"trade IS live on exchange but NOT recorded locally! Error: {dump_err}. "
                f"Trade: {trade_data}"
            )
            raise  # re-raise so execute_order can handle it
        
        # NEW: Also log to Supabase for persistence
        try:
            reasoning_trace = trade_data.get('reasoning_trace', {})
            if self.db.log_trade_with_reasoning(trade_data, reasoning_trace):
                self.logger.info(f"✅ Trade persisted to Supabase: {trade_data.get('ticker')}")
            else:
                self.logger.warning(f"⚠️ Supabase write returned False for {trade_data.get('ticker')}")
        except Exception as e:
            self.logger.error(f"⚠️ Supabase logging failed (non-blocking): {e}")
        
        status_msg = trade_data.get('status', 'UNKNOWN')
        if status_msg == 'PENDING_FOUNDER_APPROVAL':
            self.logger.warning(f"⏳ Trade PENDING APPROVAL: {trade_data['ticker']} {trade_data['action']} @ ${trade_data['entry_price']:.2f} (Value: ${trade_data.get('trade_value', 0):.2f})")
        else:
            self.logger.info(f"Trade logged: {trade_data['ticker']} {trade_data['action']} @ {trade_data['entry_price']:.2f}")
    
    def check_approval_status(self, trade_id: str) -> str:
        """
        Checks if a pending trade has been approved/rejected by the Founder.
        Returns: 'APPROVED', 'REJECTED', or 'PENDING'
        """
        if not os.path.exists(self.dashboard_file):
            return 'PENDING'
        
        try:
            with open(self.dashboard_file, "r") as f:
                dashboard_data = json.load(f)
            
            approval_decisions = dashboard_data.get('approval_decisions', {})
            return approval_decisions.get(trade_id, 'PENDING')
        except Exception as e:
            self.logger.error(f"Error checking approval status: {e}")
            return 'PENDING'
    
    def update_pending_approvals(self, trade_data):
        """
        Adds a trade to the pending_approvals list in dashboard.json
        """
        try:
            if os.path.exists(self.dashboard_file):
                with open(self.dashboard_file, "r") as f:
                    dashboard_data = json.load(f)
            else:
                dashboard_data = {"status": "ACTIVE", "market_data": {}}
            
            if 'pending_approvals' not in dashboard_data:
                dashboard_data['pending_approvals'] = []
            
            # Add trade to pending list
            dashboard_data['pending_approvals'].append({
                "trade_id": trade_data['id'],
                "ticker": trade_data['ticker'],
                "action": trade_data['action'],
                "quantity": trade_data['quantity'],
                "price": trade_data['entry_price'],
                "trade_value": trade_data.get('trade_value', 0),
                "conviction": trade_data.get('conviction', 0),
                "synthesis_report": trade_data.get('synthesis_report', ''),
                "status": "PENDING",
                "timestamp": trade_data['entry_fmt']
            })
            
            with open(self.dashboard_file, "w") as f:
                json.dump(dashboard_data, f, indent=4)
                
            self.logger.info(f"Trade {trade_data['id']} added to pending approvals")
        except Exception as e:
            self.logger.error(f"Error updating pending approvals: {e}")
    
    
    def process_approved_trade(self, trade_id: str):
        """
        Executes a previously pending trade after founder approval.
        Includes AUDITOR checks (Staleness & Slippage).
        """
        try:
            # Load trade log
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
            
            # Find the pending trade
            for trade in trades:
                if trade['id'] == trade_id and trade['status'] == 'PENDING_FOUNDER_APPROVAL':
                    
                    self.logger.info(f"🕵️ Running Pre-Flight Auditor for {trade_id}...")
                    
                    # 1. Fetch Current Market Data (L1 Order Book)
                    l1_data = self.exchange.get_l1_orderbook(trade['ticker'])
                    current_price = self.exchange.get_market_price(trade['ticker'])
                    
                    if not l1_data:
                         self.logger.warning("Could not fetch L1 Data. Using purely last price.")
                         l1_data = {"bid": current_price, "ask": current_price}

                    # 2. Run Audit w/ L1 Data
                    audit_result = self.perform_pre_flight_check(trade, current_price, l1_data)
                    
                    if not audit_result['passed']:
                        self.logger.warning(f"❌ AUDITOR BLOCKED EXECUTION: {audit_result['reason']}")
                        self.reject_trade(trade_id, f"Auditor Block: {audit_result['reason']}")
                        return None
                    
                    self.logger.info(f"✅ Auditor Passed: {audit_result['reason']}")
                    
                    # 3. Execution (Real Order on Testnet)
                    approval_time = time.time()
                    self.logger.info(f"🚀 Placing Market Order for {trade['ticker']}...")
                    
                    order = self.exchange.create_order(trade['ticker'], trade['action'], trade['quantity'], order_type='market')
                    
                    if not order:
                        self.logger.error("❌ Order Placement Failed!")
                        return None
                        
                    # 4. Wait for Fill (Latency Simulation / Realism)
                    # We poll for a few seconds to get the fill price
                    filled_price = order.get('price') or current_price # Fallback
                    filled_qty = order.get('amount') or trade['quantity']
                    fee = 0.0 # CCXT fees logic varies
                    exec_status = order.get('status', 'unknown')
                    
                    # Polling loop for fill (max 10 seconds)
                    for _ in range(10):
                        if exec_status == 'closed':
                            break
                        time.sleep(1)
                        order_status = self.exchange.fetch_order_status(order['id'], trade['ticker'])
                        if order_status:
                             exec_status = order_status.get('status', 'unknown')
                             if exec_status == 'closed':
                                 filled_price = order_status.get('average') or order_status.get('price')
                                 filled_qty = order_status.get('filled')
                                 # Try to get fee cost
                                 if 'fee' in order_status and order_status['fee']:
                                     fee = order_status['fee'].get('cost', 0.0)
                                 break
                    
                    fill_time = time.time()
                    execution_latency = fill_time - approval_time
                    
                    intended_price = trade['intended_price']
                    realized_slippage = (filled_price - intended_price) / intended_price if intended_price else 0.0
                    
                    self.logger.info(f"Order Status: {exec_status}. Fill Price: {filled_price}")
                    
                    # Update fields
                    trade['status'] = 'OPEN' if exec_status == 'closed' else 'PLACED'
                    trade['approval_time'] = datetime.now().isoformat()
                    trade['entry_price'] = filled_price
                    trade['fees'] = fee
                    trade['execution_latency'] = execution_latency
                    trade['realized_slippage'] = realized_slippage
                    trade['order_id'] = order['id']
                    
                    # Save updated log
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)
                    
                    self.logger.info(f"✅ Trade {trade_id} APPROVED and executed: {trade['ticker']} {trade['action']} @ {trade['entry_price']:.2f}")
                    return trade
            
            self.logger.warning(f"Trade {trade_id} not found in pending trades")
            return None
        except Exception as e:
            self.logger.error(f"Error processing approved trade: {e}")
            return None
            
    def close_position(self, trade_id: str, reason: str = 'CLOSE_TP'):
        """
        Executes a closing order for an active trade (TP, SL, or manual).
        """
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
                
            for trade in trades:
                if trade['id'] == trade_id and trade.get('status') in ('OPEN', 'PLACED'):
                    self.logger.info(f"Closing position {trade_id} due to {reason}")

                    # Execute reversing order
                    close_action = "SELL" if trade['action'] == "BUY" else "BUY"
                    order = self.exchange.create_order(trade['ticker'], close_action, trade['quantity'], order_type='market')

                    if not order:
                        self.logger.warning(
                            f"Close order for {trade['ticker']} ({reason}) returned None — "
                            f"position likely still open on HL. NOT marking CLOSED."
                        )
                        _send_telegram(
                            f"CLOSE FAILED: {trade['ticker']}  [{reason}]\n"
                            f"Order returned None — position still open on HL.\n"
                            f"Manual intervention may be needed."
                        )
                        return False

                    trade['status'] = 'CLOSED'
                    trade['close_reason'] = reason
                    trade['exit_time'] = datetime.now().isoformat()

                    if order:
                        # Use average fill price; fall back to price field if average absent
                        exit_price = order.get('average') or order.get('price')
                        if exit_price:
                            trade['exit_price'] = float(exit_price)
                            entry_price = trade.get('entry_price') or 0.0
                            qty = trade.get('quantity') or 0.0
                            # Close-leg pnl (on remaining quantity only)
                            if trade['action'] == "BUY":
                                close_pnl = (float(exit_price) - float(entry_price)) * float(qty)
                            else:
                                close_pnl = (float(entry_price) - float(exit_price)) * float(qty)
                            # Realized partial-exit pnl (was previously lost from the total)
                            realized_partial_pnl = sum(
                                float(e.get('pnl') or 0)
                                for e in trade.get('partial_exits', [])
                            )
                            total_pnl = close_pnl + realized_partial_pnl
                            trade['close_pnl'] = round(close_pnl, 4)
                            trade['realized_partial_pnl'] = round(realized_partial_pnl, 4)
                            trade['pnl'] = round(total_pnl, 4)
                            # Percentage on ORIGINAL notional (entry × original qty),
                            # so pnl_percent reflects ROI of the whole position, not
                            # the leftover fragment after partials.
                            partial_qty = sum(
                                float(e.get('qty') or 0)
                                for e in trade.get('partial_exits', [])
                            )
                            original_qty = float(qty) + partial_qty
                            original_notional = float(entry_price) * original_qty
                            trade['pnl_percent'] = round(
                                (total_pnl / original_notional * 100) if original_notional > 0 else 0.0, 2
                            )
                            self.logger.info(
                                f"Position Closed. Total PnL: ${total_pnl:.2f} "
                                f"(close=${close_pnl:.2f} + partial=${realized_partial_pnl:.2f}, "
                                f"{trade['pnl_percent']:.2f}%)"
                            )

                            # Real costs from the HL ledgers (audit B6): the
                            # price-based pnl above ignores fees and funding,
                            # which silently flattered every historical stat.
                            # `fees` covers ALL legs since entry (entry +
                            # partials + this close), so it overwrites the
                            # entry-only value stored at open. pnl stays gross
                            # for backward compat; pnl_net is the real result.
                            try:
                                entry_ms = _entry_ts_ms(trade)
                                if entry_ms:
                                    time.sleep(2)  # let the close fill reach the fills ledger
                                    fees_usd, funding_usd = self.exchange.get_trade_costs(
                                        trade['ticker'], since_ms=entry_ms
                                    )
                                    if fees_usd is not None:
                                        trade['fees'] = round(fees_usd, 4)
                                    if funding_usd is not None:
                                        trade['funding_received'] = round(funding_usd, 4)
                                    if fees_usd is not None or funding_usd is not None:
                                        trade['pnl_net'] = round(
                                            total_pnl - (fees_usd or 0.0) + (funding_usd or 0.0), 4
                                        )
                            except Exception as cost_e:
                                self.logger.warning(f"Trade cost enrichment failed: {cost_e}")

                    try:
                        log_pipeline_event("TRADE_EXIT", trade['ticker'], {
                            "exit_reason": reason,
                            "pnl": round(trade.get('pnl', 0), 2),
                            "entry_price": trade.get('entry_price', 0),
                            "exit_price": trade.get('exit_price', 0),
                            "trade_id": trade_id,
                        })
                    except Exception:
                        pass

                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)

                    try:
                        pnl = trade.get('pnl', 0)
                        pnl_pct = trade.get('pnl_percent', 0)
                        entry_px = trade.get('entry_price', 0)
                        exit_px = trade.get('exit_price', 0)
                        pnl_sign = "+" if pnl >= 0 else ""
                        _send_telegram(
                            f"TRADE CLOSED: {trade['ticker']}  [{reason}]\n"
                            f"Entry: ${entry_px:.4f}  Exit: ${exit_px:.4f}\n"
                            f"PnL: {pnl_sign}${pnl:.2f} ({pnl_sign}{pnl_pct:.2f}%)"
                        )
                    except Exception:
                        pass

                    return True

            return False
        except Exception as e:
            self.logger.error(f"Failed to close position: {e}")
            return False
            
    def update_take_profit_stop_loss(self, trade_id: str, new_stop_loss: float):
        """
        Updates the Stop Loss level of an open trade (Trailing SL / Breakeven).
        """
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
                
            for trade in trades:
                if trade['id'] == trade_id and trade['status'] == 'OPEN':
                    old_sl = trade.get('stop_loss', 0.0)
                    trade['stop_loss'] = new_stop_loss
                    self.logger.info(f"Moved Stop Loss for {trade['ticker']} from {old_sl:.2f} to {new_stop_loss:.2f}")
                    
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)
                    
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to move stop loss: {e}")
            return False
    
    def reject_trade(self, trade_id: str, reason: str = "Founder rejection"):
        """
        Rejects a pending trade.
        """
        try:
            # Load trade log
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
            
            # Find and update the trade
            for trade in trades:
                if trade['id'] == trade_id and trade['status'] == 'PENDING_FOUNDER_APPROVAL':
                    trade['status'] = 'REJECTED'
                    trade['rejection_reason'] = reason
                    trade['rejection_time'] = datetime.now().isoformat()
                    
                    # Save updated log
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)
                    
                    self.logger.warning(f"❌ Trade {trade_id} REJECTED: {reason}")
                    return True
            
            return False
        except Exception as e:
            self.logger.error(f"Error rejecting trade: {e}")
            return False

    def _revalidate_thesis(self, ticker, trade_data, price_delta) -> tuple[bool, str]:
        """
        LLM Check: Is the original thesis still valid given market changes?
        """
        try:
            if not self.llm:
                 return True, "LLM Offline (Skipped)"
            
            prompt = f"""
            You are the Pre-Flight Auditor.
            A trade for {ticker} ({trade_data['action']}) was approved LATE (> 1 hour).
            
            MARKET CHANGE:
            Price Delta: {price_delta:+.2f}%
            
            ORIGINAL THESIS:
            {trade_data.get('synthesis_report', 'N/A')}
            
            TASK:
            Is this trade still valid? 
            - If price moved drastically against us: INVALID.
            - If price ran away (FOMO): INVALID.
            - If thesis was long-term: VALID.
            
            OUTPUT:
            Respond with 'VALID' or 'INVALID' followed by a short reason.
            """
            
            response = self.llm.analyze_text(prompt, agent_name="ExecutionAgent").strip()
            if "INVALID" in response.upper():
                return False, response
            return True, response
            
        except Exception as e:
            self.logger.error(f"Revalidation error: {e}")
            return True, "Error (Fail-Open)"

    def perform_pre_flight_check(self, trade_data: dict, current_price: float, l1_data: dict = None) -> dict:
        """
        AUDITOR: Performs 'Pre-Flight Check' using Hyperliquid L1 Data.
        
        Checks:
        1. Staleness: If > 1 hour, ask LLM.
        2. Slippage: If < 1 hour, check vs L1 Orderbook depth (Bid/Ask).
        """
        # 1. Staleness Check
        timestamp_str = trade_data.get('approval_time') or trade_data.get('entry_fmt')
        age = timedelta(0)
        
        if timestamp_str:
            try:
                ts = datetime.fromisoformat(timestamp_str)
                age = datetime.now() - ts
            except ValueError:
                self.logger.warning(f"Could not parse timestamp: {timestamp_str}")
        
        approved_price = trade_data.get('approved_at_price', trade_data.get('intended_price', 0.0))
        delta_pct = 0.0
        
        # Determine effective current price based on side (Audit against the book)
        audit_price = current_price
        if l1_data:
            if trade_data['action'] == 'BUY':
                audit_price = l1_data['ask'] # We buy at Ask
            else:
                audit_price = l1_data['bid'] # We sell at Bid
        
        if approved_price > 0:
            if trade_data['action'] == 'BUY':
                delta_pct = (audit_price - approved_price) / approved_price
            else:
                delta_pct = (approved_price - audit_price) / approved_price 
        
        # --- LATE APPROVAL (> 60 mins) ---
        if age > timedelta(minutes=60):
             self.logger.info(f"⏳ Late Approval ({int(age.total_seconds()/60)}m). Invoking LLM Auditor...")
             is_valid, reason = self._revalidate_thesis(trade_data['ticker'], trade_data, delta_pct*100)
             if not is_valid:
                 return {'passed': False, 'reason': f"LLM Rejection: {reason}"}
             return {'passed': True, 'reason': f"LLM Validated: {reason}"}

        # --- STANDARD CHECK (< 60 mins) ---
        # 5 Minute warning (optional logs) but we allow up to 60 mins with slippage check.
        
        max_slippage = trade_data.get('max_slippage_allowed', 0.005) # Default 0.5%
        
        # Check if slippage exceeds threshold (AND is negative for us)
        # delta_pct is positive if it moved against us.
        if delta_pct > max_slippage:
             return {'passed': False, 'reason': f"Excessive Slippage vs L1 Book ({delta_pct*100:.2f}% > {max_slippage*100:.2f}%)"}
                 
        return {'passed': True, 'reason': f"Auditor Passed (Vs L1 Book). Spread Impact: {delta_pct*100:.3f}%"}

    def execute_order(self, trade_proposal):
        """
        Executes an order based on the APPROVED proposal.
        Implements HITL workflow: trades above threshold require founder approval.
        """
        ticker = trade_proposal.get('ticker')
        # Hyperliquid only has USDC-margined perps — normalize USDT tickers
        if ticker and ticker.endswith('/USDT'):
            ticker = ticker.replace('/USDT', '/USDC')
            self.logger.info(f"Ticker normalized to USDC: {ticker}")

        # BUG-6 fix: In-flight lock prevents duplicate orders when log_trade fails
        with self._in_flight_lock:
            if ticker in self._in_flight:
                self.logger.warning(f"BLOCKED duplicate execution for {ticker} — order already in-flight")
                return None
            self._in_flight.add(ticker)

        try:
            return self._execute_order_inner(trade_proposal, ticker)
        finally:
            with self._in_flight_lock:
                self._in_flight.discard(ticker)

    # Correlated asset groups — only one position per group at a time
    CORRELATION_GROUPS = [
        {"XYZ-CL", "XYZ-BRENTOIL", "XYZ-WTIOIL"},   # Oil
        {"XYZ-GOLD", "XYZ-SILVER"},                    # Precious metals
    ]

    def _execute_order_inner(self, trade_proposal, ticker):
        """Inner execution logic — always called within in-flight guard."""
        action = trade_proposal.get('action')  # BUY/SELL
        intended_price = trade_proposal.get('price', 0.0)

        # Correlation guard: skip if we already hold a correlated asset
        base = ticker.split('/')[0]
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                open_trades = [t for t in json.load(f) if t.get('status') in ('OPEN', 'PLACED')]
            open_bases = {t.get('ticker', '').split('/')[0] for t in open_trades}
            for group in self.CORRELATION_GROUPS:
                if base in group:
                    overlap = open_bases & group - {base}
                    if overlap:
                        self.logger.warning(
                            f"BLOCKED {ticker}: correlated asset already open ({overlap.pop()}/USDC). "
                            f"Only one position per correlation group allowed."
                        )
                        return None
        except Exception:
            pass  # fail-open — don't block trades due to file read error

        # Spot order guard: only allow perpetual swaps, block spot markets
        # _normalize_symbol prefers perps (:USDC) over spot, so use it for the check
        try:
            norm_sym = self.exchange._normalize_symbol(ticker) if self.exchange else ticker
            markets = getattr(self.exchange, 'markets', None)
            if markets and norm_sym and norm_sym in markets:
                mkt_type = markets[norm_sym].get('type', '')
                if mkt_type != 'swap':
                    self.logger.warning(
                        f"BLOCKED {ticker}: market type is '{mkt_type}', not 'swap'. "
                        f"Only perpetual contracts are supported."
                    )
                    return None
        except Exception:
            pass  # fail-open

        # Derive position size in units from Kelly recommendation
        quantity = trade_proposal.get('size', 0.0)
        if quantity == 0:
            metrics = trade_proposal.get('metrics', {})
            # recommended_size from Kelly is in USD (kelly_fraction * bankroll)
            kelly = metrics.get('kelly', {})
            quantity_usd = kelly.get('recommended_size', 0.0)
            if quantity_usd > 0 and intended_price > 0:
                quantity = quantity_usd / intended_price
                # Round down to market's amount precision step
                try:
                    precision = self.exchange.get_amount_precision(ticker)
                    if precision and precision > 0:
                        quantity = math.floor(quantity / precision) * precision
                except Exception:
                    pass

        if quantity <= 0:
            self.logger.error(
                f"Position size is 0 for {ticker} (price=${intended_price:.4f}). "
                f"Check account balance and Kelly calculation. Trade aborted."
            )
            return None

        # Meaningful minimum: skip positions below $50 — they generate near-zero PnL
        # after fees. Applies to high-unit-price assets (e.g. PAXG ~$5k) where Kelly
        # recommends tiny qty that rounds to $10-20 notional.
        MIN_MEANINGFUL_NOTIONAL = 50.0
        if intended_price > 0 and quantity * intended_price < MIN_MEANINGFUL_NOTIONAL:
            self.logger.warning(
                f"Skipping {ticker}: notional ${quantity * intended_price:.2f} below "
                f"${MIN_MEANINGFUL_NOTIONAL:.0f} minimum — Kelly allocation too small for "
                f"this asset's unit price (${intended_price:.2f})"
            )
            return None

        # Enforce minimum notional ($10 on Hyperliquid)
        try:
            min_notional = self.exchange.get_min_notional(ticker)
            if intended_price > 0 and quantity * intended_price < min_notional:
                precision = self.exchange.get_amount_precision(ticker) or 0.000001
                min_units = math.ceil(min_notional / intended_price / max(precision, 0.000001)) * max(precision, 0.000001)
                min_units_value = min_units * intended_price
                # Safety: if rounding up to min notional would exceed 3x the Kelly-recommended
                # size, the asset's unit size is too large for our budget — skip it.
                kelly_usd = trade_proposal.get('metrics', {}).get('kelly', {}).get('recommended_size', 0)
                cap = max(kelly_usd * 3, min_notional * 1.5) if kelly_usd > 0 else min_notional * 1.5
                if min_units_value > cap:
                    self.logger.warning(
                        f"Min notional bump for {ticker} would create ${min_units_value:.2f} position "
                        f"(cap=${cap:.2f}). Asset unit too large for budget — trade skipped."
                    )
                    return None
                self.logger.warning(
                    f"Order notional ${quantity * intended_price:.2f} below min ${min_notional}. "
                    f"Adjusting quantity from {quantity} to {min_units} (${min_units_value:.2f})."
                )
                quantity = min_units
        except Exception:
            pass

        # Calculate trade value
        trade_value = quantity * intended_price
        
        # Check if approval is required
        requires_approval = trade_value > APPROVAL_THRESHOLD
        
        self.logger.info(f"Executing PAPER trade for {ticker}: {action} {quantity} units (Value: ${trade_value:.2f})")
        
        if requires_approval:
            self.logger.warning(f"⚠️ Trade value ${trade_value:.2f} exceeds threshold ${APPROVAL_THRESHOLD}. Requiring Founder approval.")
        
        # Capture Snapshot Config for Auditor
        max_slippage = trade_proposal.get('max_slippage_allowed', 0.005)

        # Calculate Exit Strategy Levels (ATR-based when available)
        rrr = trade_proposal.get('net_odds', 2.0)
        stop_loss_pct = trade_proposal.get('stop_loss_pct', 5.0)
        atr_pct = trade_proposal.get('metrics', {}).get('atr_pct', 0.0)

        take_profit, stop_loss = 0.0, 0.0
        if hasattr(self, 'strategy_manager') and self.strategy_manager:
            try:
                _tf = trade_proposal.get('timeframe')
                _swing = trade_proposal.get('swing_levels') or {}
                levels = self.strategy_manager.calculate_levels(
                    intended_price, action, float(rrr), float(stop_loss_pct),
                    atr_pct=float(atr_pct), timeframe=_tf, swing_levels=_swing
                )
                take_profit = levels.get('take_profit', 0.0)
                stop_loss = levels.get('stop_loss', 0.0)
                stop_loss_pct = levels.get('sl_pct', stop_loss_pct)
            except Exception as e:
                self.logger.error(f"Failed to calculate levels: {e}")

        # ── Shadow mode intercept ────────────────────────────────────────
        # When shadow_mode is active, record a paper trade instead of executing.
        # The calling code sees a returned record just like a real trade.
        try:
            from utils.auto_params import AutoParams
            if AutoParams().is_shadow_mode():
                return self._log_shadow_trade(
                    ticker, action, quantity, intended_price,
                    take_profit, stop_loss, trade_proposal
                )
        except Exception as _se:
            self.logger.warning(f"Shadow mode check failed (fail-open): {_se}")
        # ─────────────────────────────────────────────────────────────────

        # Logic Fork:
        # If Approval Required -> DO NOT EXECUTE YET. Log as PENDING.
        # If No Approval -> Execute Immediately.

        if requires_approval:
             # Create PENDING record (No mock execution yet)
             trade_record = {
                "id": f"trade_{int(time.time()*1000)}",
                "status": "PENDING_FOUNDER_APPROVAL",
                "ticker": ticker,
                "action": action,
                "quantity": quantity,
                "entry_price": 0.0, # Not filled yet
                "intended_price": intended_price,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "approved_at_price": intended_price, # Snapshot
                "max_slippage_allowed": max_slippage,
                "entry_time": time.time(),
                "entry_fmt": datetime.now().isoformat(),
                "fees": 0.0,
                "trade_value": trade_value,
                "analyst_signals": trade_proposal.get("analyst_signals", {}),
                "conviction": trade_proposal.get('conviction', 0),
                "synthesis_report": trade_proposal.get('synthesis_report', '')
            }
             self.log_trade(trade_record)
             self.update_pending_approvals(trade_record)

             try:
                 log_pipeline_event("EXECUTION", ticker, {
                     "action": action,
                     "trade_value": round(trade_value, 2),
                     "status": "PENDING",
                     "trade_id": trade_record["id"],
                 })
             except Exception:
                 pass

             return trade_record

        # DIRECT EXECUTION (Small Trade)
        # Using CCXT to place real order on Testnet
        self.logger.info(f"🚀 Direct Execution (No Approval Needed) for {ticker}...")
        
        start_time = time.time()
        current_price_check = self.exchange.get_market_price(ticker)
        
        # Place Market Order
        order = self.exchange.create_order(ticker, action, quantity, order_type='market')
        
        if not order:
            if not self.exchange.signing_client:
                self.logger.error(f"Direct Execution Failed for {ticker}: signing client unavailable (wallet not registered?)")
            else:
                # exchange_client already logged the specific reason (e.g. insufficient margin) as warning
                self.logger.warning(f"Direct Execution Skipped for {ticker}: order not placed (see exchange log above)")
            return None

        # Wait for Fill — order.get('price') is the slippage-tolerance limit, NOT the
        # actual fill.  Only trust 'average' (the real fill) or fall back to the mid-price
        # we captured just before placing.
        filled_price = order.get('average') or current_price_check
        filled_qty = order.get('filled') or order.get('amount') or quantity
        fee = 0.0
        exec_status = order.get('status', 'unknown')

        for _ in range(10):
            if exec_status == 'closed':
                 break
            time.sleep(1)
            order_status = self.exchange.fetch_order_status(order['id'], ticker)
            if order_status:
                    exec_status = order_status.get('status', 'unknown')
                    if exec_status == 'closed':
                        filled_price = order_status.get('average') or filled_price
                        filled_qty = order_status.get('filled') or filled_qty
                        if 'fee' in order_status and order_status['fee']:
                            fee = order_status['fee'].get('cost', 0.0)
                        break

        fill_time = time.time()
        execution_latency = fill_time - start_time
        realized_slippage = (filled_price - intended_price) / intended_price if intended_price else 0.0
        
        # Fetch Funding (Cost of Carry)
        funding_rate = self.exchange.get_funding_rate(ticker)
        
        # Construct Log Record
        trade_record = {
            "id": f"trade_{int(time.time()*1000)}",
            "status": "OPEN" if exec_status == 'closed' else "PLACED",
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "entry_price": filled_price,
            "intended_price": intended_price,
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "sl_pct": levels.get('sl_pct', stop_loss_pct) if hasattr(self, 'strategy_manager') and self.strategy_manager else stop_loss_pct,
            "sl_stage": 0,
            "partial_tp1_taken": False,
            "peak_price": filled_price,
            "partial_exits": [],
            "entry_time": start_time,
            "entry_fmt": datetime.now().isoformat(),
            "fees": fee,
            "funding_rate": funding_rate,
            "approved_at_price": intended_price,
            "max_slippage_allowed": max_slippage,
            "slippage_pct": realized_slippage,
            "execution_latency": execution_latency,
            "realized_slippage": realized_slippage,
            "trade_value": trade_value,
            "exit_time": None,
            "pnl": 0.0,
            "pnl_percent": 0.0,
            "timeframe": trade_proposal.get('timeframe', '1h'),
            "analyst_signals": trade_proposal.get("analyst_signals", {}),
            "conviction": trade_proposal.get('conviction', 0),
            "synthesis_report": trade_proposal.get('synthesis_report', ''),
            "order_id": order['id']
        }
        
        try:
            self.log_trade(trade_record)
        except Exception as log_err:
            # Trade IS live on Hyperliquid. Log failure must not silently drop it.
            # The reconciliation in main.py will recover it on the next cycle.
            self.logger.critical(
                f"GHOST TRADE RISK: {ticker} executed on HL but trade_log write failed: {log_err}. "
                f"Reconciliation will recover it next cycle."
            )
            # Still return the record so add_active_asset() gets called by the caller
            return trade_record

        try:
            direction = "Long" if action == "BUY" else "Short"
            tp_line = f"TP: ${trade_record.get('take_profit', 0):.4f}" if trade_record.get('take_profit') else "TP: —"
            sl_line = f"SL: ${trade_record.get('stop_loss', 0):.4f}" if trade_record.get('stop_loss') else "SL: —"
            conviction = trade_record.get('conviction', 0)
            _send_telegram(
                f"TRADE OPENED: {ticker} ({direction})\n"
                f"Entry: ${filled_price:.4f}  Size: {quantity}\n"
                f"{tp_line}  {sl_line}\n"
                f"Value: ${trade_value:.2f}  Conviction: {conviction:.0%}\n"
                f"Timeframe: {trade_record.get('timeframe', '?')}"
            )
        except Exception:
            pass

        try:
            log_pipeline_event("EXECUTION", ticker, {
                "action": action,
                "trade_value": round(trade_value, 2),
                "status": trade_record.get("status", "OPEN"),
                "trade_id": trade_record["id"],
                "entry_price": filled_price,
                "slippage_pct": round(realized_slippage * 100, 3),
            })
        except Exception:
            pass

        return trade_record


    def update_trade_field(self, trade_id: str, fields: dict) -> bool:
        """
        Generic field updater for an open trade record.
        """
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
            for trade in trades:
                if trade['id'] == trade_id and trade.get('status') in ('OPEN', 'PLACED'):
                    trade.update(fields)
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to update trade fields: {e}")
            return False

    def close_partial_position(self, trade_id: str, close_fraction: float, reason: str) -> bool:
        """
        Closes a fraction of an open position (partial take-profit).
        """
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                trades = json.load(f)
            for trade in trades:
                if trade['id'] == trade_id and trade.get('status') in ('OPEN', 'PLACED'):
                    close_qty = trade['quantity'] * close_fraction
                    current_price = self.exchange.get_market_price(trade['ticker'])
                    # Enforce minimum notional ($10) — HL rejects smaller orders.
                    # When partial is infeasible, lock in the downside via SL→breakeven
                    # instead. Functionally equivalent to partial TP (eliminate risk,
                    # keep upside) without actually placing an order.
                    if close_qty * (current_price or 0) < 10.0:
                        entry_price = trade.get('entry_price', 0.0)
                        FEE_BUFFER = 0.001  # 0.1%
                        is_long = trade.get('action') == 'BUY'
                        be_sl = entry_price * (1 + FEE_BUFFER) if is_long else entry_price * (1 - FEE_BUFFER)
                        old_sl = trade.get('stop_loss', 0.0)
                        # Only move SL in favorable direction
                        if (is_long and be_sl > old_sl) or (not is_long and (old_sl == 0 or be_sl < old_sl)):
                            trade['stop_loss'] = be_sl
                            trade['sl_stage'] = max(trade.get('sl_stage', 0), 1)
                        trade['partial_tp1_taken'] = True
                        skipped = trade.get('skipped_partials', [])
                        skipped.append({
                            'fraction': close_fraction,
                            'reason': reason,
                            'skip_reason': 'below_min_notional',
                            'intended_qty': close_qty,
                            'intended_notional': close_qty * (current_price or 0),
                            'fallback': 'sl_to_breakeven',
                            'new_sl': trade['stop_loss'],
                            'time': datetime.now().isoformat(),
                        })
                        trade['skipped_partials'] = skipped
                        with open(TRADE_LOG_FILE, "w") as f:
                            json.dump(trades, f, indent=4)
                        self.logger.warning(
                            f"Partial close skipped for {trade['ticker']}: notional "
                            f"${close_qty*(current_price or 0):.2f} < $10 min. "
                            f"SL→breakeven @{be_sl:.4f} (was {old_sl:.4f})."
                        )
                        return False
                    # Round to exchange precision
                    try:
                        precision = self.exchange.get_amount_precision(trade['ticker'])
                        if precision and precision > 0:
                            close_qty = math.floor(close_qty / precision) * precision
                    except Exception:
                        pass
                    close_action = "SELL" if trade['action'] == "BUY" else "BUY"
                    order = self.exchange.create_order(trade['ticker'], close_action, close_qty, order_type='market')
                    exit_price = 0.0
                    partial_pnl = 0.0
                    if order:
                        exit_price = float(order.get('average') or order.get('price') or current_price or 0)
                        entry_price = trade.get('entry_price', 0.0)
                        if trade['action'] == 'BUY':
                            partial_pnl = (exit_price - entry_price) * close_qty
                        else:
                            partial_pnl = (entry_price - exit_price) * close_qty
                    # Update trade record
                    trade['quantity'] = trade['quantity'] - close_qty
                    trade['partial_tp1_taken'] = True
                    partial_exits = trade.get('partial_exits', [])
                    partial_exits.append({
                        'fraction': close_fraction, 'qty': close_qty,
                        'exit_price': exit_price, 'pnl': partial_pnl,
                        'reason': reason, 'time': datetime.now().isoformat()
                    })
                    trade['partial_exits'] = partial_exits
                    with open(TRADE_LOG_FILE, "w") as f:
                        json.dump(trades, f, indent=4)
                    self.logger.info(f"Partial close {trade['ticker']}: {close_qty} units @ {exit_price:.4f}, PnL=${partial_pnl:.2f}")
                    return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to close partial position: {e}")
            return False

    def _log_shadow_trade(self, ticker: str, action: str, quantity: float,
                          intended_price: float, take_profit: float,
                          stop_loss: float, trade_proposal: dict) -> dict:
        """Record a paper trade during shadow mode instead of executing on HL."""
        try:
            fill_price = self.exchange.get_market_price(ticker) or intended_price
            record = {
                "id":             f"shadow_{int(time.time()*1000)}",
                "status":         "SHADOW_OPEN",
                "source":         "SHADOW",
                "ticker":         ticker,
                "action":         action,
                "quantity":       quantity,
                "entry_price":    fill_price,
                "intended_price": intended_price,
                "take_profit":    take_profit,
                "stop_loss":      stop_loss,
                "entry_time":     time.time(),
                "entry_fmt":      datetime.now().isoformat(),
                "pnl":            0.0,
                "pnl_percent":    0.0,
                "exit_price":     None,
                "exit_time":      None,
                "analyst_signals": trade_proposal.get("analyst_signals", {}),
                "conviction":     trade_proposal.get("conviction", 0),
                "synthesis_report": trade_proposal.get("synthesis_report", ""),
                "fees":           0.0,
            }
            from utils.shadow_comparator import ShadowComparator
            ShadowComparator().record_shadow_trade(record)
            self.logger.info(
                f"[SHADOW] Paper trade: {ticker} {action} {quantity} @ {fill_price:.4f} "
                f"(shadow mode active — no real order placed)"
            )
            return record
        except Exception as e:
            self.logger.error(f"Shadow trade logging failed: {e}")
            return None

    def get_balance(self):
        """
        Returns the current portfolio balance (USDC).
        """
        return self.exchange.get_balance()


    def check_supabase_approvals(self):
        """
        Periodically checks Supabase for trades that have been APPROVED by the Founder.
        Also handles AUTO-EXPIRATION if no response within 24 hours.
        """
        if not self.db.is_available():
            return
            
        try:
            # 1. Get local pending IDs
            pending_approvals = []
            if os.path.exists(self.dashboard_file):
                with open(self.dashboard_file, "r") as f:
                    dashboard_data = json.load(f)
                    pending_approvals = dashboard_data.get('pending_approvals', [])
            
            if not pending_approvals:
                return

            # 2. Check each pending trade, track which ones are resolved
            resolved_ids = set()
            for trade_info in pending_approvals:
                trade_id = trade_info['trade_id']
                trade_ts_str = trade_info.get('timestamp')

                # --- A. Check for Auto-Expiration ---
                if trade_ts_str:
                    try:
                        trade_ts = datetime.fromisoformat(trade_ts_str)
                        if datetime.now() - trade_ts > timedelta(hours=24):
                            self.logger.warning(f"⏰ Trade {trade_id} EXPIRED (Timeout > 24 hours). Auto-Rejecting.")
                            self.reject_trade(trade_id, "Auto-Expired: No Founder Response")
                            resolved_ids.add(trade_id)
                            continue # Skip to next trade
                    except ValueError:
                        self.logger.warning(f"Could not parse timestamp for {trade_id}: {trade_ts_str}")

                # --- B. Check Supabase for Status Update ---
                if self.db.client:
                    # check if supabase has a different status
                    # Supabase 'id' column is a bigint, but local trade_id is 'trade_123456789'
                    # Extract the numeric part to avoid 'invalid input syntax for type bigint'
                    try:
                        numeric_id = int(trade_id.replace('trade_', ''))
                    except ValueError:
                        self.logger.error(f"Cannot convert trade_id {trade_id} to numeric ID for Supabase.")
                        continue

                    res = self.db.client.table("trades").select("status").eq("id", numeric_id).execute()

                    if res.data:
                        status = res.data[0]['status']
                        if status == 'APPROVED':
                            self.logger.info(f"✅ Found APPROVED status in Supabase for {trade_id}")
                            self.process_approved_trade(trade_id)
                            resolved_ids.add(trade_id)
                        elif status == 'REJECTED':
                             self.reject_trade(trade_id, "Rejected via Supabase")
                             resolved_ids.add(trade_id)

            # 3. Remove resolved trades from pending_approvals and persist
            if resolved_ids:
                dashboard_data['pending_approvals'] = [
                    t for t in pending_approvals if t['trade_id'] not in resolved_ids
                ]
                try:
                    with open(self.dashboard_file, "w") as f:
                        json.dump(dashboard_data, f, indent=2, default=str)
                    self.logger.info(f"Cleaned {len(resolved_ids)} resolved trades from pending_approvals")
                except Exception as write_err:
                    self.logger.error(f"Failed to update pending_approvals: {write_err}")
                            
        except Exception as e:
            self.logger.error(f"Error checking Supabase approvals: {e}")
