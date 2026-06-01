"""Empirical test: does spot USDC count as perp collateral?

Places a small $30 BTC market order, observes fill, reports margin state
before and after. Then closes the position. This definitively distinguishes
Unified (spot pools with perp) from Standard (spot segregated) mode.
"""
import sys, os, time
sys.path.insert(0, '/app')

from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v

from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
client = ex.signing_client
user = ex.vault_address or ex.wallet_address


def show_margin(label):
    raw = client.fetch_balance(params={'user': user})
    info = raw.get('info') or {}
    m = info.get('marginSummary') or {}
    print(f"--- {label} ---")
    print(f"  accountValue:    ${float(m.get('accountValue') or 0):.4f}")
    print(f"  totalMarginUsed: ${float(m.get('totalMarginUsed') or 0):.4f}")
    print(f"  totalNtlPos:     ${float(m.get('totalNtlPos') or 0):.4f}")
    print(f"  withdrawable:    ${float(m.get('withdrawable') or 0):.4f}")
    print(f"  get_balance():   ${ex.get_balance():.4f}")
    print(f"  get_free_margin: ${ex.get_free_margin():.4f}")
    print()


# 1. List current positions to find a ticker not in use
print("=" * 60)
print("STEP 1: List open positions")
print("=" * 60)
positions = ex.fetch_all_positions()
open_symbols = set()
for p in positions:
    contracts = p.get('contracts') or 0
    if contracts and abs(float(contracts)) > 0:
        sym = p.get('symbol')
        open_symbols.add(sym)
        print(f"  OPEN: {sym}  contracts={contracts}  notional=${p.get('notional')}")
print(f"Total open symbols: {len(open_symbols)}")
print()

# 2. Pick a test ticker (BTC if free, else ETH, else SOL)
test_ticker = None
for candidate in ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC"]:
    if candidate not in open_symbols:
        test_ticker = candidate
        break
if not test_ticker:
    print("ERROR: BTC, ETH, SOL all have open positions. Pick manually.")
    sys.exit(1)
print(f"Test ticker: {test_ticker}")
print()

# 3. Show pre-order margin
print("=" * 60)
print("STEP 2: Pre-order margin state")
print("=" * 60)
show_margin("PRE-ORDER")

# 4. Place small market buy
print("=" * 60)
print("STEP 3: Place $30 market BUY")
print("=" * 60)
price = ex.get_market_price(test_ticker)
print(f"{test_ticker} price: ${price:.4f}")
target_notional = 30.0
qty = target_notional / price
# Respect precision
prec = ex.get_amount_precision(test_ticker)
if prec and prec > 0:
    qty = round(qty / prec) * prec
    qty = round(qty, 8)
print(f"Placing market BUY {qty} (~${qty*price:.2f} notional)...")
print()

order = ex.create_order(test_ticker, "buy", qty, price=price, order_type="market")
print(f"Order result: {order}")
print()

# 5. Post-order state
time.sleep(3)
print("=" * 60)
print("STEP 4: Post-order margin state")
print("=" * 60)
show_margin("POST-ORDER")

# Check what actually filled
post_positions = client.fetch_positions([test_ticker], params={'user': user})
filled_qty = 0.0
for p in post_positions:
    if p.get('symbol') == test_ticker:
        c = p.get('contracts') or 0
        if c:
            filled_qty = abs(float(c))
            print(f"FILLED: contracts={c}, notional=${p.get('notional')}, entry=${p.get('entryPrice')}")
print()

# 6. Close position
if filled_qty > 0:
    print("=" * 60)
    print("STEP 5: Close position")
    print("=" * 60)
    close_price = ex.get_market_price(test_ticker)
    close_order = ex.create_order(test_ticker, "sell", filled_qty, price=close_price, order_type="market")
    print(f"Close result: {close_order}")
    time.sleep(3)
    print()
    show_margin("POST-CLOSE")
else:
    print("No position was opened — nothing to close.")

print("=" * 60)
print("VERDICT")
print("=" * 60)
print(f"Target notional: $30.00")
print(f"Actual filled:   ${filled_qty * price:.2f}")
if filled_qty * price >= 25:
    print(">>> FULL FILL: Unified mode is active. Spot USDC works as perp collateral.")
    print(">>> Code fix needed: get_free_margin() should read a different field.")
elif filled_qty * price > 1:
    print(">>> PARTIAL FILL: Mixed state — some margin available but not enough.")
else:
    print(">>> NO/DUST FILL: Standard mode. Spot USDC does NOT collateralize perp.")
    print(">>> Need to transfer spot->perp or actually enable Unified.")
