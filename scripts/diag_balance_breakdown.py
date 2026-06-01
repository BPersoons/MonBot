"""Dump raw CCXT balance response to understand double-counting in Unified mode."""
import sys, os, json
sys.path.insert(0, '/app')
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
client = ex.signing_client
user = ex.vault_address or ex.wallet_address

print("=== RAW CCXT fetch_balance ===")
raw = client.fetch_balance(params={'user': user})

# CCXT top-level USDC fields
usdc_entry = raw.get('USDC', {})
print(f"balance['USDC']['total']:  {usdc_entry.get('total')}")
print(f"balance['USDC']['free']:   {usdc_entry.get('free')}")
print(f"balance['USDC']['used']:   {usdc_entry.get('used')}")
print(f"balance['total']['USDC']:  {raw.get('total', {}).get('USDC')}")
print(f"balance['free']['USDC']:   {raw.get('free', {}).get('USDC')}")

# Info/marginSummary
info = raw.get('info') or {}
margin = info.get('marginSummary') or {}
print(f"\nmarginSummary.accountValue:    {margin.get('accountValue')}")
print(f"marginSummary.totalRawUsd:     {margin.get('totalRawUsd')}")
print(f"marginSummary.totalMarginUsed: {margin.get('totalMarginUsed')}")
print(f"marginSummary.totalNtlPos:     {margin.get('totalNtlPos')}")
print(f"marginSummary.withdrawable:    {margin.get('withdrawable')}")

# Spot USDC
import urllib.request
payload = json.dumps({"type": "spotClearinghouseState", "user": user}).encode()
req = urllib.request.Request(
    "https://api.hyperliquid.xyz/info", data=payload,
    headers={"Content-Type": "application/json"}
)
with urllib.request.urlopen(req, timeout=5) as r:
    spot_data = json.loads(r.read())
spot_usdc = 0.0
for entry in spot_data.get("balances", []):
    if entry.get("coin") == "USDC":
        spot_usdc = float(entry.get("total", 0.0))
        print(f"\nspotClearinghouse USDC total: {entry.get('total')}")
        print(f"spotClearinghouse USDC hold:  {entry.get('hold')}")

print(f"\n=== SUMMARY ===")
perps = float(usdc_entry.get('total') or raw.get('total', {}).get('USDC') or 0)
print(f"CCXT perps USDC total:  ${perps:.4f}")
print(f"Spot USDC total:        ${spot_usdc:.4f}")
print(f"Sum (current code):     ${perps + spot_usdc:.4f}")
acv = float(margin.get('accountValue') or 0)
print(f"accountValue:           ${acv:.4f}")
print(f"accountValue + spot:    ${acv + spot_usdc:.4f}")
