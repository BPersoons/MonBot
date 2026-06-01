import json
with open("trade_log.json") as f:
    trades = json.load(f)
ghosts = [t for t in trades if t.get("id","").startswith("RECOVERED_")]
real = [t for t in trades if not t.get("id","").startswith("RECOVERED_")]
null_qty = sum(1 for t in ghosts if t.get("quantity") is None)
null_pnl = sum(1 for t in ghosts if t.get("pnl") is None)
print(f"Total: {len(trades)}, RECOVERED_: {len(ghosts)}, real: {len(real)}")
print(f"Ghosts null quantity: {null_qty}, null pnl: {null_pnl}")
if ghosts:
    g = ghosts[0]
    print(f"Sample: id={g['id']}, ticker={g.get('ticker')}, qty={g.get('quantity')}, pnl={g.get('pnl')}")
