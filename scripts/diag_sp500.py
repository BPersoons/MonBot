import json

with open("trade_log.json") as f:
    trades = json.load(f)

sp = [t for t in trades if "SP500" in t.get("ticker", "")]
print(f"=== SP500 trades: {len(sp)} ===")
for t in sp[-5:]:
    status = t.get("status", "?")
    ticker = t.get("ticker", "?")
    action = t.get("action", "?")
    qty = t.get("quantity", 0)
    entry = t.get("entry_price", 0)
    pnl = t.get("pnl", 0) or 0
    reason = t.get("close_reason", "")
    partials = t.get("partial_exits", [])
    pt1 = t.get("partial_tp1_taken", False)
    sl_st = t.get("sl_stage", 0)
    et = str(t.get("exit_time", ""))[:19]
    tid = t.get("id", "?")
    print(f"  [{status}] {ticker} {action} qty={qty} entry={entry} pnl={pnl:+.4f}")
    print(f"    close_reason={reason} partial_tp1={pt1} sl_stage={sl_st} exit={et}")
    print(f"    partial_exits={len(partials)} id={tid}")
    for p in partials:
        print(f"      PARTIAL: qty={p.get('qty')} pnl={p.get('pnl')} reason={p.get('reason')}")

# Also check WTIOIL / CL mapping
print("\n=== CL + WTIOIL trades ===")
cl = [t for t in trades if "CL" in t.get("ticker", "") or "WTIOIL" in t.get("ticker", "")]
for t in cl[-5:]:
    status = t.get("status", "?")
    ticker = t.get("ticker", "?")
    action = t.get("action", "?")
    qty = t.get("quantity", 0)
    print(f"  [{status}] {ticker} {action} qty={qty}")
