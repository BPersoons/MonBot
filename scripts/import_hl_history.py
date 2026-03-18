"""
One-time script: import closed trade history from Hyperliquid fills into
trade_log.json and Supabase. Run inside the container.
"""
import os, sys, json, time
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, "/app")
os.environ["GOOGLE_CLOUD_PROJECT"] = "gen-lang-client-0441524375"
from utils.gcp_secrets import get_all_trading_secrets
s = get_all_trading_secrets()
for k, v in s.items():
    if v:
        os.environ[k] = v

from utils.exchange_client import HyperliquidExchange
from utils.db_client import DatabaseClient

ex = HyperliquidExchange(testnet=False)
db = DatabaseClient()

# Fetch all HL fills
fills = ex.signing_client.fetch_my_trades(limit=500)
print(f"Fetched {len(fills)} fills from Hyperliquid")

# Current open tickers
with open("/app/trade_log.json") as f:
    trades = json.load(f)
open_bases = {t["ticker"].split("/")[0].upper() for t in trades if t.get("status") == "OPEN"}
existing_ids = {str(t.get("id", "")) for t in trades}
print(f"Currently open: {sorted(open_bases)}")

# Group fills by base symbol
by_sym = defaultdict(list)
for fill in fills:
    base = fill["symbol"].split("/")[0].upper()
    by_sym[base].append(fill)

new_trades = []
for base, sym_fills in sorted(by_sym.items()):
    if base in open_bases:
        # Still update quantities/prices via reconciliation loop — skip here
        continue

    sym_fills.sort(key=lambda x: x.get("timestamp", 0))
    ticker = sym_fills[0]["symbol"].split(":")[0]

    # Skip if already imported
    import_id = "HL_" + base + "_" + str(sym_fills[0].get("timestamp", 0))
    if import_id in existing_ids:
        print(f"  Skipping {ticker} — already imported")
        continue

    buys  = [f for f in sym_fills if f["side"] == "buy"]
    sells = [f for f in sym_fills if f["side"] == "sell"]

    if not buys:
        continue

    entry_fill = buys[0]
    exit_fill  = sells[-1] if sells else buys[-1]
    entry_price = float(entry_fill.get("price") or 0)
    exit_price  = float(exit_fill.get("price") or 0)
    qty = float(entry_fill.get("amount") or 0)
    pnl = round((exit_price - entry_price) * qty, 4) if exit_price and entry_price else 0.0
    pnl_pct = round((exit_price - entry_price) / entry_price * 100, 2) if entry_price else 0.0

    record = {
        "id": import_id,
        "ticker": ticker,
        "action": "BUY",
        "status": "CLOSED",
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": qty,
        "pnl": pnl,
        "pnl_percent": pnl_pct,
        "entry_fmt": str(entry_fill.get("datetime", ""))[:19],
        "entry_time": entry_fill.get("timestamp", 0) / 1000,
        "exit_time": str(exit_fill.get("datetime", ""))[:19],
        "close_reason": "HL_HISTORY_IMPORT",
        "source": "HYPERLIQUID",
        "conviction": 0.0,
        "fees": round(sum(float((f.get("fee") or {}).get("cost") or 0) for f in sym_fills), 6),
    }
    trades.append(record)
    new_trades.append(record)
    print(f"  Imported {ticker}: entry={entry_price} exit={exit_price} pnl={pnl}")

    try:
        db.client.table("trades").insert({
            "ticker": ticker,
            "action": "BUY",
            "status": "CLOSED",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": qty,
            "pnl": pnl,
            "closed_at": str(exit_fill.get("datetime", ""))[:19],
            "created_at": str(entry_fill.get("datetime", ""))[:19],
            "analyst_signals": {},
            "reasoning_trace": {},
        }).execute()
    except Exception as e:
        print(f"  Supabase insert failed for {ticker}: {e}")

with open("/app/trade_log.json", "w") as f:
    json.dump(trades, f, indent=2, default=str)

print(f"\nDone. Added {len(new_trades)} closed trades. Total trades: {len(trades)}")
