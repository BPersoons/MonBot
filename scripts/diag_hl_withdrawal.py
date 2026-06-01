"""Diagnose why _attempt_hl_withdrawal fails."""
import sys, os, json
sys.path.insert(0, "/app")

from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v

print("=== Secret availability ===")
for key in ("HL_VAULT_PRIVATE_KEY", "HL_VAULT_ADDRESS", "HL_WALLET_ADDRESS", "HL_PRIVATE_KEY"):
    val = os.getenv(key, "")
    print(f"  {key}: {'SET (' + val[:6] + '…)' if val else 'NOT SET'}")

print("\n=== _create_vault_withdrawal_client ===")
from utils.treasury_executor import _create_vault_withdrawal_client, _TREASURY_WALLET

client = _create_vault_withdrawal_client()
print(f"  Client created: {client is not None}")

if client:
    print(f"  walletAddress: {client.options.get('walletAddress','?') or getattr(client,'wallet_address','?')}")
    # Check supported withdrawal methods
    try:
        markets = client.load_markets()
        print(f"  Markets loaded: {len(markets)}")
        print(f"  Has withdraw: {hasattr(client, 'withdraw')}")
    except Exception as e:
        print(f"  load_markets failed: {e}")

print("\n=== HL vault address vs treasury wallet ===")
vault_addr = os.getenv("HL_VAULT_ADDRESS") or os.getenv("HL_WALLET_ADDRESS", "")
print(f"  HL vault address: {vault_addr}")
print(f"  Treasury wallet:  {_TREASURY_WALLET}")
print(f"  Same address: {vault_addr.lower() == _TREASURY_WALLET.lower() if vault_addr else 'unknown'}")

print("\n=== Current Arbitrum USDC on treasury wallet ===")
from utils.treasury_executor import get_arb_usdc_balance
bal = get_arb_usdc_balance(_TREASURY_WALLET)
print(f"  Balance: ${bal:.4f}")

print("\n=== HL balance ===")
from utils.exchange_client import HyperliquidExchange
ex = HyperliquidExchange(testnet=False)
print(f"  HL balance: ${ex.get_balance():.2f}")
print(f"  Free margin: ${ex.get_free_margin():.2f}")

print("\n=== TRP_20260524_0335 proposal details ===")
try:
    with open("treasury_proposals.json") as f:
        proposals = json.load(f)
    p = next((p for p in proposals if p.get("id") == "TRP_20260524_0335"), None)
    if p:
        print(f"  source: {p.get('source', 'not set')}")
        print(f"  amount_usd: ${p.get('amount_usd', 0):.2f}")
        print(f"  source_hl: ${p.get('source_hl', 0):.2f}")
        print(f"  source_treasury: ${p.get('source_treasury', 0):.2f}")
        print(f"  protocol: {p.get('protocol')}")
    else:
        print("  proposal not found")
except Exception as e:
    print(f"  error: {e}")
