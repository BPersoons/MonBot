"""
stocks_main.py — Heartbeat loop for the Stocks Department.

Phase 1: Research-only (no IBKR execution). Runs locally with:
  python stocks_main.py

Cadence:
  - Once daily at 13:00–13:15 UTC (14:00 CET): full universe screening
  - Every 60 min during market hours (13:30–20:00 UTC weekdays): re-score watchlist
  - Every 10 min: poll Telegram for approval responses
  - Every Sunday 16:00 UTC (18:00 CET): RSI audit
  - Outside market hours: sleep 5 minutes
"""

import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone

# Windows UTF-8 fix
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("stocks_heartbeat.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("StocksHeartbeat")

# ─────────────────────────────────────────────────────────────────────────────
# Timing constants
# ─────────────────────────────────────────────────────────────────────────────

SLEEP_WHEN_CLOSED = 5 * 60       # 5 min outside market hours
SLEEP_DURING_HOURS = 60          # 1 min polling interval during market hours
TELEGRAM_POLL_INTERVAL = 10 * 60 # 10 min
HOURLY_RESCORE_INTERVAL = 60 * 60
WEEKLY_AUDIT_HOUR_UTC = 16       # 16:00 UTC = 18:00 CET (Sunday)

STOCKS_DASHBOARD_FILE = "stocks_dashboard.json"


def sanitize(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj


def save_dashboard(data: dict):
    try:
        with open(STOCKS_DASHBOARD_FILE, "w") as f:
            json.dump(sanitize(data), f, indent=2)
    except Exception as e:
        logger.error(f"Could not save stocks dashboard: {e}")


def main():
    logger.info("=" * 60)
    logger.info("STOCKS DEPARTMENT — Phase 1 (Research Only)")
    logger.info("=" * 60)

    # ─────────────────────────────────────────────────────────────────
    # Phase 0: Load secrets
    # ─────────────────────────────────────────────────────────────────
    logger.info("Phase 0: Loading secrets...")
    try:
        from utils.gcp_secrets import get_secret
        google_api_key = get_secret("GOOGLE_API_KEY")
        fmp_api_key = get_secret("FMP_API_KEY")
        if google_api_key and not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = google_api_key
        if fmp_api_key and not os.environ.get("FMP_API_KEY"):
            os.environ["FMP_API_KEY"] = fmp_api_key
        logger.info("  Secrets loaded (GCP or .env.adk)")
    except Exception as e:
        logger.warning(f"  Secret loading failed (non-fatal, may work from env): {e}")

    # ─────────────────────────────────────────────────────────────────
    # Phase 1: Initialize clients and agents
    # ─────────────────────────────────────────────────────────────────
    logger.info("Phase 1: Initializing agents...")

    # AutoParams (stocks-specific: reads config/stocks_auto_params.json)
    try:
        from stocks.utils.stocks_auto_params import StocksAutoParams
        auto_params = StocksAutoParams()
        logger.info("  StocksAutoParams (stocks_auto_params.json) initialized")
    except Exception as e:
        logger.warning(f"  StocksAutoParams failed: {e} — using defaults")
        auto_params = None

    # LLM Client
    llm = None
    try:
        from utils.llm_client import LLMClient
        llm = LLMClient()
        if llm.available:
            logger.info(f"  LLMClient initialized ({llm.model_name})")
        else:
            logger.warning("  LLMClient unavailable — moat/sentiment scoring will use defaults")
    except Exception as e:
        logger.warning(f"  LLMClient failed: {e}")

    # YFinance Client
    try:
        from stocks.utils.yfinance_client import YFinanceClient
        yf_client = YFinanceClient()
        logger.info("  YFinanceClient initialized")
    except Exception as e:
        logger.critical(f"  YFinanceClient FAILED: {e}")
        return

    # FMP Client
    fmp_client = None
    try:
        from stocks.utils.fmp_client import FMPClient
        fmp_client = FMPClient()
        remaining = fmp_client.get_daily_calls_remaining()
        logger.info(f"  FMPClient initialized ({remaining} calls remaining today)")
    except Exception as e:
        logger.warning(f"  FMPClient failed: {e} — scoring will use yfinance only")

    # StocksProjectLead
    try:
        from stocks.agents.stocks_project_lead import StocksProjectLead
        project_lead = StocksProjectLead(
            fmp_client=fmp_client,
            yf_client=yf_client,
            llm_client=llm,
            auto_params=auto_params,
        )
        logger.info("  StocksProjectLead initialized")
    except Exception as e:
        logger.critical(f"  StocksProjectLead FAILED: {e}", exc_info=True)
        return

    # StocksAuditor
    auditor = None
    try:
        from stocks.agents.stocks_auditor import StocksAuditor
        auditor = StocksAuditor(auto_params=auto_params)
        logger.info("  StocksAuditor initialized")
    except Exception as e:
        logger.warning(f"  StocksAuditor failed (non-critical): {e}")

    logger.info("=" * 60)
    logger.info("All agents initialized. Starting heartbeat loop.")
    logger.info("=" * 60)

    # ─────────────────────────────────────────────────────────────────
    # Phase 2: Heartbeat loop
    # ─────────────────────────────────────────────────────────────────
    from stocks.utils.market_calendar import (
        is_market_open, is_daily_screening_time, is_sunday
    )
    from stocks.utils.telegram_approval import poll_approvals

    last_screening_date = None     # date of last full daily screening
    last_hourly_rescore = 0.0      # timestamp of last hourly re-score
    last_telegram_poll = 0.0       # timestamp of last Telegram poll
    last_weekly_audit_date = None  # date of last weekly audit
    cycle_count = 0

    dashboard = {
        "status": "ACTIVE",
        "phase": "1 — Research Only",
        "last_screening": None,
        "last_hourly_check": None,
        "last_audit": None,
        "cycle_count": 0,
        "fmp_calls_today": 0,
        "watchlist_count": 0,
        "pending_approvals": 0,
    }

    while True:
        cycle_count += 1
        now_utc = datetime.now(timezone.utc)
        now_str = now_utc.strftime("%Y-%m-%d %H:%M UTC")

        try:
            market_open = is_market_open(now_utc.replace(tzinfo=None))
            today = now_utc.date()

            # ── Telegram poll (every 10 min, always) ──────────────────
            if time.time() - last_telegram_poll >= TELEGRAM_POLL_INTERVAL:
                try:
                    approvals = poll_approvals()
                    if approvals:
                        logger.info(f"Telegram: received {len(approvals)} approval(s)")
                        project_lead.process_approvals(approvals)
                    last_telegram_poll = time.time()
                except Exception as e:
                    logger.error(f"Telegram poll failed: {e}")

            # ── Proposal expiry check (always) ────────────────────────
            try:
                project_lead.expire_stale_proposals()
            except Exception as e:
                logger.debug(f"Proposal expiry check failed: {e}")

            # ── Weekly RSI audit (Sunday 16:00 UTC) ───────────────────
            if (is_sunday() and now_utc.hour == WEEKLY_AUDIT_HOUR_UTC
                    and last_weekly_audit_date != today and auditor):
                logger.info("=== Running Weekly RSI Audit ===")
                try:
                    audit_result = auditor.run_weekly_audit()
                    last_weekly_audit_date = today
                    dashboard["last_audit"] = now_str
                    logger.info(f"Audit complete: {audit_result.get('actions', [])}")
                except Exception as e:
                    logger.error(f"Weekly audit failed: {e}", exc_info=True)

            if not market_open:
                logger.debug(f"Market closed ({now_str}) — sleeping {SLEEP_WHEN_CLOSED}s")
                dashboard["status"] = "MARKET_CLOSED"
                save_dashboard(dashboard)
                time.sleep(SLEEP_WHEN_CLOSED)
                continue

            dashboard["status"] = "ACTIVE"

            # ── Daily full screening (once per day, at 13:00–13:15 UTC) ─
            if is_daily_screening_time(now_utc.replace(tzinfo=None)) and last_screening_date != today:
                logger.info(f"=== Triggering Daily Full Screening ({now_str}) ===")
                try:
                    result = project_lead.run_daily_screening()
                    last_screening_date = today
                    dashboard["last_screening"] = now_str
                    dashboard["fmp_calls_today"] = fmp_client.get_daily_calls_used() if fmp_client else 0
                    logger.info(
                        f"Screening done: {result.get('analyzed',0)} analyzed, "
                        f"{result.get('proposals',0)} proposals, "
                        f"{result.get('triggered',0)} sent to Telegram"
                    )
                except Exception as e:
                    logger.error(f"Daily screening failed: {e}", exc_info=True)

            # ── Hourly watchlist re-score ──────────────────────────────
            elif time.time() - last_hourly_rescore >= HOURLY_RESCORE_INTERVAL:
                logger.info(f"=== Hourly Watchlist Re-score ({now_str}) ===")
                try:
                    result = project_lead.run_hourly_check()
                    last_hourly_rescore = time.time()
                    dashboard["last_hourly_check"] = now_str
                    logger.info(f"Hourly check done: {result.get('checked',0)} checked, "
                                f"{result.get('triggered',0)} proposed")
                except Exception as e:
                    logger.error(f"Hourly re-score failed: {e}", exc_info=True)

            # ── Dashboard update ───────────────────────────────────────
            try:
                from stocks.utils.stocks_opportunity_manager import StocksOpportunityManager
                om = StocksOpportunityManager()
                watchlist = om.get_all()
                pending = om.get_by_status("PROPOSED")
                dashboard["watchlist_count"] = len(watchlist)
                dashboard["pending_approvals"] = len(pending)
                dashboard["cycle_count"] = cycle_count
                dashboard["fmp_calls_today"] = fmp_client.get_daily_calls_used() if fmp_client else 0
            except Exception:
                pass
            save_dashboard(dashboard)

            logger.info(
                f"[Cycle {cycle_count}] {now_str} | "
                f"Watchlist: {dashboard['watchlist_count']} | "
                f"Pending: {dashboard['pending_approvals']} | "
                f"FMP: {dashboard['fmp_calls_today']} calls"
            )
            time.sleep(SLEEP_DURING_HOURS)

        except KeyboardInterrupt:
            logger.info("Stocks heartbeat stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in stocks heartbeat: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
