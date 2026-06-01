"""Check get_amount_precision and get_min_notional for affected tickers."""
import sys
sys.path.insert(0, '/app')
import math
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
for tkr in ['TAO/USDC', 'HYPE/USDC', 'BTC/USDC', 'ETH/USDC', 'VVV/USDC', 'LIT/USDC', 'XYZ-MU/USDC']:
    prec = ex.get_amount_precision(tkr)
    min_n = ex.get_min_notional(tkr)
    try:
        sym = ex._normalize_symbol(tkr)
        raw_prec = ex.markets.get(sym, {}).get('precision', {})
        limits = ex.markets.get(sym, {}).get('limits', {})
    except Exception as e:
        raw_prec = f'err: {e}'
        limits = {}
    print(f"{tkr:18s} precision.amount={prec}  min_notional=${min_n}")
    print(f"   raw precision dict={raw_prec}")
    print(f"   raw limits dict={limits}")
    # Simulate qty calc for $27 notional
    try:
        px = ex.get_market_price(tkr) or 0
    except Exception:
        px = 0
    if px and prec:
        raw_qty = 27.0 / px
        if prec > 0:
            floored = math.floor(raw_qty / prec) * prec
        else:
            floored = raw_qty
        print(f"   @px=${px:.4f}  raw_qty(27$)={raw_qty:.6f}  floored={floored:.6f}  notional=${floored*px:.2f}")
    print()
