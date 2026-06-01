"""Dump all open trades with qty, entry, trade_value, actual_notional."""
import json
from datetime import datetime

t = [x for x in json.load(open("/app/trade_log.json")) if x.get("status") == "OPEN"]
for x in t:
    et = x.get("entry_time")
    et_str = datetime.utcfromtimestamp(et).strftime("%Y-%m-%d %H:%M") if isinstance(et, (int, float)) else str(et)[:16]
    qty = float(x.get("quantity") or 0)
    px = float(x.get("entry_price") or 0)
    tv = float(x.get("trade_value") or 0)
    tkr = x.get("ticker", "?")
    print(f"{tkr:20s} {et_str}  qty={qty:>12.6f}  entry=${px:>10.4f}  tv=${tv:>7.2f}  actual=${qty*px:>7.2f}")
