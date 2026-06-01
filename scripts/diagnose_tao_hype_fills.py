"""Diagnose why TAO, HYPE, BTC, ETH positions on HL differ from trade_value.

Fetches all fills from HL, reconstructs the cumulative position over time for
each ticker of interest, and shows exactly when/how the position shrank.
"""
import sys
sys.path.insert(0, '/app')
from collections import defaultdict
from datetime import datetime
from utils.exchange_client import HyperliquidExchange

TICKERS = ['TAO', 'HYPE', 'BTC', 'ETH', 'VVV']

ex = HyperliquidExchange(testnet=False)
fills = ex.signing_client.fetch_my_trades(limit=1000)
print(f"Fetched {len(fills)} total fills\n")

by_base = defaultdict(list)
for f in fills:
    base = f['symbol'].split('/')[0].upper()
    by_base[base].append(f)

for tkr in TICKERS:
    fs = sorted(by_base.get(tkr, []), key=lambda x: x.get('timestamp', 0))
    if not fs:
        print(f"=== {tkr}: no fills ===\n")
        continue
    print(f"=== {tkr}: {len(fs)} fills ===")
    running_qty = 0.0
    for f in fs:
        side = f.get('side', '?')
        amt = float(f.get('amount') or 0)
        price = float(f.get('price') or 0)
        ts = f.get('timestamp', 0)
        dt = datetime.utcfromtimestamp(ts / 1000).strftime('%m-%d %H:%M:%S') if ts else '?'
        signed_amt = amt if side == 'buy' else -amt
        running_qty += signed_amt
        info = f.get('info') or {}
        dir_hl = info.get('dir', '')
        fee = float(f.get('fee', {}).get('cost') or 0) if f.get('fee') else 0
        notional = amt * price
        print(f"  {dt}  {side:4s} qty={amt:>12.6f} @ ${price:>10.4f}  "
              f"notional=${notional:>8.2f}  running_qty={running_qty:>12.6f}  "
              f"dir={dir_hl}  fee=${fee:.4f}")
    print(f"  → Final running qty: {running_qty:.6f}\n")
