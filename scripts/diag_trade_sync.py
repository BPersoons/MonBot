"""Quick diagnostic: compare trade_log open trades vs HL positions."""
import json

with open("trade_log.json") as f:
    trades = json.load(f)

open_trades = [t for t in trades if t.get("status") in ("OPEN", "PLACED")]
print(f"=== TRADE LOG: {len(open_trades)} open trades ===")
for t in open_trades:
    ticker = t.get("ticker", "?")
    action = t.get("action", "?")
    qty = t.get("quantity", 0)
    entry = t.get("entry_price", 0)
    sl_stage = t.get("sl_stage", 0)
    partial = t.get("partial_tp1_taken", False)
    partials = t.get("partial_exits", [])
    skipped = t.get("skipped_partials", [])
    tid = t.get("id", "?")
    print(f"  {ticker:25} {action:5} qty={qty:.4f} entry={entry:.4f} "
          f"sl_stage={sl_stage} partial_tp1={partial} "
          f"partial_exits={len(partials)} skipped_partials={len(skipped)} "
          f"id={tid}")
    if partials:
        for p in partials:
            print(f"    PARTIAL: qty={p.get('qty',0)} pnl={p.get('pnl',0)} reason={p.get('reason','?')}")

# Recent closed
closed = [t for t in trades if t.get("status") == "CLOSED"]
print(f"\n=== RECENT CLOSED (last 10) ===")
for t in closed[-10:]:
    ticker = t.get("ticker", "?")
    action = t.get("action", "?")
    pnl = t.get("pnl", 0) or 0
    reason = t.get("close_reason", "?")
    exit_time = str(t.get("exit_time", "?"))[:19]
    print(f"  {ticker:25} {action:5} pnl={pnl:+.4f} reason={reason} exit={exit_time}")

# Check active_assets
try:
    with open("active_assets.json") as f:
        active = json.load(f)
    print(f"\n=== ACTIVE ASSETS: {len(active)} ===")
    for a in active:
        print(f"  {a}")
except Exception:
    print("\nactive_assets.json not found")
