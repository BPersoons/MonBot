import json
with open("trade_log.json") as f:
    trades = json.load(f)
ghosts = [t for t in trades if t.get("id","").startswith("RECOVERED_")]
print(f"Total RECOVERED_: {len(ghosts)}")
for g in ghosts[:5]:
    print(f"  {g['id']}: ticker={g.get('ticker')}, qty={g.get('quantity')}, pnl={g.get('pnl')}, entry={g.get('entry_price')}, status={g.get('status')}")
pnl_zero = sum(1 for g in ghosts if g.get("pnl") == 0.0 or g.get("pnl") is None)
has_pnl = sum(1 for g in ghosts if g.get("pnl") and g.get("pnl") != 0.0)
print(f"\npnl==0.0 or None: {pnl_zero}, has real pnl: {has_pnl}")
