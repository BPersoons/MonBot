"""
Reconcile Hyperliquid fill history into trade_log.json.

Replaces import_hl_history.py. Uses position-tracking cycle detection so that
multiple open/close cycles on the same ticker produce separate trade records.

Usage:
    python scripts/reconcile_hl_trades.py [--dry-run]

    --dry-run   Print what would be imported without writing any files.

Works both locally (reads secrets from .env.adk) and inside the container.
"""
import os
import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Portable path setup — works in container (/app) and locally
# ---------------------------------------------------------------------------
BASE_DIR = "/app" if os.path.exists("/app/main.py") else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
TRADE_LOG = os.path.join(BASE_DIR, "trade_log.json")

# ---------------------------------------------------------------------------
# Secrets — gcp_secrets falls back to .env.adk when GOOGLE_CLOUD_PROJECT unset
# ---------------------------------------------------------------------------
from utils.gcp_secrets import get_all_trading_secrets  # noqa: E402

secrets = get_all_trading_secrets()
for k, v in secrets.items():
    if v:
        os.environ[k] = v

from utils.exchange_client import HyperliquidExchange  # noqa: E402
from utils.db_client import DatabaseClient              # noqa: E402


# ---------------------------------------------------------------------------
# Direction parsing
# ---------------------------------------------------------------------------

def _parse_direction(fill):
    """Return (signed_delta_per_unit, is_open) from fill.

    signed_delta > 0 means the fill increases net long position.
    """
    d = (fill.get("info") or {}).get("dir", "")
    if d == "Open Long":   return +1, True
    if d == "Close Long":  return -1, False
    if d == "Open Short":  return -1, True
    if d == "Close Short": return +1, False
    # Fallback: use ccxt side field (less precise for shorts)
    return (+1 if fill.get("side") == "buy" else -1), True


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def group_into_cycles(fills):
    """Walk fills chronologically, splitting on position open/close boundaries.

    Returns a list of dicts: {entry_fills, exit_fills, direction (+1=long/-1=short)}
    Only fully closed cycles are returned.
    """
    cycles = []
    net_pos = 0.0
    current = None

    for fill in sorted(fills, key=lambda x: x.get("timestamp") or 0):
        delta, is_open = _parse_direction(fill)
        qty = float(fill.get("amount") or 0)

        if abs(net_pos) < 1e-9 and is_open:
            # Starting a new cycle
            current = {
                "entry_fills": [fill],
                "exit_fills": [],
                "direction": delta,
            }
            net_pos += delta * qty

        elif current is not None:
            if is_open:
                current["entry_fills"].append(fill)
            else:
                current["exit_fills"].append(fill)
            net_pos += delta * qty

            if abs(net_pos) < 1e-9:
                # Position fully closed → cycle complete
                cycles.append(current)
                current = None
                net_pos = 0.0

    # Note: any remaining `current` is a still-open position — skip it
    return cycles


# ---------------------------------------------------------------------------
# VWAP helper
# ---------------------------------------------------------------------------

def vwap(fills):
    total_cost = sum(float(f.get("price") or 0) * float(f.get("amount") or 0) for f in fills)
    total_qty  = sum(float(f.get("amount") or 0) for f in fills)
    return total_cost / total_qty if total_qty else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Reconcile HL trade history into trade_log.json")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be imported without writing")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        print("[DRY RUN] No files will be written.\n")

    # Connect
    ex = HyperliquidExchange(testnet=False)
    db = DatabaseClient()

    # Fetch all fills
    fills = ex.signing_client.fetch_my_trades(limit=500)
    print(f"Fetched {len(fills)} fills from Hyperliquid\n")

    # Load existing trade log
    try:
        with open(TRADE_LOG) as f:
            trades = json.load(f)
    except FileNotFoundError:
        trades = []

    open_bases = {
        t["ticker"].split("/")[0].upper()
        for t in trades
        if t.get("status") == "OPEN"
    }
    existing_ids = {str(t.get("id", "")) for t in trades}
    print(f"Currently open bases (will skip): {sorted(open_bases)}")
    print(f"Existing trade records: {len(trades)}\n")

    # Group fills by base symbol
    by_sym = defaultdict(list)
    for fill in fills:
        base = fill["symbol"].split("/")[0].upper()
        by_sym[base].append(fill)

    new_trades = []

    for base in sorted(by_sym):
        if base in open_bases:
            print(f"  [{base}] Skipping — position currently open")
            continue

        sym_fills = by_sym[base]
        ticker = sym_fills[0]["symbol"].split(":")[0]  # e.g. "EIGEN/USDC"

        cycles = group_into_cycles(sym_fills)
        print(f"  [{base}] {len(sym_fills)} fills -> {len(cycles)} closed cycle(s)")

        for cycle in cycles:
            first_entry_ts = cycle["entry_fills"][0].get("timestamp") or 0
            cycle_id = f"HL_{base}_{first_entry_ts}"

            if cycle_id in existing_ids:
                print(f"    Cycle {cycle_id}: already imported — skipping")
                continue

            entry_p = vwap(cycle["entry_fills"])
            exit_p  = vwap(cycle["exit_fills"])
            total_qty = sum(float(f.get("amount") or 0) for f in cycle["entry_fills"])

            # Use HL-authoritative closed PnL from close fills
            pnl = round(
                sum(float((f.get("info") or {}).get("closedPnl") or 0) for f in cycle["exit_fills"]),
                4,
            )
            pnl_pct = round((exit_p - entry_p) / entry_p * 100, 2) if entry_p else 0.0

            fees = round(
                sum(
                    float((f.get("fee") or {}).get("cost") or 0)
                    for f in cycle["entry_fills"] + cycle["exit_fills"]
                ),
                6,
            )

            last_exit = cycle["exit_fills"][-1] if cycle["exit_fills"] else cycle["entry_fills"][-1]
            first_entry = cycle["entry_fills"][0]

            action = "BUY" if cycle["direction"] > 0 else "SELL"

            record = {
                "id": cycle_id,
                "ticker": ticker,
                "action": action,
                "status": "CLOSED",
                "entry_price": entry_p,
                "exit_price": exit_p,
                "quantity": total_qty,
                "pnl": pnl,
                "pnl_percent": pnl_pct,
                "entry_fmt": str(first_entry.get("datetime", ""))[:19],
                "entry_time": first_entry_ts / 1000,
                "exit_time": str(last_exit.get("datetime", ""))[:19],
                "close_reason": "HL_HISTORY_IMPORT",
                "source": "HYPERLIQUID",
                "conviction": 0.0,
                "fees": fees,
            }

            entry_dt = datetime.fromtimestamp(first_entry_ts / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            print(
                f"    Cycle {cycle_id}: {action} {total_qty:.4f} {base} | "
                f"entry={entry_p:.4f} exit={exit_p:.4f} pnl={pnl:+.4f} ({pnl_pct:+.2f}%) | {entry_dt}"
            )

            if not dry_run:
                trades.append(record)
                existing_ids.add(cycle_id)
                new_trades.append(record)

                try:
                    db.client.table("trades").insert({
                        "ticker": ticker,
                        "action": action,
                        "status": "CLOSED",
                        "entry_price": entry_p,
                        "exit_price": exit_p,
                        "quantity": total_qty,
                        "pnl": pnl,
                        "closed_at": str(last_exit.get("datetime", ""))[:19],
                        "created_at": str(first_entry.get("datetime", ""))[:19],
                        "analyst_signals": {},
                        "reasoning_trace": {},
                    }).execute()
                except Exception as e:
                    print(f"    Supabase insert failed for {cycle_id}: {e}")
            else:
                new_trades.append(record)  # count for dry-run summary

    print()
    if dry_run:
        print(f"[DRY RUN] Would add {len(new_trades)} new trade record(s). No files written.")
        print("\nNext step: run without --dry-run to write, then hot-patch trade_log.json to production.")
    else:
        with open(TRADE_LOG, "w") as f:
            json.dump(trades, f, indent=2, default=str)
        print(f"Done. Added {len(new_trades)} new trade record(s). Total records: {len(trades)}")
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
