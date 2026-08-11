#!/usr/bin/env python3
"""Fund de Hyperliquid xyz perp-dex van de Thematic Exposure Sleeve.

Waarom dit bestaat
------------------
XYZ-synthetics draaien op een APARTE Hyperliquid builder perp-dex ("xyz") met
z'n EIGEN collateral-pot. Main-dex / spot USDC telt daar niet als marge. Loopt
die pot leeg, dan faalt elke XYZ-order met "Insufficient margin — account fully
allocated" terwijl de wallet gezond oogt (`create_order()` -> None, sleeve stil).

De sleeve draait op een APARTE self-custody wallet (HL_THEMATIC_WALLET_ADDRESS /
HL_THEMATIC_PRIVATE_KEY, 0xBd6c…) — gescheiden van de main-swarm zodat beide
tegelijk in hetzelfde asset kunnen zitten zonder HL-netting-conflict. Omdat de
key naar het account ZELF derivt (geen agent), mag deze wallet user-signed
actions doen: we kunnen de collateral dus programmatisch verplaatsen.

Belangrijk: USDC dat via HL "Send Tokens" naar de wallet gaat, landt in SPOT —
niet op de perps xyz-dex. Dit script verplaatst het met een `sendAsset` HIP-3
transfer (spot -> xyz in één hop). ccxt 4.5.56 wrapt dit niet, dus we signen zelf
(mainnet EIP-712 domain: chainId 42161 / signatureChainId 0xa4b1) en posten via
private_post_exchange. Geverifieerd 2026-07-23 op 0xBd6c (status: ok).

Veiligheid
----------
- `sendAsset` verplaatst binnen HETZELFDE account (destination = eigen adres),
  van sourceDex naar destinationDex. Een verkeerd-gesignde action wordt door HL
  GEWEIGERD — geen fondsverlies, geen partiële transfer.
- Valideer ALTIJD eerst met --amount 1, controleer dat xyz met ~$1 stijgt, dan
  het echte bedrag.

Gebruik (in de container op de VM):
    docker cp scripts/fund_xyz_dex.py agent_trader_swarm:/app/scripts/fund_xyz_dex.py
    docker exec -w /app -e PYTHONPATH=/app agent_trader_swarm \
        python3 scripts/fund_xyz_dex.py --amount 1 --yes
    # controleer, dan het echte bedrag:
    docker exec -w /app -e PYTHONPATH=/app agent_trader_swarm \
        python3 scripts/fund_xyz_dex.py --amount 254 --yes

Opties:
    --from-dex spot   (default) — bron is het spot-account (waar deposits landen)
    --from-dex ""     — bron is de main perp-dex
    --wallet main     — gebruik de main-swarm wallet i.p.v. de thematic wallet
                        (LET OP: die draait op een AGENT-key en kan GEEN fondsen
                        verplaatsen; alleen zinvol met een master-key lokaal)
"""
from __future__ import annotations

import argparse
import sys
import time

MAINNET_DOMAIN_CHAINID = 42161          # Arbitrum One
SIGNATURE_CHAIN_ID = "0xa4b1"           # matcht domain-chainId; HL mainnet
ZERO_VERIFYING = "0x0000000000000000000000000000000000000000"

SEND_ASSET_TYPES = {
    "HyperliquidTransaction:SendAsset": [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "sourceDex", "type": "string"},
        {"name": "destinationDex", "type": "string"},
        {"name": "token", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "fromSubAccount", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
}


def _dex_value(client, dex: str) -> float:
    """accountValue (USDC) op een perp-dex ('' = main, 'xyz' = builder)."""
    bal = client.fetch_balance(params={"dex": dex} if dex else {})
    ms = (bal.get("info", {}) or {}).get("marginSummary", {}) or {}
    try:
        return float(ms.get("accountValue", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _spot_usdc(client, address: str) -> float:
    s = client.publicPostInfo({"type": "spotClearinghouseState", "user": address})
    for b in s.get("balances", []) or []:
        if b.get("coin") == "USDC":
            try:
                return float(b.get("total", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _resolve_usdc_token(client) -> str:
    """HL sendAsset verwacht token als 'USDC:0x...'. Resolve het token-id live."""
    meta = client.publicPostInfo({"type": "spotMeta"})
    for tok in meta.get("tokens", []) or []:
        if (tok.get("name") or "").upper() == "USDC":
            token_id = tok.get("tokenId")
            if token_id:
                return f"USDC:{token_id}"
    raise RuntimeError("USDC token-id niet gevonden in spotMeta")


def _source_balance(client, address: str, from_dex: str) -> float:
    return _spot_usdc(client, address) if from_dex == "spot" else _dex_value(client, from_dex)


def _send_asset(client, address: str, amount: float, from_dex: str, to_dex: str) -> dict:
    token = _resolve_usdc_token(client)
    nonce = client.milliseconds()
    str_amount = client.number_to_string(amount)
    message = {
        "hyperliquidChain": "Mainnet",
        "destination": address,          # eigen adres: binnen-account transfer
        "sourceDex": from_dex,
        "destinationDex": to_dex,
        "token": token,
        "amount": str_amount,
        "fromSubAccount": "",
        "nonce": nonce,
    }
    # Zelf signen: ccxt's sign_user_signed_action hardcodet de testnet-chainId
    # (421614) -> HL weigert met "Mainnet and testnet require different signature".
    domain = {
        "chainId": MAINNET_DOMAIN_CHAINID,
        "name": "HyperliquidSignTransaction",
        "verifyingContract": ZERO_VERIFYING,
        "version": "1",
    }
    enc = client.eth_encode_structured_data(domain, SEND_ASSET_TYPES, message)
    signature = client.sign_message(enc, client.privateKey)
    request = {
        "action": {
            "type": "sendAsset",
            "signatureChainId": SIGNATURE_CHAIN_ID,
            "hyperliquidChain": "Mainnet",
            "destination": address,
            "sourceDex": from_dex,
            "destinationDex": to_dex,
            "token": token,
            "amount": str_amount,
            "fromSubAccount": "",
            "nonce": nonce,
        },
        "nonce": nonce,
        "signature": signature,
    }
    return client.private_post_exchange(request)


def _build_exchange(which: str):
    from utils.exchange_client import HyperliquidExchange
    from utils.gcp_secrets import get_secret
    if which == "main":
        # Twee valkuilen, beide gefixt 2026-08-03 (het main-pad had nooit gewerkt):
        #  1. HyperliquidExchange() default naar testnet=True -> alle balansen $0,00.
        #  2. De DEFAULT order-client van de main-wallet signt met de AGENT-key
        #     (HL_PRIVATE_KEY -> 0xe18f…), en HL WEIGERT user-signed actions zoals
        #     sendAsset van een agent-key. De swarm houdt echter ook de MASTER-key van
        #     0x92D4 (HL_VAULT_PRIVATE_KEY, die naar het account zelf derivt en door de
        #     treasury voor Arbitrum wordt gebruikt) — daarmee mag het wel.
        addr = get_secret("HL_VAULT_ADDRESS") or get_secret("HL_WALLET_ADDRESS")
        key = get_secret("HL_VAULT_PRIVATE_KEY")
        if not (addr and key):
            raise RuntimeError(
                "HL_VAULT_ADDRESS/HL_VAULT_PRIVATE_KEY niet gezet — zonder master-key "
                "kan de main-wallet geen sendAsset doen (agent-key wordt geweigerd)")
        return HyperliquidExchange(testnet=False, wallet_address=addr, private_key=key)
    addr = get_secret("HL_THEMATIC_WALLET_ADDRESS")
    key = get_secret("HL_THEMATIC_PRIVATE_KEY")
    if not (addr and key):
        raise RuntimeError("HL_THEMATIC_WALLET_ADDRESS/HL_THEMATIC_PRIVATE_KEY niet gezet")
    return HyperliquidExchange(testnet=False, wallet_address=addr, private_key=key)


def main() -> int:
    ap = argparse.ArgumentParser(description="Fund de Hyperliquid xyz perp-dex")
    ap.add_argument("--amount", type=float, required=True, help="USDC bedrag")
    ap.add_argument("--from-dex", default="spot", help="'spot' (default), '' (main perp), of 'xyz'")
    ap.add_argument("--to-dex", default="xyz", help="doel-dex ('xyz' default)")
    ap.add_argument("--wallet", default="thematic", choices=["thematic", "main"],
                    help="welke wallet (default: thematic self-custody)")
    ap.add_argument("--yes", action="store_true", help="voer echt uit (anders dry-run)")
    args = ap.parse_args()

    ex = _build_exchange(args.wallet)
    client = ex.signing_client
    if client is None:
        print("FOUT: geen signing_client (wallet niet gefund / trading suspended)")
        return 1
    address = getattr(client, "walletAddress", None) or getattr(ex, "wallet_address", None)
    if not address:
        print("FOUT: kon wallet-adres niet bepalen")
        return 1

    src_label = args.from_dex or "main"
    before_src = _source_balance(client, address, args.from_dex)
    before_dst = _dex_value(client, args.to_dex)
    print(f"WALLET: {address} ({args.wallet})")
    print(f"VOOR  : {src_label}=${before_src:.2f}  {args.to_dex}=${before_dst:.2f}")
    print(f"PLAN  : sendAsset ${args.amount:.2f} USDC  {src_label} -> {args.to_dex}")

    if args.amount > before_src + 1e-9:
        print(f"FOUT: bedrag ${args.amount:.2f} > beschikbaar op {src_label} (${before_src:.2f})")
        return 1
    if not args.yes:
        print("DRY-RUN: voeg --yes toe om echt uit te voeren.")
        return 0

    try:
        resp = _send_asset(client, address, args.amount, args.from_dex, args.to_dex)
    except Exception as e:  # noqa: BLE001
        print(f"FOUT tijdens sendAsset: {e}")
        return 1
    print(f"RESPONSE: {resp}")

    time.sleep(3)
    after_dst = _dex_value(client, args.to_dex)
    delta = after_dst - before_dst
    print(f"NA    : {args.to_dex}=${after_dst:.2f}  (+${delta:.2f})")
    if delta >= args.amount * 0.9:
        print(f"OK: {args.to_dex}-dex geslaagd gefund.")
        return 0
    print(f"LET OP: {args.to_dex} steeg ${delta:.2f} (verwacht ~${args.amount:.2f}) — check RESPONSE.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
