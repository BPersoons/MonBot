"""
telegram_approval.py — Telegram proposal delivery and approval polling for stocks.

Flow:
  1. send_proposal(ticker, payload) — sends formatted message with reply instructions
  2. poll_approvals()              — calls getUpdates, parses BUY/SKIP/WATCHLIST replies
  3. Returns list of {ticker, action} dicts for the caller to process

Requires env vars (loaded from GCP Secret Manager or .env.adk):
  TELEGRAM_BOT_TOKEN   — bot HTTP API token
  TELEGRAM_CHAT_ID     — target chat/channel ID

All messages are prefixed [STOCKS] to distinguish from [CRYPTO] alerts.
"""

import json
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("TelegramApproval")

_UPDATE_OFFSET_FILE = "stocks_telegram_offset.json"


def _load_bot_config() -> tuple[Optional[str], Optional[str]]:
    """Return (bot_token, chat_id) from env / .env.adk / GCP secrets."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        try:
            from dotenv import load_dotenv
            load_dotenv(".env.adk")
            token = token or os.getenv("TELEGRAM_BOT_TOKEN")
            chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        except Exception:
            pass

    if not token or not chat_id:
        try:
            from utils.gcp_secrets import get_secret
            token = token or get_secret("TELEGRAM_BOT_TOKEN")
            chat_id = chat_id or get_secret("TELEGRAM_CHAT_ID")
        except Exception:
            pass

    return token, chat_id


def _load_offset() -> int:
    try:
        with open(_UPDATE_OFFSET_FILE) as f:
            return json.load(f).get("offset", 0)
    except Exception:
        return 0


def _save_offset(offset: int):
    try:
        with open(_UPDATE_OFFSET_FILE, "w") as f:
            json.dump({"offset": offset}, f)
    except Exception as e:
        logger.warning(f"Could not save Telegram offset: {e}")


def send_message(text: str) -> bool:
    """Send a raw text message. Returns True on success."""
    token, chat_id = _load_bot_config()
    if not token or not chat_id:
        logger.warning("Telegram config missing — cannot send message")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text,
                                     "parse_mode": "HTML"}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.warning(f"Telegram sendMessage failed: {e}")
        return False


def send_proposal(ticker: str, payload: dict) -> bool:
    """
    Send a structured BUY proposal to Telegram and record it in pending_approvals.

    payload keys (all optional with defaults):
        final_score, growth_score, multiple_score, management_score,
        moat_score, sentiment_score,
        revenue_cagr_pct, pe_vs_avg_pct, founder_ceo, insider_pct,
        insider_net_shares_90d, moat_summary,
        shares, price, total_cost_usd, portfolio_pct, stop_price, stop_pct
    """
    score = payload.get("final_score", 0.0)
    growth = payload.get("growth_score", 0.0)
    multiple = payload.get("multiple_score", 0.0)
    mgmt = payload.get("management_score", 0.0)
    moat = payload.get("moat_score", 0.0)
    sent = payload.get("sentiment_score", 0.0)

    rev_cagr = payload.get("revenue_cagr_pct", "N/A")
    pe_vs = payload.get("pe_vs_avg_pct", "N/A")
    founder = "Yes" if payload.get("founder_ceo") else "No"
    ins_pct = payload.get("insider_pct", "N/A")
    ins_net = payload.get("insider_net_shares_90d", "N/A")
    moat_sum = payload.get("moat_summary", "N/A")

    shares = payload.get("shares", "?")
    price = payload.get("price", 0.0)
    total = payload.get("total_cost_usd", 0.0)
    port_pct = payload.get("portfolio_pct", 0.0)
    stop_price = payload.get("stop_price", 0.0)
    stop_pct = payload.get("stop_pct", 10.0)

    msg = (
        f"<b>[STOCKS] BUY PROPOSAL: {ticker}</b>\n"
        f"Score: <b>{score:.2f}</b> | Growth: {growth:.2f} | Multiple: {multiple:.2f} "
        f"| Mgmt: {mgmt:.2f} | Moat: {moat:.2f} | Sent: {sent:.2f}\n\n"
        f"Revenue CAGR 3yr: {rev_cagr}%\n"
        f"P/E vs 5yr avg: {pe_vs}%\n"
        f"Founder CEO: {founder} | Insider ownership: {ins_pct}%\n"
        f"Net insider buying (90d): {ins_net:+,} shares\n"
        f"Moat: {moat_sum}\n\n"
        f"<b>{shares} shares @ ${price:.2f} limit = ${total:,.0f} ({port_pct:.1f}% portfolio)</b>\n"
        f"Stop: ${stop_price:.2f} (-{stop_pct:.0f}%)\n\n"
        f"Reply: <b>BUY {ticker}</b> / <b>SKIP {ticker}</b> / <b>WATCHLIST {ticker}</b>\n"
        f"(Approval window: 24h — no reply = WATCHLIST)"
    )

    ok = send_message(msg)
    if ok:
        _record_pending(ticker, payload)
    return ok


def _record_pending(ticker: str, payload: dict):
    """Add ticker to stocks_pending_approval.json."""
    from datetime import datetime
    file = "stocks_pending_approval.json"
    try:
        try:
            with open(file) as f:
                pending = json.load(f)
        except Exception:
            pending = []
        # Remove any existing entry for this ticker
        pending = [p for p in pending if p.get("ticker") != ticker]
        pending.append({
            "ticker": ticker,
            "payload": payload,
            "sent_at": datetime.utcnow().isoformat(),
            "status": "PENDING",
        })
        with open(file, "w") as f:
            json.dump(pending, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not record pending approval for {ticker}: {e}")


def poll_approvals() -> list[dict]:
    """
    Poll Telegram getUpdates for BUY/SKIP/WATCHLIST replies.
    Returns list of {ticker, action} dicts.

    Actions: BUY, SKIP, WATCHLIST
    Unrecognized messages are ignored.
    """
    token, chat_id = _load_bot_config()
    if not token or not chat_id:
        return []

    offset = _load_offset()
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = requests.get(url, params={"offset": offset, "timeout": 5}, timeout=15)
        r.raise_for_status()
        updates = r.json().get("result", [])
    except Exception as e:
        logger.warning(f"Telegram getUpdates failed: {e}")
        return []

    results = []
    new_offset = offset

    for update in updates:
        new_offset = max(new_offset, update["update_id"] + 1)
        msg = update.get("message") or update.get("channel_post") or {}
        text = (msg.get("text") or "").strip().upper()
        from_chat = str(msg.get("chat", {}).get("id", ""))

        # Only process messages from the configured chat
        if from_chat != str(chat_id):
            continue

        # Parse: BUY AAPL / SKIP AAPL / WATCHLIST AAPL
        parts = text.split()
        if len(parts) >= 2 and parts[0] in ("BUY", "SKIP", "WATCHLIST"):
            action = parts[0]
            ticker = parts[1].upper()
            results.append({"ticker": ticker, "action": action})
            logger.info(f"Telegram approval received: {action} {ticker}")

    if new_offset > offset:
        _save_offset(new_offset)

    return results


def send_alert(text: str):
    """Send a non-proposal alert (position updates, stop-loss hits, etc.)."""
    send_message(f"[STOCKS] {text}")
