"""
Sync currently-open Hyperliquid positions into trade_log.json.

Fetches live positions via ccxt fetch_positions(), creates OPEN trade records
for any position not already tracked in trade_log.json.

Usage:
    python scripts/sync_open_positions.py [--dry-run]

Works both locally (reads secrets from .env.adk) and inside the container.
"""
import os
import sys
import json
import argparse
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Portable path setup — works in container (/app) and locally
# ---------------------------------------------------------------------------
BASE_DIR = "/app" if os.path.exists("/app/main.py") else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
TRADE_LOG = os.path.join(BASE_DIR, "trade_log.json")

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
from utils.gcp_secrets import get_all_trading_secrets  # noqa: E402

secrets = get_all_trading_secrets()
for k, v in secrets.items():
    if v:
        os.environ[k] = v

from utils.exchange_client import HyperliquidExchange  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Sync open HL positions into trade_log.json")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be added without writing")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        print("[DRY RUN] No files will be written.\n")

    ex = HyperliquidExchange(testnet=False)
    if not ex.signing_client:
        print("ERROR: Exchange client not available (missing HL credentials).")
        sys.exit(1)

    # Fetch open positions from Hyperliquid
    user_addr = getattr(ex, 'vault_address', None) or ex.wallet_address
    try:
        positions = ex.signing_client.fetch_positions(params={'user': user_addr})
    except Exception as e:
        print(f"ERROR: fetch_positions failed: {e}")
        sys.exit(1)

    open_positions = [p for p in positions if abs(float(p.get('contracts') or p.get('info', {}).get('szi', 0) or 0)) > 1e-9]
    print(f"Found {len(open_positions)} open position(s) on Hyperliquid.\n")

    # Load existing trade log
    try:
        with open(TRADE_LOG) as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []

    # Build set of tickers already tracked as OPEN in trade_log
    open_tickers = {
        t["ticker"].split("/")[0].upper()
        for t in trades
        if t.get("status") in ("OPEN", "PLACED")
    }
    print(f"Already tracked as OPEN in trade_log: {sorted(open_tickers)}")

    added = 0
    for pos in open_positions:
        info = pos.get("info") or {}
        symbol = pos.get("symbol", "")  # e.g. "BTC/USDC:USDC"
        base = symbol.split("/")[0].upper()
        ticker = symbol.split(":")[0]   # e.g. "BTC/USDC"

        if base in open_tickers:
            print(f"  [{base}] Already tracked — skipping")
            continue

        contracts = float(pos.get("contracts") or info.get("szi") or 0)
        direction = "long" if contracts > 0 else "short"
        qty = abs(contracts)
        entry_price = float(pos.get("entryPrice") or info.get("entryPx") or 0)
        mark_price = float(pos.get("markPrice") or info.get("markPx") or entry_price)
        unrealized_pnl = float(pos.get("unrealizedPnl") or info.get("unrealizedPnl") or 0)

        now_ts = datetime.now(tz=timezone.utc)
        trade_id = f"HL_OPEN_{base}_{int(now_ts.timestamp() * 1000)}"

        record = {
            "id": trade_id,
            "ticker": ticker,
            "action": "BUY" if direction == "long" else "SELL",
            "status": "OPEN",
            "entry_price": entry_price,
            "exit_price": None,
            "quantity": qty,
            "pnl": round(unrealized_pnl, 4),
            "pnl_percent": round((mark_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0,
            "entry_fmt": now_ts.strftime("%Y-%m-%dT%H:%M:%S"),
            "entry_time": now_ts.timestamp(),
            "exit_time": None,
            "close_reason": None,
            "source": "HL_POSITION_SYNC",
            "conviction": 0.0,
            "fees": 0.0,
        }

        print(
            f"  [{base}] {direction.upper()} {qty} @ entry={entry_price:.4f} "
            f"mark={mark_price:.4f} uPnL={unrealized_pnl:+.4f} id={trade_id}"
        )

        if not dry_run:
            trades.append(record)
            open_tickers.add(base)
            added += 1
        else:
            added += 1

    print()
    if dry_run:
        print(f"[DRY RUN] Would add {added} OPEN trade record(s). No files written.")
        print("\nNext step: run without --dry-run to write, then hot-patch to production.")
    else:
        with open(TRADE_LOG, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"Done. Added {added} OPEN record(s). Total records: {len(trades)}")
        print(f"Written to: {TRADE_LOG}")
        print(
            "\nNext step: hot-patch to production:\n"
            "  gcloud compute scp trade_log.json agent-trader-swarm-vm:~/trade_log.json --zone=europe-west1-b\n"
            "  gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b \\\n"
            '    --command="sudo docker cp ~/trade_log.json agent_trader_swarm:/app/trade_log.json '
            '&& sudo docker restart agent_trader_swarm"'
        )


if __name__ == "__main__":
    main()
