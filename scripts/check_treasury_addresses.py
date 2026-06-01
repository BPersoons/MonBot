"""
Treasury on-chain address audit.

Verifies that all hardcoded and config-based contract addresses
actually contain deployed bytecode on Arbitrum.

Run BEFORE any large treasury transaction or after adding a new protocol.
Requires network access to Arbitrum RPC.

Usage:
    python scripts/check_treasury_addresses.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.treasury_executor import (
    _rpc, _verify_is_contract, _encode_balance_of,
    _TREASURY_WALLET, _USDC_ARB, _AAVE_POOL_ARB, _AUSDC_ARB,
    get_aave_balance, get_arb_usdc_balance,
    _USDC_DECIMALS,
)

PASS = "\033[32m  OK \033[0m"
FAIL = "\033[31m FAIL\033[0m"
WARN = "\033[33m WARN\033[0m"


def check(label: str, condition: bool, detail: str = "") -> bool:
    status = PASS if condition else FAIL
    print(f"{status}  {label}" + (f" — {detail}" if detail else ""))
    return condition


def main():
    failures = 0

    print("\n=== Treasury On-Chain Address Audit ===\n")
    print("[ Hardcoded contract addresses ]\n")

    # USDC on Arbitrum
    ok = _verify_is_contract(_USDC_ARB)
    if not check(f"USDC ({_USDC_ARB[:12]}…)", ok, "contract bytecode present" if ok else "NO BYTECODE — WRONG ADDRESS"):
        failures += 1

    # Aave v3 Pool proxy
    ok = _verify_is_contract(_AAVE_POOL_ARB)
    if not check(f"Aave v3 Pool ({_AAVE_POOL_ARB[:12]}…)", ok, "contract bytecode present" if ok else "NO BYTECODE — WRONG ADDRESS"):
        failures += 1

    # aUSDCn receipt token
    ok = _verify_is_contract(_AUSDC_ARB)
    if not check(f"aUSDCn ({_AUSDC_ARB[:12]}…)", ok, "contract bytecode present" if ok else "NO BYTECODE — WRONG ADDRESS"):
        failures += 1

    # Verify USDC decimals() returns 6
    print()
    try:
        result = _rpc("eth_call", [{"to": _USDC_ARB, "data": "0x313ce567"}, "latest"])  # decimals()
        decimals = int(result, 16) if result and result != "0x" else -1
        if not check(f"USDC decimals() == 6", decimals == 6, f"got {decimals}"):
            failures += 1
    except Exception as e:
        print(f"{FAIL}  USDC decimals() call failed: {e}")
        failures += 1

    # Verify aUSDCn decimals() returns 6
    try:
        result = _rpc("eth_call", [{"to": _AUSDC_ARB, "data": "0x313ce567"}, "latest"])
        decimals = int(result, 16) if result and result != "0x" else -1
        if not check(f"aUSDCn decimals() == 6", decimals == 6, f"got {decimals}"):
            failures += 1
    except Exception as e:
        print(f"{FAIL}  aUSDCn decimals() call failed: {e}")
        failures += 1

    print("\n[ Live balances ]\n")

    aave_bal = get_aave_balance(_TREASURY_WALLET)
    usdc_bal = get_arb_usdc_balance(_TREASURY_WALLET)
    check(f"Aave balance readable", True, f"${aave_bal:.2f} aUSDCn")
    check(f"Treasury wallet USDC readable", True, f"${usdc_bal:.2f}")

    print("\n[ Config protocol addresses ]\n")

    try:
        with open("config/treasury_protocols.json") as f:
            protocols = json.load(f).get("protocols", [])
    except Exception as e:
        print(f"{WARN}  Could not read treasury_protocols.json: {e}")
        protocols = []

    has_protocol_addresses = False
    for p in protocols:
        pid = p.get("id", "?")
        for addr_key in ("pool_address", "vault_address", "comet_address"):
            addr = p.get(addr_key)
            if addr:
                has_protocol_addresses = True
                ok = _verify_is_contract(addr)
                label = f"Protocol '{pid}' {addr_key} ({addr[:12]}…)"
                if not check(label, ok, "contract OK" if ok else "NO BYTECODE — VERIFY ADDRESS"):
                    failures += 1

    if not has_protocol_addresses:
        print(f"  (no automated protocol addresses configured yet)")

    print()
    print(f"=== Result: {'PASSED' if failures == 0 else f'FAILED ({failures} issue(s))'} ===\n")

    if failures > 0:
        print("Fix ALL failures before executing any treasury transaction.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
