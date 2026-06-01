"""Compare public_client.markets vs signing_client.markets for broken tickers."""
import sys
sys.path.insert(0, '/app')
import os
from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange

ex = HyperliquidExchange(testnet=False)
pub = ex.public_client
sig = ex.signing_client
print(f"public_client.markets keys: {len(pub.markets or {})}")
print(f"signing_client.markets keys: {len(sig.markets or {}) if sig else 0}")
print()

# Try to load markets on signing_client
try:
    sig.load_markets()
    print(f"After sig.load_markets(): {len(sig.markets or {})} keys\n")
except Exception as e:
    print(f"sig.load_markets() ERR: {e}\n")

# Now compare precision for broken tickers
for tkr in ['TAO/USDC:USDC', 'HYPE/USDC:USDC', 'BTC/USDC:USDC', 'VVV/USDC:USDC']:
    p_mkt = (pub.markets or {}).get(tkr, {}) or {}
    s_mkt = (sig.markets or {}).get(tkr, {}) if sig else {}
    p_prec = p_mkt.get('precision', {})
    s_prec = (s_mkt or {}).get('precision', {})
    p_info = p_mkt.get('info', {})
    s_info = (s_mkt or {}).get('info', {})
    print(f"{tkr}")
    print(f"  public precision: {p_prec}")
    print(f"  signing precision: {s_prec}")
    print(f"  public szDecimals: {p_info.get('szDecimals') if isinstance(p_info, dict) else 'n/a'}")
    print(f"  signing szDecimals: {s_info.get('szDecimals') if isinstance(s_info, dict) else 'n/a'}")
    print(f"  public contractSize: {p_mkt.get('contractSize')}")
    print(f"  signing contractSize: {s_mkt.get('contractSize') if s_mkt else 'n/a'}")
    # Try amount_to_precision on the signing client now
    try:
        out = sig.amount_to_precision(tkr, 0.68)
        print(f"  sig.amount_to_precision({tkr}, 0.68) = {out}")
    except Exception as e:
        print(f"  sig.amount_to_precision ERR: {e}")
    try:
        out2 = pub.amount_to_precision(tkr, 0.68)
        print(f"  pub.amount_to_precision({tkr}, 0.68) = {out2}")
    except Exception as e:
        print(f"  pub.amount_to_precision ERR: {e}")
    print()
