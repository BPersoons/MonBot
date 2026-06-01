"""Verify RiskManager now uses free_margin for Kelly sizing."""
import sys
sys.path.insert(0, '/app')
import os
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange
from agents.risk_manager import RiskManager

ex = HyperliquidExchange(testnet=False)
rm = RiskManager(exchange_client=ex)

print(f"get_balance():     ${ex.get_balance():.4f}")
print(f"get_free_margin(): ${ex.get_free_margin():.4f}")
print()

# Calculate Kelly with default (fetches from exchange)
out = rm.check_trade_safety(win_probability=0.55, net_odds=2.5)
print(f"Kelly result with live bankroll: {out}")
print()

# Sanity check: force a bankroll to confirm the math works
out2 = rm.check_trade_safety(win_probability=0.55, net_odds=2.5, bankroll=100.0)
print(f"Kelly result with bankroll=$100: {out2}")
