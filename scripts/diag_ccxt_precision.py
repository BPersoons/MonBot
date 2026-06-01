"""Test CCXT Hyperliquid amount_to_precision for the broken tickers.

Call amount_to_precision with the quantities our execute_order would compute
(from Kelly $27 at current price) and see what CCXT turns them into.
"""
import sys
sys.path.insert(0, '/app')
import os
import math
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
client = ex.signing_client or ex.public_client
print(f"signing_client: {'YES' if ex.signing_client else 'NO'}")
print(f"markets loaded: {len(client.markets) if client and client.markets else 0}\n")

TEST = ['TAO/USDC', 'HYPE/USDC', 'BTC/USDC', 'ETH/USDC', 'VVV/USDC', 'LIT/USDC']

for tkr in TEST:
    try:
        sym = ex._normalize_symbol(tkr)
        if not sym:
            print(f"{tkr}: _normalize_symbol returned None\n")
            continue
        mkt = (client.markets or {}).get(sym) or {}
        prec = mkt.get('precision', {})
        info = mkt.get('info', {})
        px = ex.get_market_price(tkr) or 0
        if not px:
            print(f"{tkr}: no price, skip")
            continue
        raw_qty = 27.0 / px
        # Our floor step
        our_step = prec.get('amount', 0.0) or 0.0
        our_floored = math.floor(raw_qty / our_step) * our_step if our_step > 0 else raw_qty
        # CCXT's own amount_to_precision
        try:
            ccxt_str = client.amount_to_precision(sym, raw_qty)
        except Exception as e:
            ccxt_str = f"ERR: {e}"
        try:
            ccxt_str_floored = client.amount_to_precision(sym, our_floored)
        except Exception as e:
            ccxt_str_floored = f"ERR: {e}"
        szDec = info.get('szDecimals') if isinstance(info, dict) else None
        print(f"{tkr:14s} px=${px:>10.4f} raw_qty={raw_qty:>.6f}")
        print(f"   precision.amount={our_step}  szDecimals={szDec}")
        print(f"   our_floor   = {our_floored}")
        print(f"   ccxt(raw)   = {ccxt_str}  (would notional ${float(ccxt_str)*px:.2f})" if not str(ccxt_str).startswith('ERR') else f"   ccxt(raw)   = {ccxt_str}")
        print(f"   ccxt(our)   = {ccxt_str_floored}  (would notional ${float(ccxt_str_floored)*px:.2f})" if not str(ccxt_str_floored).startswith('ERR') else f"   ccxt(our)   = {ccxt_str_floored}")
        print()
    except Exception as e:
        print(f"{tkr}: ERR {e}\n")
