"""Check HL positions and trade_log open trades."""
import sys, os, json
sys.path.insert(0, '/app')
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)

# 1. HL positions
print("=== HL POSITIONS ===")
positions = ex.fetch_all_positions()
open_pos = [p for p in positions if p.get("contracts") and abs(float(p["contracts"])) > 0]
print(f"Open on HL: {len(open_pos)}")
for p in open_pos:
    sym = p.get("symbol", "?")
    c = p.get("contracts", 0)
    n = p.get("notional", 0)
    print(f"  {sym}: contracts={c} notional={n}")
if not open_pos:
    print("  (none)")

# 2. trade_log open trades
print("\n=== TRADE_LOG OPEN ===")
try:
    with open("trade_log.json") as f:
        trades = json.load(f)
    open_trades = [t for t in trades if t.get("status") in ("OPEN", "PLACED")]
    print(f"Open in trade_log: {len(open_trades)}")
    for t in open_trades:
        ticker = t.get("ticker", "?")
        qty = t.get("quantity", 0)
        entry = t.get("entry_price", 0)
        print(f"  {ticker}: qty={qty} entry={entry} status={t.get('status')}")
except Exception as e:
    print(f"  Error reading trade_log: {e}")

# 3. Balance breakdown
print("\n=== BALANCE ===")
print(f"get_balance(): ${ex.get_balance():.2f}")
print(f"get_free_margin(): ${ex.get_free_margin():.2f}")

# 4. Peak info
print("\n=== PORTFOLIO PEAK ===")
try:
    with open("portfolio_peak.json") as f:
        peak = json.load(f)
    print(f"peak_equity: ${peak.get('peak_equity', 0):.2f}")
    import time
    ts = peak.get("updated_at", 0)
    print(f"updated_at: {time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}")
except Exception as e:
    print(f"  Error: {e}")
