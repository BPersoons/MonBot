import time
import json
import logging
import os
import sys
import math

# Force UTF-8 for Windows Console to prevent logging errors
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from datetime import datetime
import asyncio
from utils.reporting import report_status
from utils.swarm_health import SwarmHealthManager
from agents.swarm_monitor import SwarmMonitor
from utils.pipeline_events import log_event as log_pipeline_event, get_previous_state

# Initialize Stdout Capture EARLY for Supabase Metadata & Logging Capture
try:
    from utils.stdout_capture import start_capture, get_logs
    start_capture()
    # Note: Logger not set up yet, so we print to confirm safely
    # print("📡 Stdout Capture Active - Metadata Bridge Enabled") 
except Exception as e:
    print(f"⚠️ Failed to init Stdout Capture: {e}")


# Configuration
SLEEP_INTERVAL = 60  # 1 minute between cycles
DASHBOARD_FILE = "dashboard.json"

# 3-Tier Scanning Intervals (now adaptive via TickerStateTracker)
# These are kept as fallback defaults
FAST_SCAN_INTERVAL = 300     # 5 min — re-analyze active/candidate tickers (short TFs)
RESEARCH_INTERVAL = 1800     # 30 min — Scout scans for new candidates (overridden by adaptive logic)
DEEP_SCAN_INTERVAL = 14400   # 4 hours — full deep analysis (all TFs settle)

# Setup Logging (with optional Cloud Logging integration for GCP)
def setup_logging():
    """Configure logging. Cloud Logging is optional and won't block startup."""
    # Always set up basic logging first
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("heartbeat.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Optionally try to add Cloud Logging (non-blocking)
    try:
        # Only attempt if explicitly on GCP and client is available
        if os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT"):
            import google.cloud.logging
            client = google.cloud.logging.Client()
            # Use a less aggressive setup that doesn't replace root handlers
            handler = client.get_default_handler()
            logging.getLogger().addHandler(handler)
            logging.info("☁️ Cloud Logging handler added (optional)")
    except Exception as e:
        # Never crash on cloud logging issues - just continue with local logging
        logging.warning(f"Cloud Logging unavailable (continuing with local): {e}")

setup_logging()
logger = logging.getLogger("Heartbeat")



def sanitize(obj):
    """
    Recursively replace NaN and Infinity with 0.0 or None to make data JSON-safe.
    """
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj): return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj

def load_dashboard_data():
    if not os.path.exists(DASHBOARD_FILE):
        return {"status": "ACTIVE", "market_data": {}}
    try:
        with open(DASHBOARD_FILE, "r") as f:
            data = json.load(f)
            if "market_data" not in data:
                # Migrate old format if exists, or init empty
                return {"status": data.get("status", "ACTIVE"), "market_data": {}}
            return data
    except Exception as e:
        logger.error(f"Error reading dashboard file: {e}")
        return {"status": "ACTIVE", "market_data": {}}

def save_dashboard_data(data):
    try:
        with open(DASHBOARD_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error writing to dashboard file: {e}")

def check_system_status():
    """Checks if system is PAUSED via dashboard.json"""
    try:
        data = load_dashboard_data()
        status = data.get("status", "ACTIVE")
        if status == "PAUSED":
            logger.info("System is PAUSED. Sleeping...")
            return False
        return True
    except Exception as e:
        logger.error(f"Error checking system status: {e}")
        return True # Fail open safely



def main():
    logger.info("🚀 Initializing Autonomous Heartbeat (Multi-Asset)...")
    logger.info("ℹ️ VERSION: RECOVERY V1")
    logger.info("=" * 60)
    
    # ===========================================
    # PHASE 0: Environment & Secret Validation
    # ===========================================
    logger.info("📋 Phase 0: Validating environment and secrets...")
    
    try:
        from utils.gcp_secrets import get_all_trading_secrets
        secrets = get_all_trading_secrets()
        
        missing_secrets = [k for k, v in secrets.items() if not v]
        loaded_secrets = [k for k, v in secrets.items() if v]
        
        if loaded_secrets:
            logger.info(f"✅ Secrets loaded: {', '.join(loaded_secrets)}")
        
        if missing_secrets:
            logger.warning(f"⚠️ Missing secrets (may cause failures): {', '.join(missing_secrets)}")
        
        # Critical secrets that MUST exist
        critical_secrets = ["GOOGLE_API_KEY", "HL_WALLET_ADDRESS", "HL_PRIVATE_KEY"]
        critical_missing = [s for s in critical_secrets if s in missing_secrets]
        
        if critical_missing:
            logger.critical(f"❌ CRITICAL SECRETS MISSING: {', '.join(critical_missing)}")
            logger.critical("   → Check GCP Secret Manager or .env.adk file")
            logger.critical("   → Ensure Service Account has 'Secret Manager Secret Accessor' role")
            # Don't return yet - let agent init fail with specific errors
    except Exception as e:
        logger.warning(f"⚠️ Secret validation skipped (non-fatal): {e}")
    
    # ===========================================
    # PHASE 1: Agent Initialization (Individual)
    # ===========================================
    logger.info("=" * 60)
    logger.info("📋 Phase 1: Initializing Agents...")
    
    try:
        from utils.db_client import DatabaseClient
        global_db_client = DatabaseClient()
        logger.info("   [OK] Global DatabaseClient initialized for metadata caching")
    except Exception as e:
        logger.error(f"Failed to initialize global DatabaseClient: {e}")
        global_db_client = None
    
    project_lead = None
    auditor = None
    cpo = None
    
    # --- ProjectLead (Scout) ---
    try:
        logger.info("   → Initializing ProjectLead (Scout)...")
        from agents.project_lead import ProjectLead
        project_lead = ProjectLead(db_client=global_db_client)
        logger.info("   ✅ ProjectLead initialized successfully")
    except Exception as e:
        logger.critical(f"   ❌ ProjectLead FAILED: {e}", exc_info=True)
        logger.critical("      → This agent depends on: TechnicalAnalyst, FundamentalAnalyst, SentimentAnalyst, ExecutionAgent")
        logger.critical("      → Check: Exchange API keys, LLM API key, database connectivity")
        return
    
    # --- PerformanceAuditor ---
    try:
        logger.info("   → Initializing PerformanceAuditor...")
        from utils.auditor import PerformanceAuditor
        auditor = PerformanceAuditor()
        logger.info("   ✅ PerformanceAuditor initialized successfully")
    except Exception as e:
        logger.critical(f"   ❌ PerformanceAuditor FAILED: {e}", exc_info=True)
        return
    
    # --- ProductOwner (CPO) ---
    try:
        logger.info("   → Initializing ProductOwner (CPO)...")
        from agents.product_owner import ProductOwner
        cpo = ProductOwner()
        logger.info("   ✅ ProductOwner (CPO) initialized successfully")
    except Exception as e:
        logger.error(f"   ⚠️ ProductOwner FAILED (non-critical): {e}")
        cpo = None  # CPO is optional, continue without it

    # --- SwarmLearner ---
    swarm_learner = None
    try:
        logger.info("   → Initializing SwarmLearner...")
        from agents.swarm_learner import SwarmLearner
        swarm_learner = SwarmLearner(
            exchange_client=project_lead.execution_agent.exchange if project_lead and hasattr(project_lead, 'execution_agent') else None,
            db_client=global_db_client,
        )
        logger.info("   ✅ SwarmLearner initialized successfully")
    except Exception as e:
        logger.error(f"   ⚠️ SwarmLearner FAILED (non-critical): {e}")
        swarm_learner = None
    
    logger.info("=" * 60)
    logger.info("🎉 All critical agents initialized successfully!")
    logger.info("=" * 60)

    # ===========================================
    # PHASE 1.5: Initialize Swarm Health Manager
    # ===========================================
    health_manager = None
    try:
        health_manager = SwarmHealthManager(global_db_client)
        health_manager.report_health("ProjectLead", "ACTIVE", 0)
        health_manager.report_health("PerformanceAuditor", "ACTIVE", 0)
        health_manager.report_health("ProductOwner", "ACTIVE" if cpo else "ERROR", 0, 
                                     last_error="Initialization failed" if not cpo else None)
        health_manager.report_health("Heartbeat", "STARTING", 0)
        logger.info("   ✅ SwarmHealthManager initialized and agents reported")
    except Exception as e:
        logger.warning(f"⚠️ SwarmHealthManager unavailable: {e}")

    # ===========================================
    # PHASE 1.55: Start SwarmMonitor (Watchdog)
    # ===========================================
    swarm_monitor = None
    try:
        swarm_monitor = SwarmMonitor(db_client=global_db_client)
        swarm_monitor.start()
        logger.info("   ✅ SwarmMonitor watchdog started (checks every 5 min)")
    except Exception as e:
        logger.warning(f"⚠️ SwarmMonitor failed to start (non-critical): {e}")

    # ===========================================
    # PHASE 1.6: Start Dashboard Server
    # ===========================================
    try:
        from utils.dashboard_server import start_dashboard_server
        start_dashboard_server(global_db_client, port=8080)
        logger.info("   ✅ Dashboard server started on port 8080")
    except Exception as e:
        logger.warning(f"⚠️ Dashboard server failed to start (non-critical): {e}")

    # ===========================================
    # PHASE 2: Initialize Runtime State
    # ===========================================
    consecutive_risk_blocks = 0
    consecutive_failures = 0  # Track for emergency alerts
    previous_cycle_results = {}
    last_research_run = 0
    last_deep_scan = 0
    system_status = "ACTIVE"
    
    # Initialize Opportunity Manager
    from utils.opportunity_manager import OpportunityManager
    opportunity_manager = OpportunityManager()
    
    # Initialize Ticker State Tracker (Tiered Scanning)
    from utils.ticker_state import TickerStateTracker
    ticker_state = TickerStateTracker()
    ticker_state.cleanup_stale(max_age_hours=24)  # Clean up old entries on startup
    
    # Main Loop
    cycle_count = 0
    
    while True:
        cycle_count += 1
        cycle_start = time.time()
        logger.info(f"\n--- Starting Trading Cycle #{cycle_count} ---")
        
        # REPORT START OF CYCLE (Immediate Feedback)
        if health_manager:
            latest_logs = get_logs()
            health_manager.report_health(
                "Heartbeat", 
                "ACTIVE", 
                cycle_count, 
                "Cycle In Progress",
                metadata={
                    "stdout_tail": latest_logs,
                    "current_task": f"Pipeline cycle #{cycle_count} starting",
                    "type": "uptime_tick"
                }
            )

        # 0a. SwarmLearner: Decision pipeline diagnostics (Every 60 cycles, ~1 hour)
        if cycle_count % 60 == 0 and swarm_learner is not None:
            logger.info("🔬 SwarmLearner: Running decision pipeline analysis...")
            try:
                swarm_learner.run_learning_cycle()
            except Exception as e:
                logger.error(f"⚠️ SwarmLearner failed: {e}")

        # 0. CPO System Improvement Cycle (Every 10 cycles)
        if cycle_count % 10 == 0 and cpo is not None:
            logger.info("👨‍💼 CPO is analyzing system logs for improvements & heartbeat...")
            if health_manager:
                health_manager.report_health("ProductOwner", "ACTIVE", cycle_count, metadata={
                    "current_task": "Analyzing system logs for improvements",
                    "last_activity": f"CPO analysis triggered at cycle {cycle_count}"
                })
            try:
                # Pass execution_agent for health check balance fetch
                cpo.run_analysis_cycle(execution_agent=project_lead.execution_agent)
                if health_manager:
                    health_manager.report_health("ProductOwner", "IDLE", cycle_count, metadata={
                        "current_task": "Analysis complete",
                        "last_activity": f"Completed system improvement analysis at cycle {cycle_count}"
                    })
            except Exception as e:
                logger.error(f"⚠️ CPO Analysis failed: {e}")
                if health_manager:
                    health_manager.report_health("ProductOwner", "ERROR", cycle_count, last_error=str(e)[:200], metadata={
                        "current_task": "Analysis failed",
                        "last_activity": f"CPO analysis crashed: {str(e)[:100]}"
                    })
        
        # 1. System Status Check
        if not check_system_status():
            time.sleep(60)
            continue
        
        try:
            # ... (Rest of loop logic remains same until next ticker loop) ...
            
            # Temporary state for this run
            current_market_state = {}
            current_dashboard = load_dashboard_data() 
            market_data_update = current_dashboard.get("market_data", {})
            
            # Fetch monitored setups early for Scout Watchlist Sync
            monitored_setups = opportunity_manager.get_monitoring_setups()
            monitored_tickers = [s["ticker"] for s in monitored_setups]
            
            # 2. Run Research Cycle (Periodically)
            current_time = time.time()
            discovery_data = current_dashboard.get("discovery_pipeline", {})
            
            if current_time - last_research_run > ticker_state.get_adaptive_scout_interval(len(project_lead.get_active_assets())):
                 logger.info("   → Triggering Scout (Research Cycle)...")
                 research_start = time.time()
                 # REASONING INJECTION: Scout manages its own health/status via ResearchAgent class
                 # if health_manager:
                 #     health_manager.report_health("Scout", "ACTIVE", cycle_count, metadata={ ... })
                 research_results = project_lead.run_research_cycle(
                     cycle_count=cycle_count, 
                     monitored_tickers=monitored_tickers
                 )
                 research_duration = round(time.time() - research_start, 1)
                 last_research_run = current_time
                 
                 num_proposals = len(research_results.get('proposals', []))
                 proposal_tickers = [p.get('ticker', '?') for p in research_results.get('proposals', [])[:5]]
                 
                 # Format for Dashboard
                 discovery_data = {
                     "last_run": datetime.now().isoformat(),
                     "proposals": research_results.get('proposals', [])
                 }
                 
                 # HANDSHAKE CHECK: Explicitly log findings
                 logger.info(f"LOG: Scout found {num_proposals} opportunities")
                 
                 # Scout updates its own status to IDLE with scan results in ResearchAgent.scan_market
                 # We do NOT overwrite it here.
                 pass
            
            # 3. Assessment Cycle
            
            # Scout-provided candidates (dynamic, based on backtest quality or news)
            candidates = []
            for p in discovery_data.get('proposals', []):
                t = p.get('ticker')
                tf = p.get('timeframe', '1h')
                if t:
                    setup_id = f"{t}_{tf}"
                    candidates.append({"setup_id": setup_id, "ticker": t, "timeframe": tf})
                    if setup_id not in current_market_state:
                        current_market_state[setup_id] = {}
                    current_market_state[setup_id]['catalyst_reason'] = p.get('catalyst_reason', 'TA_BACKTEST')
                    current_market_state[setup_id]['timeframe'] = tf
                    current_market_state[setup_id]['strategy'] = p.get('strategy', 'Unknown')
                    current_market_state[setup_id]['direction'] = p.get('direction', 'LONG')
            
            # Open positions we're actively trading (must keep monitoring)
            open_positions = project_lead.get_active_assets()
            open_setups = [{"setup_id": f"{t}_1h", "ticker": t, "timeframe": "1h"} for t in open_positions]
            
            # Tickers waiting for micro entry setup (fetched earlier)
            
            # Combine unique setups: Open Positions -> Monitored -> Scout Candidates
            active_setups = []
            seen = set()
            for s in open_setups + monitored_setups + candidates:
                sid = s["setup_id"]
                if sid not in seen:
                    active_setups.append(s)
                    seen.add(sid)

            logger.info(f"   → Analyzing {len(active_setups)} setups (Positions: {len(open_setups)}, Scout: {len(candidates)})")
            
            cycle_decisions = []
            # Pre-populate table to prevent it from disappearing
            for s in active_setups:
                sid = s["setup_id"]
                cycle_decisions.append({
                    "setup_id": sid,
                    "ticker": s["ticker"],
                    "timeframe": s["timeframe"],
                    "score": 0.0,
                    "decision": "PENDING",
                    "reason": "Waiting in queue...",
                    "breakdown": {"tech":0, "fund":0, "sent":0},
                    "next_step": "PENDING",
                    "bull_case": "...",
                    "bear_case": "...",
                    "time": datetime.now().strftime("%H:%M:%S")
                })
            
            # --- OPTIMIZATION: Load trade log once per cycle ---
            active_trades_cache = []
            if os.path.exists("trade_log.json"):
                try:
                    import json
                    with open("trade_log.json", "r") as f:
                        all_trades = json.load(f)
                        active_trades_cache = [t for t in all_trades if t.get('status') == 'OPEN']
                except Exception as e:
                    logger.error(f"Failed to load trade_log.json: {e}")
            # ---------------------------------------------------

            # ===========================================
            # PHASE 3.5: Active Position Management (TP/SL)
            # Run BEFORE ticker analysis so every cycle checks exits,
            # even when the analysis loop takes many minutes.
            # ===========================================
            if active_trades_cache and hasattr(project_lead, 'execution_agent') and hasattr(project_lead.execution_agent, 'strategy_manager') and project_lead.execution_agent.strategy_manager:
                logger.info(f"   → Running Strategy Manager ({len(active_trades_cache)} open positions)...")
                positions_status = {}
                try:
                    hl_exchange = project_lead.execution_agent.exchange

                    # ── Sync entry prices & quantities from Hyperliquid each cycle ──
                    # This keeps trade_log in sync with reality so TP/SL and P&L are accurate.
                    try:
                        vault_addr = getattr(hl_exchange, 'vault_address', None) or hl_exchange.wallet_address
                        hl_positions_raw = hl_exchange.signing_client.fetch_positions(params={'user': vault_addr})
                        hl_pos_map = {}  # base_symbol -> {entry_price, contracts}
                        for p in hl_positions_raw:
                            if float(p.get('contracts') or 0) == 0:
                                continue
                            base = (p.get('symbol') or '').split('/')[0]
                            hl_pos_map[base] = {
                                'entry_price': float(p.get('entryPrice') or p.get('info', {}).get('entryPx') or 0),
                                'contracts':   float(p.get('contracts') or 0),
                            }
                        logger.info(f"   → Synced {len(hl_pos_map)} live HL positions for entry price/qty accuracy")
                    except Exception as _sync_err:
                        hl_pos_map = {}
                        logger.warning(f"   → Could not fetch HL positions for sync: {_sync_err}")

                    # Apply sync to trade_log in-memory and on disk
                    if hl_pos_map:
                        try:
                            with open("trade_log.json") as _tlf:
                                all_trades = json.load(_tlf)
                            changed = False

                            # ── Pass 1: Sync known trades (entry price / quantity) ──
                            for _t in all_trades:
                                if _t.get('status') not in ('OPEN', 'PLACED'):
                                    continue
                                _base = (_t.get('ticker') or '').split('/')[0].upper()
                                if _base in hl_pos_map:
                                    _hl = hl_pos_map[_base]
                                    if _hl['entry_price'] and abs(_t.get('entry_price', 0) - _hl['entry_price']) > 0.0001:
                                        _t['entry_price'] = _hl['entry_price']
                                        changed = True
                                    if _hl['contracts'] and abs(_t.get('quantity', 0) - abs(_hl['contracts'])) > 0.00001:
                                        _t['quantity'] = abs(_hl['contracts'])
                                        changed = True

                            # ── Pass 2: Detect ghost trades (live on HL, missing from trade_log) ──
                            open_bases = {
                                (_t.get('ticker') or '').split('/')[0].upper()
                                for _t in all_trades
                                if _t.get('status') in ('OPEN', 'PLACED')
                            }
                            for _base, _hl in hl_pos_map.items():
                                if _base.upper() not in open_bases:
                                    _contracts = _hl['contracts']
                                    _action = 'BUY' if _contracts > 0 else 'SELL'
                                    _ticker = f"{_base}/USDC"
                                    _entry = _hl['entry_price']
                                    _qty = abs(_contracts)
                                    logger.warning(
                                        f"[RECONCILE] Ghost position detected: {_ticker} {_action} "
                                        f"qty={_qty} entry={_entry} — live on HL but missing from trade_log. Recovering..."
                                    )
                                    # Calculate TP/SL from entry using system defaults (5% SL, 2:1 RRR)
                                    _tp, _sl = 0.0, 0.0
                                    try:
                                        _sm = project_lead.execution_agent.strategy_manager
                                        if _sm and _entry > 0:
                                            _lvl = _sm.calculate_levels(_entry, _action, 2.0, 5.0)
                                            _tp = _lvl.get('take_profit', 0.0)
                                            _sl = _lvl.get('stop_loss', 0.0)
                                    except Exception:
                                        pass
                                    _recovery = {
                                        'id': f"RECOVERED_{_base}_{int(time.time())}",
                                        'ticker': _ticker,
                                        'action': _action,
                                        'quantity': _qty,
                                        'entry_price': _entry,
                                        'intended_price': _entry,
                                        'take_profit': _tp,
                                        'stop_loss': _sl,
                                        'status': 'OPEN',
                                        'source': 'RECONCILED',
                                        'entry_fmt': datetime.now().isoformat(),
                                        'entry_time': time.time(),
                                        'fees': 0.0,
                                        'pnl': 0.0,
                                        'pnl_percent': 0.0,
                                        'timeframe': '?',
                                        'conviction': 0.0,
                                        'synthesis_report': 'Recovered from Hyperliquid position reconciliation',
                                    }
                                    all_trades.append(_recovery)
                                    changed = True
                                    project_lead.add_active_asset(_ticker)
                                    try:
                                        report_status(
                                            f"⚠️ RECONCILE: Ghost position {_ticker} recovered from Hyperliquid. "
                                            f"Trade was live but missing from trade_log.", "WARNING"
                                        )
                                    except Exception:
                                        pass

                            if changed:
                                with open("trade_log.json", "w") as _tlf:
                                    json.dump(all_trades, _tlf, indent=2)
                                # Refresh cache so this cycle uses correct values
                                active_trades_cache = [_t for _t in all_trades if _t.get('status') in ('OPEN', 'PLACED')]
                        except Exception as _apply_err:
                            logger.warning(f"   → Could not apply HL sync to trade_log: {_apply_err}")

                    for trade in active_trades_cache:
                        trade_ticker = trade.get('ticker')
                        if not trade_ticker:
                            continue
                        try:
                            current_price = hl_exchange.get_market_price(trade_ticker) or None
                        except Exception:
                            current_price = None

                        if current_price:
                            qty = trade.get('quantity', 0)
                            entry = trade.get('entry_price', current_price)
                            if trade.get('action', 'BUY').upper() == 'BUY':
                                unrealized = (current_price - entry) * qty
                            else:
                                unrealized = (entry - current_price) * qty
                            pnl_pct = ((current_price - entry) / entry * 100) if entry else 0
                            positions_status[trade_ticker] = {
                                'current_price': current_price,
                                'unrealized_pnl': round(unrealized, 4),
                                'pnl_pct': round(pnl_pct, 2),
                                'entry_price': entry,
                                'take_profit': trade.get('take_profit', 0),
                                'stop_loss': trade.get('stop_loss', 0),
                                'quantity': qty,
                                'action': trade.get('action', 'BUY'),
                            }

                            result = project_lead.execution_agent.strategy_manager.evaluate_position(trade, current_price)
                            ev_action = result.get('action', 'HOLD')
                            ev_reason = result.get('reason')
                            new_peak   = result.get('peak_price')

                            # Persist peak_price when it changes
                            if new_peak and new_peak != trade.get('peak_price'):
                                project_lead.execution_agent.update_trade_field(trade['id'], {'peak_price': new_peak})

                            if ev_action == 'CLOSE_FULL':
                                icon = '🎯' if ev_reason == 'TAKE_PROFIT' else '🛑'
                                logger.info(f"{icon} {ev_reason} for {trade_ticker} at {current_price}")
                                project_lead.execution_agent.close_position(trade['id'], reason=ev_reason)
                                project_lead.remove_active_asset(trade_ticker)

                            elif ev_action == 'CLOSE_PARTIAL':
                                logger.info(f"💰 PARTIAL_TP for {trade_ticker}: closing {result['close_fraction']*100:.0f}% @ {current_price}")
                                project_lead.execution_agent.close_partial_position(trade['id'], result['close_fraction'], ev_reason)

                            elif ev_action == 'UPDATE_SL':
                                logger.info(f"🔒 SL {ev_reason} for {trade_ticker}: {result['new_sl']:.4f} (stage {result['sl_stage']})")
                                project_lead.execution_agent.update_take_profit_stop_loss(trade['id'], result['new_sl'])
                                project_lead.execution_agent.update_trade_field(trade['id'], {
                                    'sl_stage': result['sl_stage'],
                                    'peak_price': new_peak
                                })

                    try:
                        with open("positions_status.json", "w") as _f:
                            json.dump(positions_status, _f, indent=2)
                    except Exception:
                        pass

                    # Record daily unrealized P&L snapshot
                    try:
                        total_unrealized = round(sum(ps.get('unrealized_pnl', 0) for ps in positions_status.values()), 2)
                        today_str = datetime.now().strftime('%Y-%m-%d')
                        snap_file = 'pnl_snapshots.json'
                        try:
                            with open(snap_file) as _sf:
                                snapshots = json.load(_sf)
                        except Exception:
                            snapshots = []
                        if snapshots and snapshots[-1].get('date') == today_str:
                            snapshots[-1]['unrealized_pnl'] = total_unrealized
                        else:
                            snapshots.append({'date': today_str, 'unrealized_pnl': total_unrealized})
                        snapshots = snapshots[-90:]
                        with open(snap_file, 'w') as _sf:
                            json.dump(snapshots, _sf)
                    except Exception as _snap_err:
                        logger.debug(f"PnL snapshot failed: {_snap_err}")
                except Exception as e:
                    logger.error(f"Error in active trade management: {e}")

            for setup_idx, setup in enumerate(active_setups):
                setup_id = setup["setup_id"]
                ticker = setup["ticker"]
                timeframe = setup["timeframe"]
                
                # --- USDT DEDUP: Skip USDT if USDC variant exists ---
                if "USDT" in ticker:
                    usdc_variant = setup_id.replace("USDT", "USDC")
                    if usdc_variant in seen:
                        logger.info(f"⏭️ Skipping {setup_id} — USDC variant ({usdc_variant}) already in pipeline")
                        continue
                    else:
                        logger.info(f"📌 Using {setup_id} (USDT fallback — no USDC variant available)")
                
                # --- TIERED SCANNING: Check if ticker is in cooldown ---
                if not ticker_state.should_analyze(setup_id):
                    ts = ticker_state.get_status(setup_id)
                    logger.info(f"⏭️ Skipping {setup_id} — in cooldown ({ts['last_decision']}, next check {ts['next_check']})")
                    # Update cycle_decisions with cooldown status
                    if setup_idx < len(cycle_decisions):
                        cycle_decisions[setup_idx].update({
                            "decision": ts['last_decision'],
                            "score": ts.get('last_score', 0.0),
                            "reason": f"Cooldown ({ts['next_check']})",
                            "next_step": "COOLDOWN",
                            "time": datetime.now().strftime("%H:%M:%S")
                        })
                    continue
                
                logger.info(f"--- Processing {setup_id} ---")
                
                if health_manager:
                    health_manager.report_health("ProjectLead", "ACTIVE", cycle_count, metadata={
                        "current_task": f"Analyzing {setup_id} ({setup_idx+1}/{len(active_setups)})",
                        "last_activity": f"Processing setup {setup_id} with analyst council",
                        "tickers_total": len(active_setups),
                        "ticker_current": ticker,
                        "latest_decisions": cycle_decisions # Keep history visible
                    })
                
                try:
                    # Project Lead orchestrates analysts
                    ticker_start = time.time()
                    
                    context_for_setup = {ticker: current_market_state.get(setup_id, {})}
                    if not context_for_setup[ticker]:
                        context_for_setup[ticker] = {'timeframe': timeframe}
                        
                    result = project_lead.process_opportunity(ticker, market_context=context_for_setup, cycle_count=cycle_count)
                    ticker_duration = round(time.time() - ticker_start, 1)
                    
                    # Store Score
                    score = result.get("combined_score", 0)
                    decision = result.get("status", "UKNOWN")
                    reason = result.get("decision_reason", "No reason provided")
                    breakdown = result.get("score_breakdown", {"tech":0, "fund":0, "sent":0})
                    
                    # Extract full Council JSON
                    bull_case = result.get("bull_case", "N/A")
                    bear_case = result.get("bear_case", "N/A")
                    next_step = result.get("next_step", decision)
                    target_entry_price = result.get("target_entry_price", 0.0)
                    current_price = result.get("current_price", 0.0)
                    stop_loss_pct = result.get("stop_loss_pct", 5.0)
                    rrr = result.get("rrr", "1:1.5")
                    direction = result.get("direction", "LONG")
                    
                    # Add to decision log
                    # Update decision log (in-place)
    
                    # Update decision log (in-place or append)
                    try:
                        logger.info(f"DEBUG: Updating cycle_decisions[{setup_idx}] for {setup_id} with score {score}")
                        new_decision_entry = {
                            "setup_id": setup_id,
                            "ticker": ticker,
                            "timeframe": timeframe,
                            "score": sanitize(score),
                            "decision": decision,
                            "reason": reason,
                            "breakdown": sanitize(breakdown),
                            "next_step": next_step,
                            "bull_case": bull_case[:100] + "..." if len(bull_case) > 100 else bull_case,
                            "bear_case": bear_case[:100] + "..." if len(bear_case) > 100 else bear_case,
                            "time": datetime.now().strftime("%H:%M:%S")
                        }
                        
                        if setup_idx < len(cycle_decisions):
                            cycle_decisions[setup_idx] = new_decision_entry
                        else:
                            # Fallback if list length mismatch (shouldn't happen with pre-fill)
                            cycle_decisions.append(new_decision_entry)
                            
                        # --- 12-Hour ROLLING DASHBOARD HISTORY LOG ---
                        history_file = "decision_history.json"
                        history_entry = {
                            "timestamp": datetime.now().isoformat(),
                            "ticker": ticker,
                            "decision": next_step,
                            "score": round(score, 2),
                            "reason": reason,
                            "bull_case": new_decision_entry["bull_case"],
                            "bear_case": new_decision_entry["bear_case"],
                            "direction": direction,
                            "target_entry_price": target_entry_price,
                            "current_price": current_price,
                            "stop_loss_pct": stop_loss_pct,
                            "rrr": rrr
                        }
                        
                        try:
                            history_data = []
                            if os.path.exists(history_file):
                                with open(history_file, "r") as f:
                                    try:
                                        history_data = json.load(f)
                                    except json.JSONDecodeError:
                                        history_data = []
                            
                            history_data.append(history_entry)
                            
                            # Prune strictly to last 2000 events to prevent memory bloat 
                            # (Approx 12 hours of dense market scanning)
                            if len(history_data) > 2000:
                                history_data = history_data[-2000:]
                                
                            with open(history_file, "w") as f:
                                json.dump(history_data, f, indent=2)
                        except Exception as history_e:
                            logger.error(f"Failed to append to decision_history.json: {history_e}")
                        # ---------------------------------------------
                            
                    except Exception as e:
                        logger.error(f"Failed to update cycle_decisions for {setup_id}: {e}")
                        
                    # Check for Critical Errors (Brain Crash)
                    if result.get("status") == "ERROR":
                        logger.error(f"Skipping {ticker} due to agent failure.")
                        continue
                        
                    # ----------------------------------------------------
                    # 4. Filter & Route to Execution
                    # ----------------------------------------------------
                    
                    if 'analysis' in result:
                        current_market_state[ticker] = {
                            "combined_score": score
                        }
                    
                    # Update Dashboard Data
                    market_data_update[ticker] = {
                        "last_updated": datetime.now().isoformat(),
                        "analysis": result.get('analysis'),
                        "status": result.get('status'),
                        "risk_status": result.get('risk_status'),
                        "payload_sent": result.get('payload_sent')
                    }
                    
                    if health_manager:
                        health_manager.report_health("ProjectLead", "ACTIVE", cycle_count, metadata={
                            "current_task": f"Completed {ticker} analysis",
                            "last_activity": f"{ticker}: {decision} ({score:.2f}) - {reason}",
                            "ticker_duration_s": ticker_duration,
                            "last_score": score,
                            "latest_decisions": cycle_decisions # Update with new decision
                        })
                    
                    # DYNAMIC PORTFOLIO UPDATE
                    # If we bought or sold (short opened), add to active assets AND remove from monitoring
                    if result.get("status") in ["BUY", "SELL"]:
                        project_lead.add_active_asset(ticker)
                        opportunity_manager.remove(ticker, reason=f"Trade Executed ({decision})")
                    # If we need to monitor, add/update it in the Opportunity Manager
                    elif result.get("status") == "MONITOR":
                        opportunity_manager.add_or_update(
                            ticker=ticker,
                            timeframe=timeframe,
                            score=score,
                            details=result.get("analysis", {}),
                            next_step=result.get("next_step", "PENDING"),
                            reason=reason,
                            target_entry_price=target_entry_price,
                            direction=direction,
                            current_price=current_price,
                            monitoring_rationale=result.get("monitoring_rationale", ""),
                            rrr=rrr,
                            stop_loss_pct=stop_loss_pct
                        )
                    # If it explicitly failed macro, remove it
                    elif result.get("status") in ["NO_GO", "ERROR"]:
                        opportunity_manager.remove(setup_id, reason=f"Discarded by ProjectLead: {reason}")
                    
                    # --- PIPELINE EVENT: Record state transition ---
                    try:
                        from_state = get_previous_state(ticker)
                        log_pipeline_event("DECISION", ticker, {
                            "from_state": from_state,
                            "to_state": next_step,
                            "score": round(score, 3),
                            "reason": reason[:200],
                            "direction": direction,
                            "status": decision,
                        })
                    except Exception as pe:
                        logger.error(f"Pipeline event logging failed: {pe}")

                    # --- TIERED SCANNING: Record analysis result for cooldown ---
                    ticker_state.record_analysis(
                        ticker=setup_id,
                        decision=next_step,
                        score=score,
                        extra_meta={
                            "direction": direction,
                            "bull_case": bull_case[:50] if bull_case else "",
                            "duration_s": ticker_duration
                        }
                    )

                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}", exc_info=True)
                    # Report specific error to dashboard health
                    if health_manager:
                         health_manager.report_health("ProjectLead", "ERROR", cycle_count, f"Crash on {ticker}: {str(e)[:100]}", metadata={
                             "current_task": f"FAILED on {ticker}",
                             "last_activity": f"Error analyzing {ticker}: {str(e)[:100]}"
                         })
                    continue
                
                time.sleep(2)
                
            # 3.5 Governance Audit
            if health_manager:
                health_manager.report_health("PerformanceAuditor", "ACTIVE", cycle_count, metadata={
                    "current_task": "Running governance audit",
                    "last_activity": f"Audit cycle triggered at pipeline cycle {cycle_count}"
                })
            auditor.run_audit_cycle()
            if health_manager:
                health_manager.report_health("PerformanceAuditor", "IDLE", cycle_count, metadata={
                    "current_task": "Audit complete",
                    "last_activity": f"Governance audit completed for cycle {cycle_count}"
                })
            
            # Check for External Approvals
            if hasattr(project_lead, 'execution_agent'):
                 project_lead.execution_agent.check_supabase_approvals()
                 
            # (Active trade management moved to Phase 3.5, before ticker loop)
            # ===========================================
            # PHASE 7: Dashboard Update
            # ===========================================
            
            # Process & Review Open Opportunities
            open_opportunities = opportunity_manager.review_opportunities()

            cycle_duration = round(time.time() - cycle_start, 1)

            current_dashboard["status"] = "ACTIVE"
            current_dashboard["last_update"] = datetime.now().isoformat()
            current_dashboard["market_data"] = market_data_update
            current_dashboard["discovery_pipeline"] = discovery_data
            current_dashboard["cycle_time_sec"] = cycle_duration
            current_dashboard["cycle_count"] = cycle_count
            current_dashboard["open_opportunities"] = open_opportunities

            # LLM token usage stats for cost monitoring
            try:
                from utils.llm_client import get_llm_usage_stats
                current_dashboard["llm_stats"] = get_llm_usage_stats()
            except Exception as _llm_err:
                logger.debug(f"LLM stats update failed (non-critical): {_llm_err}")

            save_dashboard_data(current_dashboard)
            
            # Report end of cycle to Swarm Health
            logger.info(f"Cycle #{cycle_count} completed in {cycle_duration}s. Dashboard updated.")
            
            # 5.5 Report cycle health (The "Pulse" Enforcement - ALL Agents)
            if health_manager:
                latest_logs = get_logs()
                tickers_processed = len(active_setups) if 'active_setups' in dir() else 0
                
                # Pulse Heartbeat (with uptime context)
                health_manager.report_health("Heartbeat", "ACTIVE", cycle_count, metadata={
                    "stdout_tail": latest_logs,
                    "current_task": f"Pipeline cycle #{cycle_count} complete",
                    "last_activity": f"Cycle took {cycle_duration}s, processed {tickers_processed} tickers",
                    "cycle_duration_s": cycle_duration,
                    "tickers_processed": tickers_processed,
                    "type": "uptime_tick"
                })
                
                # Pulse ProjectLead
                health_manager.report_health("ProjectLead", "IDLE" if system_status == "ACTIVE" else "PAUSED", cycle_count, metadata={
                    "current_task": "Waiting for next cycle",
                    "last_activity": f"Processed {tickers_processed} tickers in {cycle_duration}s",
                    "cycle_duration_s": cycle_duration,
                    "latest_decisions": cycle_decisions # PERSIST TABLE DURING SLEEP
                })
                
                # REMOVED: Redundant pulses that wipe metadata (Scout, Auditor, CPO)
                # They manage their own state or stay in last known state.
                
                logger.info(f"💓 System Pulse Sent (Cycle {cycle_count})")
                consecutive_failures = 0  # Reset on success
            
            # 5. Sleep
            logger.info(f"Sleeping for {SLEEP_INTERVAL} seconds...")
            time.sleep(SLEEP_INTERVAL)

        except KeyboardInterrupt:
            logger.info("Heartbeat stopped by user.")
            if health_manager:
                health_manager.report_health("Heartbeat", "IDLE", cycle_count, "User stopped")
            break
        except Exception as e:
            consecutive_failures += 1
            error_msg = str(e)
            
            # Report error to health dashboard
            if health_manager:
                health_manager.report_health("Heartbeat", "ERROR", cycle_count, error_msg[:200])
            
            # Emergency alert after 3+ consecutive failures
            if consecutive_failures >= 3:
                logger.critical(f"🚨 EMERGENCY: {consecutive_failures} consecutive failures! Last error: {error_msg[:200]}")
            
            # Robust error handling for Rate Limits or API outages
            if "429" in error_msg or "Rate limit" in error_msg or "Connection" in error_msg:
                 logger.warning(f"⚠️ API Error (Rate Limit/Connection): {e}. Retrying in 60s...")
                 time.sleep(60)
            else:
                 logger.error(f"Unexpected error in heartbeat cycle: {e}", exc_info=True)
                 time.sleep(60) # Wait 60s for stability before retry

if __name__ == "__main__":
    main()
