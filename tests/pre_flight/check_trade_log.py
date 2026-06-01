"""
Pre-flight check: validate trade_log.json before hot-patching to production.

Run this after `python scripts/reconcile_hl_trades.py` and before deploying.

Usage:
    python -m tests.pre_flight.check_trade_log
    python -m tests.pre_flight.check_trade_log --min-records 5

Exit code 0 = valid, exit code 1 = invalid (do not deploy).
"""
import os
import sys
import json
import argparse

REQUIRED_FIELDS = {"id", "ticker", "action", "status", "entry_price", "exit_price", "quantity", "pnl"}

BASE_DIR = "/app" if os.path.exists("/app/main.py") else os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
TRADE_LOG = os.path.join(BASE_DIR, "trade_log.json")


def check(min_records: int = 1) -> bool:
    ok = True

    # 1. File exists
    if not os.path.exists(TRADE_LOG):
        print(f"FAIL  trade_log.json not found at {TRADE_LOG}")
        return False
    print(f"OK    File exists: {TRADE_LOG}")

    # 2. Non-empty file
    size = os.path.getsize(TRADE_LOG)
    if size == 0:
        print("FAIL  trade_log.json is empty (0 bytes) — file was likely corrupted during write")
        return False
    print(f"OK    File size: {size} bytes")

    # 3. Valid JSON
    try:
        with open(TRADE_LOG, "r") as f:
            trades = json.load(f)
    except json.JSONDecodeError as e:
        print(f"FAIL  trade_log.json is not valid JSON: {e}")
        return False
    print(f"OK    Valid JSON")

    # 4. Is a list
    if not isinstance(trades, list):
        print(f"FAIL  Expected a JSON array, got {type(trades).__name__}")
        return False
    print(f"OK    Is a list ({len(trades)} records)")

    # 5. Minimum record count
    if len(trades) < min_records:
        print(f"FAIL  Only {len(trades)} record(s) — expected at least {min_records}. Reconcile script may not have run.")
        ok = False
    else:
        print(f"OK    Record count >= {min_records}")

    # 6. Required fields — only enforced on CLOSED records
    closed_required = {"id", "ticker", "action", "entry_price", "exit_price", "quantity", "pnl"}
    missing_fields_count = 0
    for i, t in enumerate(trades):
        if t.get("status") != "CLOSED":
            continue
        missing = closed_required - set(t.keys())
        if missing:
            print(f"FAIL  CLOSED record {i} (id={t.get('id', '?')}) missing fields: {missing}")
            missing_fields_count += 1
    if missing_fields_count == 0:
        print(f"OK    All CLOSED records have required fields")
    else:
        ok = False

    # 7. No CLOSED records with null/zero entry_price (indicates bad data)
    bad_price = [t.get("id", f"idx:{i}") for i, t in enumerate(trades)
                 if t.get("status") == "CLOSED" and not t.get("entry_price")]
    if bad_price:
        print(f"WARN  {len(bad_price)} CLOSED record(s) have zero/null entry_price: {bad_price[:5]}")
        # Warn only — don't fail, some legacy records may lack prices

    # Summary
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    open_  = [t for t in trades if t.get("status") == "OPEN"]
    total_pnl = sum(float(t.get("pnl") or 0) for t in closed)
    print(f"\nSummary: {len(closed)} closed, {len(open_)} open | total closed PnL: {'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")

    if ok:
        print("\nPASS  trade_log.json is valid — safe to deploy")
    else:
        print("\nFAIL  trade_log.json has issues — fix before deploying")

    return ok


def main():
    parser = argparse.ArgumentParser(description="Validate trade_log.json before hot-patching")
    parser.add_argument("--min-records", type=int, default=1,
                        help="Minimum number of records expected (default: 1)")
    args = parser.parse_args()

    ok = check(min_records=args.min_records)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
