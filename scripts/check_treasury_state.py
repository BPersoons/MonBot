import json

print("=== TREASURY PROPOSALS (last 10) ===")
try:
    proposals = json.load(open("treasury_proposals.json"))
    for p in proposals[-10:]:
        print(f"  {p['id']} [{p['status']}] {p.get('type','')} — {p.get('title','')[:60]}")
        if p.get("error"):
            print(f"    ERROR: {p['error'][:120]}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== TREASURY STATE ===")
try:
    s = json.load(open("treasury_state.json"))
    print(f"  timestamp: {s.get('timestamp')}")
    print(f"  hl_snapshot: ${s.get('hl_snapshot', {}).get('total_equity', 0):.2f}")
    yb = s.get("yield_balances", {})
    for k, v in yb.items():
        print(f"  {k}: ${v:.2f}")
    print(f"  treasury_wallet_usdc: ${s.get('treasury_wallet_usdc', 0):.2f}")
    print(f"  total_portfolio: ${s.get('total_portfolio', 0):.2f}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== TREASURY HARVEST ===")
try:
    h = json.load(open("treasury_harvest.json"))
    print(f"  {h}")
except Exception as e:
    print(f"  ERROR: {e}")
