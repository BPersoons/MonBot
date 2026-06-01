"""Check HL account margin state to see if over-leveraged."""
import sys
sys.path.insert(0, '/app')
import os
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
print(f"get_balance()=${ex.get_balance():.4f}")
try:
    raw = ex.signing_client.fetch_balance()
    info = raw.get("info") or {}
    margin = info.get("marginSummary") or {}
    cross = info.get("crossMarginSummary") or {}
    tot_ntl = margin.get("totalNtlPos")
    tot_raw = margin.get("totalRawUsd")
    acc_val = margin.get("accountValue")
    tot_mm = margin.get("totalMarginUsed")
    cmm = info.get("crossMaintenanceMarginUsed")
    wd = info.get("withdrawable")
    print(f"totalNtlPos:        {tot_ntl}")
    print(f"totalRawUsd:        {tot_raw}")
    print(f"accountValue:       {acc_val}")
    print(f"totalMarginUsed:    {tot_mm}")
    print(f"crossMaintMargin:   {cmm}")
    print(f"withdrawable:       {wd}")
    try:
        free = float(acc_val or 0) - float(tot_mm or 0)
        print(f"→ approx free margin: ${free:.4f}")
        print(f"→ max new order notional @3x: ${free*3:.4f}")
    except Exception:
        pass
except Exception as e:
    print(f"ERR: {e}")
