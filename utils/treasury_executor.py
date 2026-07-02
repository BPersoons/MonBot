"""
TreasuryExecutor — automated execution of treasury proposals.

State machines (per proposal type, stored in treasury_proposals.json):

DEPLOY_YIELD (idle HL → Aave):
  PENDING                  → human clicks "Goedkeuren" → APPROVED
  APPROVED                 → HL withdrawal to treasury wallet → WITHDRAWING | NEEDS_MANUAL_WITHDRAWAL
  WITHDRAWING              → poll Arbitrum USDC at treasury wallet → BRIDGED
  NEEDS_MANUAL_WITHDRAWAL  → same poll (user withdrew manually) → BRIDGED
  BRIDGED                  → Aave v3 approve + supply → DEPLOYED | FAILED

REBALANCE (Aave → HL, triggered when HL free margin < 25% of total):
  APPROVED (auto)          → Aave withdraw to treasury wallet → REBALANCING
  REBALANCING              → poll tx receipt → BRIDGE_BACK_NEEDED | FAILED
  BRIDGE_BACK_NEEDED       → auto: treasury USDC → vault Arb addr → HL bridge → BRIDGING_TO_HL
  BRIDGING_TO_HL           → poll HL balance → COMPLETED | (keeps polling every 5 cycles)

Treasury wallet: 0x4144e0b52247Ba1Cb06FF1E5fB6F817f330Ce4D3
  Private key: GCP secret HL_TREASURY_PRIVATE_KEY (never in code)
  Fallbacks: HL_VAULT_PRIVATE_KEY → HL_PRIVATE_KEY
"""
from __future__ import annotations

# eth_account must be imported before modules that patch inspect (cytoolz/toolz)
try:
    from eth_account import Account as _EthAccount
    _ETH_ACCOUNT_OK = True
except Exception:
    _EthAccount = None
    _ETH_ACCOUNT_OK = False

import json
import logging
import threading
import time
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("TreasuryExecutor")

# Prevents concurrent advance_proposal calls (dashboard thread + treasury cycle)
_EXECUTION_LOCK = threading.Lock()

# ── Arbitrum constants ────────────────────────────────────────────────────────
# Multiple public RPCs — tried in order until one succeeds
_ARB_RPCS = [
    "https://arbitrum.gateway.tenderly.co",       # public gateway; all methods work from GCP
    "https://api.zan.top/arb-one",                # works for most methods from GCP (eth_call 429)
    "https://arbitrum.drpc.org",                  # may 403 from datacenter IPs
    "https://arbitrum.meowrpc.com",               # may 403 from datacenter IPs
    "https://rpc.ankr.com/arbitrum",              # requires API key for eth_call
    "https://1rpc.io/arb",                        # usage limit may apply
    "https://arb1.arbitrum.io/rpc",               # may 403 from datacenter IPs
]
_ARB_RPC = _ARB_RPCS[0]  # default (overridden by _rpc() fallback logic)
_USDC_ARB      = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Native USDC (Circle)
_AAVE_POOL_ARB = "0x794a61358D6845594F94dc1DB02A252b5b4814aD"  # Aave v3 Pool proxy
_CHAIN_ID      = 42161

_USDC_DECIMALS  = 6
_BRIDGE_TOL     = 0.95   # accept ≥95% of expected (bridge/rounding)
_TX_WAIT_S      = 45     # max seconds to wait for Arbitrum tx receipt
_GAS_APPROVE    = 80_000
_GAS_SUPPLY     = 320_000
_GAS_WITHDRAW   = 220_000
_GAS_TRANSFER   = 80_000
_GAS_BRIDGE     = 300_000
_MAX_SINGLE_TX_USD = 10_000   # hard cap per transaction — requires code change to raise
_MIN_ETH_FOR_GAS = 0.0001    # Arbitrum gas is cheap; 0.0001 ETH covers dozens of TXs

# Dedicated treasury wallet — receives USDC from HL bridge + signs Aave txs
_TREASURY_WALLET = "0x4144e0b52247Ba1Cb06FF1E5fB6F817f330Ce4D3"

# HL bridge contract on Arbitrum (Bridge2) — credits depositor's HL account
# batchedDepositWithPermit((address,uint64,uint64,(uint256,uint256,uint8))[]) = 0xb30b5bce
# Struct field order inside Signature tuple: (r, s, v) — NOT (v, r, s)
_HL_BRIDGE_ARB = "0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7"

# Aave v3 aUSDCn token on Arbitrum (native USDC, not bridged USDC.e)
_AUSDC_ARB = "0x724dc807b04555b71ed48a6896b6F41593b8C637"


# ── ABI encoding (no web3) ────────────────────────────────────────────────────

def _addr(h: str) -> str:
    return h.lower().replace("0x", "").zfill(64)

def _u256(n: int) -> str:
    return f"{n:064x}"

def _encode_approve(spender: str, amount: int) -> str:
    return "0x095ea7b3" + _addr(spender) + _u256(amount)

def _encode_supply(asset: str, amount: int, on_behalf: str) -> str:
    return "0x617ba037" + _addr(asset) + _u256(amount) + _addr(on_behalf) + _u256(0)

def _encode_aave_withdraw(asset: str, amount: int, to: str) -> str:
    # withdraw(address,uint256,address) — Aave v3 Pool
    return "0x69328dec" + _addr(asset) + _u256(amount) + _addr(to)

def _encode_balance_of(owner: str) -> str:
    return "0x70a08231" + _addr(owner)

def _encode_allowance(owner: str, spender: str) -> str:
    return "0xdd62ed3e" + _addr(owner) + _addr(spender)


# ── JSON-RPC helpers ──────────────────────────────────────────────────────────

def _rpc(method: str, params: list) -> object:
    import urllib.error as _urlerr
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    last_exc = None
    for rpc_url in _ARB_RPCS:
        for _attempt in range(3):  # retry up to 3x on 429 rate-limit per RPC
            try:
                req = urllib.request.Request(
                    rpc_url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as r:
                    resp = json.loads(r.read())
                if "error" in resp:
                    raise RuntimeError(f"{method}: {resp['error']}")
                return resp.get("result")
            except _urlerr.HTTPError as e:
                if e.code == 429 and _attempt < 2:
                    time.sleep(2 ** _attempt)   # 1s, then 2s backoff on rate-limit
                    continue
                last_exc = e
                break
            except Exception as e:
                last_exc = e
                break
    raise RuntimeError(f"All Arbitrum RPCs failed for {method}: {last_exc}")


def _verify_is_contract(address: str) -> bool:
    """Return True iff address contains deployed bytecode (not EOA or zero address)."""
    try:
        code = _rpc("eth_getCode", [address, "latest"])
        return bool(code and code not in ("0x", "0x0") and len(code) > 4)
    except Exception:
        return False


def _read_usdc_allowance(owner: str, spender: str) -> int | None:
    """Return USDC allowance in raw units, or None if eth_call unavailable."""
    try:
        result = _rpc("eth_call", [{"to": _USDC_ARB, "data": _encode_allowance(owner, spender)}, "latest"])
        return int(result, 16) if result and result != "0x" else 0
    except Exception:
        return None


_MIN_ETH_FOR_GAS_LEGACY = 0.001  # kept for reference — see module-level _MIN_ETH_FOR_GAS


def _check_eth_gas(wallet_address: str) -> None:
    """Raise if wallet has insufficient ETH for gas. Call before the first TX in any sequence."""
    try:
        result = _rpc("eth_getBalance", [wallet_address, "latest"])
        eth_bal = int(result, 16) / 10**18
        if eth_bal < _MIN_ETH_FOR_GAS:
            raise RuntimeError(
                f"Insufficient ETH for gas: {eth_bal:.6f} ETH at {wallet_address[:12]}… "
                f"(need ≥{_MIN_ETH_FOR_GAS} ETH). Top up before executing."
            )
        logger.info(f"TreasuryExecutor: gas OK — {eth_bal:.5f} ETH at wallet")
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning(f"TreasuryExecutor: gas check failed (RPC error): {e}")


def _simulate_tx(to: str, data: str, from_addr: str = "") -> None:
    """
    Dry-run a TX via eth_call before sending it for real.
    Raises RuntimeError (no funds moved) if the call would revert.
    """
    call = {"to": to, "data": data}
    if from_addr:
        call["from"] = from_addr
    try:
        result = _rpc("eth_call", [call, "latest"])
    except Exception as e:
        # All RPCs failed (403, auth required, timeout) — warn and proceed.
        # The real TX is the final guard; worst case = gas lost but no USDC moved.
        logger.warning(f"TreasuryExecutor: dry-run skipped (RPC unavailable): {e}")
        return
    # 0x08c379a0 = Error(string) revert selector — only fatal if TX would actually revert
    if isinstance(result, str) and result.startswith("0x08c379a0"):
        try:
            hex_data = result[10:]
            length   = int(hex_data[64:128], 16) * 2
            reason   = bytes.fromhex(hex_data[128:128 + length]).decode("utf-8", errors="replace")
        except Exception:
            reason = result[:80]
        raise RuntimeError(f"TX dry-run reverted: {reason}")
    logger.debug(f"TreasuryExecutor: dry-run OK ({to[:12]}…)")


def get_arb_usdc_balance(address: str) -> float:
    """USDC balance at address on Arbitrum, in USD."""
    try:
        result = _rpc("eth_call", [{"to": _USDC_ARB, "data": _encode_balance_of(address)}, "latest"])
        if not result or result == "0x":
            return 0.0
        return int(result, 16) / (10 ** _USDC_DECIMALS)
    except Exception as e:
        logger.warning(f"Arbitrum USDC balance check failed: {e}")
        return 0.0


def _wait_receipt(tx_hash: str, timeout: int = _TX_WAIT_S) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = _rpc("eth_getTransactionReceipt", [tx_hash])
            if r:
                return r
        except Exception:
            pass
        time.sleep(3)
    return None


def _send_tx(to: str, data: str, private_key: str, gas_limit: int) -> str:
    """Sign and submit a legacy tx on Arbitrum. Returns tx hash."""
    Account = _EthAccount

    account = Account.from_key(private_key)
    nonce   = int(_rpc("eth_getTransactionCount", [account.address, "pending"]), 16)
    gas_p   = max(int(_rpc("eth_gasPrice", []), 16), 100_000_000)  # min 0.1 gwei

    tx = {
        "chainId": _CHAIN_ID,
        "nonce":   nonce,
        "gasPrice": gas_p,
        "gas":     gas_limit,
        "to":      to,
        "value":   0,
        "data":    data,
    }
    signed = Account.sign_transaction(tx, private_key)
    try:
        raw = "0x" + signed.raw_transaction.hex()
    except AttributeError:
        raw = "0x" + signed.rawTransaction.hex()
    return _rpc("eth_sendRawTransaction", [raw])


def _estimate_gas(to: str, data: str, from_addr: str, fallback: int,
                  buffer: float = 1.3, cap: int = 1_500_000) -> int:
    """
    Size a gas limit via eth_estimateGas + buffer, clamped to [fallback, cap].
    Falls back to `fallback` when the RPC can't estimate (unsupported/blocked).

    On Arbitrum the limit is only a ceiling — you pay for gasUsed — so
    over-provisioning is free insurance against revert-on-out-of-gas. The
    fixed _GAS_SUPPLY (320k) is sized for Aave's single supply() but is too
    low for a Morpho MetaMorpho deposit, which iterates the supply queue
    across multiple Morpho Blue markets (~500-900k gas). A too-low limit
    reverts with status 0x0 / gasUsed==gasLimit, which eth_call dry-run does
    NOT catch — so estimate dynamically.
    """
    try:
        est = int(_rpc("eth_estimateGas", [{"from": from_addr, "to": to, "data": data}]), 16)
    except Exception as e:
        logger.warning(f"TreasuryExecutor: gas estimate failed ({e}) — using fallback {fallback}")
        return fallback
    return max(fallback, min(int(est * buffer), cap))


# ── HL withdrawal ─────────────────────────────────────────────────────────────

def _create_vault_withdrawal_client():
    """
    Build a CCXT hyperliquid client signed by the vault wallet (not the API wallet).
    HL only accepts withdraw3 actions signed by the account owner — the API wallet
    can trade but cannot withdraw. Returns None if vault key is unavailable.
    """
    import os
    try:
        import ccxt as _ccxt
    except ImportError:
        return None

    # Vault private key resolution: env → GCP SDK → REST
    vault_pk = ""
    for name in ("HL_VAULT_PRIVATE_KEY",):
        vault_pk = os.getenv(name, "")
        if not vault_pk:
            try:
                from utils.gcp_secrets import get_secret
                vault_pk = get_secret(name) or ""
            except Exception:
                pass
        if not vault_pk:
            vault_pk = _fetch_secret_rest(name)
        if vault_pk:
            break

    if not vault_pk:
        logger.debug("TreasuryExecutor: HL_VAULT_PRIVATE_KEY not available — vault client not created")
        return None

    # Vault address (the account that owns the funds)
    vault_addr = os.getenv("HL_VAULT_ADDRESS", "") or os.getenv("HL_WALLET_ADDRESS", "")
    if not vault_addr:
        try:
            from utils.gcp_secrets import get_secret
            vault_addr = get_secret("HL_VAULT_ADDRESS") or get_secret("HL_WALLET_ADDRESS") or ""
        except Exception:
            pass

    if not vault_addr:
        logger.warning("TreasuryExecutor: vault address unknown — cannot create withdrawal client")
        return None

    try:
        client = _ccxt.hyperliquid({
            "walletAddress": vault_addr,
            "privateKey":    vault_pk,
            "apiKey":        vault_addr,
            "secret":        vault_pk,
            "enableRateLimit": True,
            "options":       {"defaultType": "swap"},
        })
        return client
    except Exception as e:
        logger.warning(f"TreasuryExecutor: vault withdrawal client init failed: {e}")
        return None


def _attempt_hl_withdrawal(amount: float, destination: str, exchange_client) -> bool:
    """
    Try HL → Arbitrum withdrawal. Returns True on success.
    Priority:
      1. Vault private key client (HL_VAULT_PRIVATE_KEY) — can sign withdraw3
      2. exchange_client.signing_client — API wallet, may lack withdrawal permission
    """
    # Primary: vault key (required by HL for withdraw3 actions)
    vault_client = _create_vault_withdrawal_client()
    if vault_client:
        try:
            vault_client.withdraw(code="USDC", amount=amount, address=destination, tag=None, params={})
            logger.info(f"TreasuryExecutor: HL withdrawal ${amount:.2f} → {destination[:10]}… (vault key)")
            return True
        except Exception as e:
            logger.warning(f"TreasuryExecutor: vault withdrawal failed ({e})")

    # Fallback: exchange_client API wallet (likely to fail, but try anyway)
    if not exchange_client or not getattr(exchange_client, "signing_client", None):
        return False
    try:
        exchange_client.signing_client.withdraw(
            code="USDC",
            amount=amount,
            address=destination,
            tag=None,
            params={},
        )
        logger.info(f"TreasuryExecutor: HL withdrawal ${amount:.2f} → {destination[:10]}… (exchange client)")
        return True
    except Exception as e:
        logger.warning(f"TreasuryExecutor: CCXT withdraw failed ({e}) — manual withdrawal needed")
        return False


# ── Aave deposit ──────────────────────────────────────────────────────────────

def _deposit_aave(amount_usd: float, private_key: str) -> tuple[str, float, float]:
    """
    Approve + supply USDC into Aave v3 Arbitrum.

    Safety checks (in order):
      1. Amount sanity (> 0, ≤ _MAX_SINGLE_TX_USD)
      2. Aave Pool and USDC are deployed contracts (not EOA/null)
      3. Allowance verified after approve (before supply)
      4. aUSDCn balance verified after supply (confirms on-chain effect)

    Returns (supply_tx_hash, aave_balance_before, aave_balance_after).
    Raises RuntimeError — no funds moved — if any check fails before supply.
    Raises RuntimeError — WITH tx hash in message — if supply confirmed but balance check fails.
    """
    if amount_usd <= 0:
        raise RuntimeError(f"Invalid deposit amount: ${amount_usd}")
    if amount_usd > _MAX_SINGLE_TX_USD:
        raise RuntimeError(
            f"${amount_usd:.0f} exceeds single-tx safety limit ${_MAX_SINGLE_TX_USD}. "
            "Raise _MAX_SINGLE_TX_USD in code if intentional."
        )

    # Layer 1: verify destination contract exists on-chain
    if not _verify_is_contract(_AAVE_POOL_ARB):
        raise RuntimeError(
            f"ABORT: Aave Pool {_AAVE_POOL_ARB} has no bytecode. "
            "Wrong address or wrong chain. No funds moved."
        )
    if not _verify_is_contract(_USDC_ARB):
        raise RuntimeError(
            f"ABORT: USDC {_USDC_ARB} has no bytecode. "
            "Wrong address or wrong chain. No funds moved."
        )

    Account   = _EthAccount
    on_behalf = Account.from_key(private_key).address
    amount    = int(amount_usd * (10 ** _USDC_DECIMALS))

    # Layer 2: gas check — prevents partial execution (approve OK but supply fails due to no ETH)
    _check_eth_gas(on_behalf)

    # Layer 2b: snapshot balance before any TX
    balance_before = get_aave_balance(on_behalf)
    logger.info(f"TreasuryExecutor: Aave balance before deposit: ${balance_before:.2f}")

    # Layer 2c: dry-run the supply call before sending approve (catches most revert scenarios)
    supply_data = _encode_supply(_USDC_ARB, amount, on_behalf)
    try:
        _simulate_tx(_AAVE_POOL_ARB, supply_data, from_addr=on_behalf)
    except RuntimeError as e:
        raise RuntimeError(f"Aave supply dry-run failed — no funds moved: {e}")

    # Approve
    logger.info(f"TreasuryExecutor: approving {amount_usd:.2f} USDC for Aave Pool...")
    approve_hash = _send_tx(_USDC_ARB, _encode_approve(_AAVE_POOL_ARB, amount), private_key, _GAS_APPROVE)
    logger.info(f"TreasuryExecutor: approve tx {approve_hash} — waiting...")
    receipt = _wait_receipt(approve_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"USDC approve failed: {approve_hash}. No funds moved.")

    # Layer 3: verify allowance is actually set (approve TX can succeed but allowance may be wrong)
    allowance = _read_usdc_allowance(on_behalf, _AAVE_POOL_ARB)
    if allowance is None:
        logger.warning("TreasuryExecutor: allowance check skipped (eth_call unavailable) — proceeding to supply")
    elif allowance < amount:
        raise RuntimeError(
            f"Allowance mismatch after approve: on-chain={allowance} expected={amount}. "
            f"Approve TX: {approve_hash}. Aborting supply — no funds moved yet."
        )
    else:
        logger.info(f"TreasuryExecutor: allowance confirmed ({allowance / 10**_USDC_DECIMALS:.2f} USDC)")

    # Brief pause so Tenderly rate-limit window resets before sending supply TX
    time.sleep(3)

    # Supply — revoke approval if this fails to prevent dangling allowance
    logger.info(f"TreasuryExecutor: supplying {amount_usd:.2f} USDC to Aave v3...")
    try:
        supply_hash = _send_tx(_AAVE_POOL_ARB, supply_data, private_key, _GAS_SUPPLY)
        logger.info(f"TreasuryExecutor: supply tx {supply_hash} — waiting...")
        receipt = _wait_receipt(supply_hash)
        if not receipt or receipt.get("status") != "0x1":
            raise RuntimeError(f"Aave supply TX failed: {supply_hash}")
    except Exception as supply_err:
        # Revoke approval so Aave Pool cannot spend USDC in the future
        try:
            logger.warning("TreasuryExecutor: supply failed — revoking Aave approval...")
            revoke_hash = _send_tx(_USDC_ARB, _encode_approve(_AAVE_POOL_ARB, 0), private_key, _GAS_APPROVE)
            logger.info(f"TreasuryExecutor: approval revoked (TX {revoke_hash[:20]}…)")
        except Exception as revoke_err:
            logger.error(f"TreasuryExecutor: approval revoke also failed: {revoke_err}")
        raise supply_err

    # Layer 4: verify aUSDCn balance actually increased on-chain
    balance_after = get_aave_balance(on_behalf)
    expected_min  = balance_before + amount_usd * 0.98  # 2% tolerance for rounding
    logger.info(
        f"TreasuryExecutor: Aave balance after deposit: ${balance_after:.2f} "
        f"(+${balance_after - balance_before:.2f}, expected ≥${amount_usd * 0.98:.2f})"
    )
    if balance_before == 0.0 and balance_after == 0.0:
        # eth_call unavailable — receipt already confirmed supply TX succeeded (status=0x1)
        logger.warning(
            f"TreasuryExecutor: Aave balance unverifiable (eth_call blocked) — "
            f"supply TX {supply_hash} receipt confirmed; assuming deposit succeeded"
        )
    elif balance_after < expected_min:
        raise RuntimeError(
            f"POST-DEPOSIT BALANCE CHECK FAILED: "
            f"before=${balance_before:.2f} after=${balance_after:.2f} deposited=${amount_usd:.2f}. "
            f"Supply TX {supply_hash} may have failed silently. INVESTIGATE IMMEDIATELY."
        )

    return supply_hash, balance_before, balance_after


# ── ERC-4626 deposit (Morpho MetaMorpho vaults) ──────────────────────────────

def _encode_erc4626_deposit(assets: int, receiver: str) -> str:
    # deposit(uint256 assets, address receiver) — ERC-4626 standard
    return "0x6e553f65" + _u256(assets) + _addr(receiver)


def _deposit_erc4626(amount_usd: float, vault_address: str, private_key: str) -> tuple[str, float, float]:
    """
    Approve + deposit USDC into an ERC-4626 vault (e.g. Morpho MetaMorpho).
    Returns (deposit_tx_hash, usdc_balance_before, usdc_balance_after).
    """
    if amount_usd <= 0 or amount_usd > _MAX_SINGLE_TX_USD:
        raise RuntimeError(f"Invalid/unsafe deposit amount: ${amount_usd}")

    # Verify vault address is a deployed contract before touching funds
    if not _verify_is_contract(vault_address):
        raise RuntimeError(
            f"ABORT: ERC-4626 vault {vault_address} has no bytecode. "
            "Wrong address? No funds moved."
        )

    Account   = _EthAccount
    on_behalf = Account.from_key(private_key).address
    amount    = int(amount_usd * (10 ** _USDC_DECIMALS))

    _check_eth_gas(on_behalf)
    usdc_before = get_arb_usdc_balance(on_behalf)

    # Dry-run deposit call before touching funds
    deposit_data = _encode_erc4626_deposit(amount, on_behalf)
    try:
        _simulate_tx(vault_address, deposit_data, from_addr=on_behalf)
    except RuntimeError as e:
        raise RuntimeError(f"ERC-4626 deposit dry-run failed — no funds moved: {e}")

    logger.info(f"TreasuryExecutor: approving {amount_usd:.2f} USDC for vault {vault_address[:10]}…")
    approve_hash = _send_tx(_USDC_ARB, _encode_approve(vault_address, amount), private_key, _GAS_APPROVE)
    receipt = _wait_receipt(approve_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"USDC approve failed: {approve_hash}. No funds moved.")

    allowance = _read_usdc_allowance(on_behalf, vault_address)
    if allowance is None:
        logger.warning("TreasuryExecutor: allowance check skipped (eth_call unavailable) — proceeding to deposit")
    elif allowance < amount:
        raise RuntimeError(f"Allowance mismatch after approve: {allowance} < {amount}. Aborting.")

    logger.info(f"TreasuryExecutor: depositing {amount_usd:.2f} USDC into ERC-4626 vault…")
    try:
        # Estimate gas now that allowance is set — Morpho MetaMorpho deposits
        # iterate the supply queue and exceed the fixed _GAS_SUPPLY (320k),
        # reverting out-of-gas (the prior BBQUSDC failures: gasUsed==320k).
        deposit_gas  = _estimate_gas(vault_address, deposit_data, on_behalf, _GAS_SUPPLY)
        logger.info(f"TreasuryExecutor: ERC-4626 deposit gas limit = {deposit_gas}")
        deposit_hash = _send_tx(vault_address, deposit_data, private_key, deposit_gas)
        receipt = _wait_receipt(deposit_hash)
        if not receipt or receipt.get("status") != "0x1":
            raise RuntimeError(f"ERC-4626 deposit TX failed: {deposit_hash}")
    except Exception as dep_err:
        try:
            logger.warning("TreasuryExecutor: deposit failed — revoking vault approval...")
            _send_tx(_USDC_ARB, _encode_approve(vault_address, 0), private_key, _GAS_APPROVE)
        except Exception as revoke_err:
            logger.error(f"TreasuryExecutor: approval revoke failed: {revoke_err}")
        raise dep_err

    usdc_after = get_arb_usdc_balance(on_behalf)
    if usdc_before == 0.0 and usdc_after == 0.0:
        # eth_call unavailable — receipt already confirmed deposit TX succeeded (status=0x1)
        logger.warning(
            f"TreasuryExecutor: wallet USDC balance unverifiable (eth_call blocked) — "
            f"deposit TX {deposit_hash} receipt confirmed; assuming deposit succeeded"
        )
    elif usdc_after > usdc_before - amount_usd * 0.98:
        raise RuntimeError(
            f"POST-DEPOSIT CHECK FAILED: wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f} "
            f"(expected decrease of ≈${amount_usd:.2f}). TX {deposit_hash}. INVESTIGATE."
        )
    else:
        logger.info(f"TreasuryExecutor: vault deposit confirmed — wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f}")
    return deposit_hash, usdc_before, usdc_after


# ── Compound v3 deposit ────────────────────────────────────────────────────────

def _encode_compound_supply(asset: str, amount: int) -> str:
    # supply(address asset, uint amount) — Compound v3 Comet
    return "0xf2b9fdb8" + _addr(asset) + _u256(amount)


# ── ERC-20 transfer ────────────────────────────────────────────────────────────

def _encode_erc20_transfer(to: str, amount: int) -> str:
    # transfer(address to, uint256 amount) — standard ERC-20
    return "0xa9059cbb" + _addr(to) + _u256(amount)


# ── HL bridge (Arbitrum → HL) ──────────────────────────────────────────────────

def _bridge_usdc_to_hl(amount_usd: float, treasury_pk: str, vault_pk: str) -> str:
    """
    Move USDC from treasury wallet to the HL trading vault via Bridge2.

    Step 1: treasury wallet ERC-20 transfers USDC to vault Arb address (if treasury has balance).
            Skipped if USDC is already on vault Arb (e.g. from a prior failed attempt).
    Step 2: vault wallet calls batchedDepositWithPermit (selector 0xb30b5bce) using EIP-2612
            permit — no separate approve TX needed. HL credits vault_arb_address == HL_VAULT_ADDRESS.

    Bridges the FULL vault Arb balance so prior stuck funds are also recovered.
    Returns the bridge deposit TX hash.
    """
    if amount_usd <= 0 or amount_usd > _MAX_SINGLE_TX_USD:
        raise RuntimeError(f"Invalid/unsafe bridge amount: ${amount_usd}")

    Account   = _EthAccount
    treasury  = Account.from_key(treasury_pk).address
    vault_arb = Account.from_key(vault_pk).address

    if treasury.lower() != _TREASURY_WALLET.lower():
        raise RuntimeError(
            f"ABORT: treasury_pk address {treasury} != expected {_TREASURY_WALLET}. Wrong key?"
        )

    if not _verify_is_contract(_HL_BRIDGE_ARB):
        raise RuntimeError(f"ABORT: HL bridge {_HL_BRIDGE_ARB} has no bytecode.")

    _check_eth_gas(vault_arb)  # vault sends the bridge TX

    amount_raw = int(amount_usd * (10 ** _USDC_DECIMALS))

    # ── Step 1: transfer USDC treasury → vault Arb address ────────────────────
    treasury_usdc = get_arb_usdc_balance(treasury)
    if treasury_usdc >= amount_usd * 0.99:
        _check_eth_gas(treasury)
        logger.info(
            f"TreasuryExecutor: bridge step 1 — transferring {amount_usd:.2f} USDC "
            f"treasury → vault ({vault_arb[:10]}…)"
        )
        transfer_hash = _send_tx(
            _USDC_ARB, _encode_erc20_transfer(vault_arb, amount_raw), treasury_pk, _GAS_TRANSFER
        )
        receipt = _wait_receipt(transfer_hash)
        if not receipt or receipt.get("status") != "0x1":
            raise RuntimeError(f"USDC transfer to vault Arb address failed: {transfer_hash}")
        logger.info(f"TreasuryExecutor: step 1 confirmed ({transfer_hash[:20]}…)")
    else:
        logger.info(
            f"TreasuryExecutor: bridge step 1 skipped — treasury has ${treasury_usdc:.2f} "
            f"(USDC already on vault Arb from prior attempt)"
        )

    # ── Step 2: vault calls batchedDepositWithPermit via EIP-2612 permit ──────
    vault_usdc = get_arb_usdc_balance(vault_arb)
    if vault_usdc < 5.0:
        raise RuntimeError(
            f"Vault Arb USDC ${vault_usdc:.2f} < $5 bridge minimum — cannot bridge."
        )

    bridge_raw = int(vault_usdc * (10 ** _USDC_DECIMALS))
    deadline   = int(time.time()) + 3600  # 1 hour

    # Get USDC EIP-2612 nonce for vault Arb address (nonces(address) = 0x7ecebe00)
    nonce_raw    = _rpc("eth_call", [{"to": _USDC_ARB, "data": "0x7ecebe00" + _addr(vault_arb)}, "latest"])
    permit_nonce = int(nonce_raw, 16) if nonce_raw and nonce_raw != "0x" else 0

    # Sign permit: vault_arb authorizes bridge to pull bridge_raw USDC (no approve TX needed)
    signed = Account.sign_typed_data(vault_pk, full_message={
        "types": {
            "EIP712Domain": [
                {"name": "name",             "type": "string"},
                {"name": "version",          "type": "string"},
                {"name": "chainId",          "type": "uint256"},
                {"name": "verifyingContract","type": "address"},
            ],
            "Permit": [
                {"name": "owner",    "type": "address"},
                {"name": "spender",  "type": "address"},
                {"name": "value",    "type": "uint256"},
                {"name": "nonce",    "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "Permit",
        "domain": {
            "name":             "USD Coin",
            "version":          "2",
            "chainId":          _CHAIN_ID,
            "verifyingContract": _USDC_ARB,
        },
        "message": {
            "owner":    vault_arb,
            "spender":  _HL_BRIDGE_ARB,
            "value":    bridge_raw,
            "nonce":    permit_nonce,
            "deadline": deadline,
        },
    })

    # Encode batchedDepositWithPermit((address,uint64,uint64,(uint256,uint256,uint8))[])
    # Selector 0xb30b5bce — Signature tuple is (r, s, v), NOT (v, r, s)
    deposit_data = (
        "0xb30b5bce"
        + _u256(32)          # offset to dynamic array (32 bytes from params start)
        + _u256(1)           # array length = 1
        + _addr(vault_arb)   # DepositWithPermit.user
        + _u256(bridge_raw)  # DepositWithPermit.usd  (uint64, padded to 256)
        + _u256(deadline)    # DepositWithPermit.deadline (uint64, padded)
        + _u256(signed.r)    # Signature.r (uint256)
        + _u256(signed.s)    # Signature.s (uint256)
        + _u256(signed.v)    # Signature.v (uint8, padded)
    )

    logger.info(
        f"TreasuryExecutor: bridge step 2 — batchedDepositWithPermit "
        f"${vault_usdc:.2f} USDC → HL vault ({vault_arb[:10]}…)…"
    )
    deposit_hash = _send_tx(_HL_BRIDGE_ARB, deposit_data, vault_pk, _GAS_BRIDGE)
    receipt      = _wait_receipt(deposit_hash, timeout=90)
    if not receipt or receipt.get("status") != "0x1":
        gas_used = receipt.get("gasUsed", "?") if receipt else "timeout"
        raise RuntimeError(
            f"Bridge batchedDepositWithPermit TX failed (gasUsed={gas_used}): {deposit_hash}"
        )

    logger.info(
        f"TreasuryExecutor: bridge TX confirmed ({deposit_hash[:20]}…) — "
        f"${vault_usdc:.2f} USDC en route to HL vault"
    )
    return deposit_hash


def get_vault_private_key() -> str:
    """Returns the HL vault private key (HL_VAULT_PRIVATE_KEY or HL_PRIVATE_KEY fallback)."""
    import os
    for secret_name in ("HL_VAULT_PRIVATE_KEY", "HL_PRIVATE_KEY"):
        val = os.getenv(secret_name, "")
        if not val:
            try:
                from utils.gcp_secrets import get_secret
                val = get_secret(secret_name) or ""
            except Exception:
                pass
        if not val:
            val = _fetch_secret_rest(secret_name)
        if val:
            return val
    return ""


def _deposit_compound_v3(amount_usd: float, comet_address: str, private_key: str) -> tuple[str, float, float]:
    """Approve + supply USDC into Compound v3 Comet. Returns (tx_hash, usdc_before, usdc_after)."""
    if amount_usd <= 0 or amount_usd > _MAX_SINGLE_TX_USD:
        raise RuntimeError(f"Invalid/unsafe deposit amount: ${amount_usd}")

    if not _verify_is_contract(comet_address):
        raise RuntimeError(
            f"ABORT: Compound v3 Comet {comet_address} has no bytecode. "
            "Wrong address? No funds moved."
        )

    Account   = _EthAccount
    on_behalf = Account.from_key(private_key).address
    amount    = int(amount_usd * (10 ** _USDC_DECIMALS))

    _check_eth_gas(on_behalf)
    usdc_before = get_arb_usdc_balance(on_behalf)

    # Dry-run: simulate the supply call before touching the chain
    supply_data = _encode_compound_supply(_USDC_ARB, amount)
    _simulate_tx(comet_address, supply_data, from_addr=on_behalf)

    logger.info(f"TreasuryExecutor: approving {amount_usd:.2f} USDC for Compound v3 {comet_address[:10]}…")
    approve_hash = _send_tx(_USDC_ARB, _encode_approve(comet_address, amount), private_key, _GAS_APPROVE)
    receipt = _wait_receipt(approve_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"USDC approve failed: {approve_hash}. No funds moved.")

    allowance = _read_usdc_allowance(on_behalf, comet_address)
    if allowance is None:
        # eth_call blocked — can't verify allowance. Proceed (approve receipt already
        # confirmed); the post-supply balance check is the backstop. Avoids TypeError on
        # `None < amount`, matching the Aave/ERC-4626 paths.
        logger.warning("TreasuryExecutor: Compound allowance read unavailable — proceeding to supply")
    elif allowance < amount:
        raise RuntimeError(f"Allowance mismatch after approve: {allowance} < {amount}. Aborting.")

    logger.info(f"TreasuryExecutor: supplying {amount_usd:.2f} USDC to Compound v3…")
    try:
        supply_hash = _send_tx(comet_address, supply_data, private_key, _GAS_SUPPLY)
        receipt = _wait_receipt(supply_hash)
        if not receipt or receipt.get("status") != "0x1":
            raise RuntimeError(f"Compound v3 supply TX failed: {supply_hash}")
    except Exception:
        # Revoke leftover allowance so funds can't be swept later
        try:
            _send_tx(_USDC_ARB, _encode_approve(comet_address, 0), private_key, _GAS_APPROVE)
            logger.warning("TreasuryExecutor: Compound v3 supply failed — approve revoked.")
        except Exception as revoke_err:
            logger.error(f"TreasuryExecutor: approve revoke also failed: {revoke_err}")
        raise

    usdc_after = get_arb_usdc_balance(on_behalf)
    if usdc_after > usdc_before - amount_usd * 0.98:
        raise RuntimeError(
            f"POST-DEPOSIT CHECK FAILED: wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f}. "
            f"TX {supply_hash}. INVESTIGATE."
        )
    logger.info(f"TreasuryExecutor: Compound deposit confirmed — wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f}")

    return supply_hash, usdc_before, usdc_after


# ── Aave balance + withdrawal ─────────────────────────────────────────────────

def get_aave_balance(wallet_address: str) -> float:
    """aUSDCn balance = deposited USDC (1:1 + accrued interest) on Arbitrum."""
    try:
        result = _rpc("eth_call", [{"to": _AUSDC_ARB, "data": _encode_balance_of(wallet_address)}, "latest"])
        if not result or result == "0x":
            return 0.0
        return int(result, 16) / (10 ** _USDC_DECIMALS)
    except Exception as e:
        logger.warning(f"TreasuryExecutor: Aave balance check failed: {e}")
        return 0.0


def get_erc4626_balance(vault_address: str, wallet_address: str) -> float:
    """USDC value of ERC-4626 vault shares held by wallet_address."""
    try:
        raw_shares = _rpc("eth_call", [
            {"to": vault_address, "data": "0x70a08231" + _addr(wallet_address)},
            "latest",
        ])
        if not raw_shares or raw_shares == "0x":
            return 0.0
        shares = int(raw_shares, 16)
        if shares == 0:
            return 0.0
        # convertToAssets(uint256 shares) → assets in USDC (6 decimals)
        raw_assets = _rpc("eth_call", [
            {"to": vault_address, "data": "0x07a2d13a" + _u256(shares)},
            "latest",
        ])
        if not raw_assets or raw_assets == "0x":
            return 0.0
        return int(raw_assets, 16) / (10 ** _USDC_DECIMALS)
    except Exception as e:
        logger.debug(f"TreasuryExecutor: ERC-4626 balance failed ({vault_address[:10]}…): {e}")
        return 0.0


def get_total_yield_balance(wallet_address: str) -> float:
    """Sum of all deployed yield balances across all automated protocols."""
    try:
        with open("config/treasury_protocols.json") as f:
            protocols = json.load(f).get("protocols", [])
    except Exception:
        protocols = []

    total = 0.0
    for cfg in protocols:
        if not cfg.get("automated"):
            continue
        ptype = cfg.get("type", "")
        try:
            if ptype == "aave_v3":
                total += get_aave_balance(wallet_address)
            elif ptype == "erc4626":
                vault = cfg.get("vault_address")
                if vault:
                    total += get_erc4626_balance(vault, wallet_address)
        except Exception as e:
            logger.debug(f"TreasuryExecutor: yield balance failed for {cfg.get('id')}: {e}")
    return round(total, 2)


def _encode_erc4626_redeem(shares: int, receiver: str, owner: str) -> str:
    # redeem(uint256 shares, address receiver, address owner) — ERC-4626 standard
    return "0xba087652" + _u256(shares) + _addr(receiver) + _addr(owner)


def _encode_erc4626_withdraw(assets: int, receiver: str, owner: str) -> str:
    # withdraw(uint256 assets, address receiver, address owner) — ERC-4626 standard
    return "0xb460af94" + _u256(assets) + _addr(receiver) + _addr(owner)


def _erc4626_convert_to_shares(vault_address: str, assets_atoms: int) -> int:
    """Call convertToShares(uint256) on an ERC-4626 vault. Returns 0 on failure."""
    # convertToShares(uint256 assets) → uint256 — ERC-4626 standard, selector 0xc6e6f592
    data = "0xc6e6f592" + _u256(assets_atoms)
    try:
        result = _rpc("eth_call", [{"to": vault_address, "data": data}, "latest"])
        if result and result != "0x":
            return int(result, 16)
    except Exception as e:
        logger.warning(f"TreasuryExecutor: convertToShares failed for {vault_address[:10]}…: {e}")
    return 0


def withdraw_erc4626_to_wallet(vault_address: str, private_key: str) -> tuple[str, float, float]:
    """Redeem all ERC-4626 vault shares to the treasury wallet. Returns (tx_hash, usdc_before, usdc_after)."""
    Account    = _EthAccount
    to_address = Account.from_key(private_key).address

    if to_address.lower() != _TREASURY_WALLET.lower():
        raise RuntimeError(
            f"ABORT: destination {to_address} != treasury wallet. Wrong key? No funds moved."
        )

    if not _verify_is_contract(vault_address):
        raise RuntimeError(f"ABORT: ERC-4626 vault {vault_address} has no bytecode. No funds moved.")

    _check_eth_gas(to_address)

    raw_shares = _rpc("eth_call", [
        {"to": vault_address, "data": "0x70a08231" + _addr(to_address)},
        "latest",
    ])
    if not raw_shares or raw_shares == "0x":
        raise RuntimeError(f"No shares found in vault {vault_address[:10]}…")
    shares = int(raw_shares, 16)
    if shares == 0:
        raise RuntimeError(f"Zero shares in vault {vault_address[:10]}… — nothing to redeem")

    usdc_before = get_arb_usdc_balance(to_address)
    redeem_data = _encode_erc4626_redeem(shares, to_address, to_address)

    _simulate_tx(vault_address, redeem_data, from_addr=to_address)

    logger.info(f"TreasuryExecutor: redeeming {shares} shares from vault {vault_address[:10]}…")
    tx_hash = _send_tx(vault_address, redeem_data, private_key, _GAS_WITHDRAW)
    receipt = _wait_receipt(tx_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"ERC-4626 redeem TX failed: {tx_hash}")

    usdc_after = get_arb_usdc_balance(to_address)
    if usdc_after <= usdc_before:
        raise RuntimeError(
            f"POST-REDEEM CHECK FAILED: wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f}. "
            f"TX {tx_hash}. INVESTIGATE."
        )
    logger.info(f"TreasuryExecutor: ERC-4626 withdrawal confirmed — ${usdc_before:.2f} → ${usdc_after:.2f}")
    return tx_hash, usdc_before, usdc_after


def withdraw_erc4626_partial(vault_address: str, amount_usd: float, private_key: str) -> tuple[str, float, float]:
    """Withdraw a specific USD amount from an ERC-4626 vault to the treasury wallet.

    Uses ERC-4626 withdraw(assets, receiver, owner) so the contract converts to shares
    internally — no need to calculate share ratios locally.
    Returns (tx_hash, usdc_before, usdc_after).
    """
    Account    = _EthAccount
    to_address = Account.from_key(private_key).address

    if to_address.lower() != _TREASURY_WALLET.lower():
        raise RuntimeError(
            f"ABORT: destination {to_address} != treasury wallet. Wrong key? No funds moved."
        )
    if amount_usd <= 0 or amount_usd > _MAX_SINGLE_TX_USD:
        raise RuntimeError(f"Invalid partial withdrawal amount: ${amount_usd:.2f}")
    if not _verify_is_contract(vault_address):
        raise RuntimeError(f"ABORT: ERC-4626 vault {vault_address} has no bytecode. No funds moved.")

    _check_eth_gas(to_address)

    assets = int(amount_usd * (10 ** _USDC_DECIMALS))

    # Probe whether withdraw(assets) is supported. Some vaults (e.g. Gains Network gUSDC)
    # implement ERC-4626 partially and revert withdraw() with a custom error that returns
    # 0x from eth_call — not caught by _simulate_tx's Error(string) check. Fall back to
    # redeem(shares) via convertToShares() when the probe returns empty.
    # When eth_call is blocked (403), default to redeem path — convertToShares will return 0
    # if also blocked, giving a clean RuntimeError instead of blindly sending a failing TX.
    use_redeem_fallback = False
    try:
        probe_data = _encode_erc4626_withdraw(assets, to_address, to_address)
        probe_result = _rpc("eth_call", [{"to": vault_address, "from": to_address, "data": probe_data}, "latest"])
        if not probe_result or probe_result == "0x":
            use_redeem_fallback = True
            logger.info(f"TreasuryExecutor: withdraw(assets) returned 0x for {vault_address[:10]}… — switching to redeem(shares)")
    except Exception as _probe_err:
        use_redeem_fallback = True  # RPC blocked — can't validate; redeem path fails cleanly if eth_call still unavailable
        logger.warning(f"TreasuryExecutor: withdraw probe unavailable, trying redeem fallback: {_probe_err}")

    if use_redeem_fallback:
        shares = _erc4626_convert_to_shares(vault_address, assets)
        if shares <= 0:
            raise RuntimeError(f"Cannot partial-redeem: convertToShares returned 0 for ${amount_usd:.2f} at {vault_address[:10]}…")
        tx_data = _encode_erc4626_redeem(shares, to_address, to_address)
        logger.info(f"TreasuryExecutor: redeem-based partial withdraw — {shares} shares ≈ ${amount_usd:.2f}")
    else:
        withdraw_data = _encode_erc4626_withdraw(assets, to_address, to_address)
        _simulate_tx(vault_address, withdraw_data, from_addr=to_address)
        tx_data = withdraw_data

    usdc_before = get_arb_usdc_balance(to_address)
    logger.info(f"TreasuryExecutor: partial ERC-4626 withdrawal ${amount_usd:.2f} from {vault_address[:10]}…")
    tx_hash = _send_tx(vault_address, tx_data, private_key, _GAS_WITHDRAW)
    receipt = _wait_receipt(tx_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"ERC-4626 partial withdraw TX failed: {tx_hash}")

    usdc_after = get_arb_usdc_balance(to_address)
    if usdc_after < usdc_before + amount_usd * 0.95:
        raise RuntimeError(
            f"POST-PARTIAL-WITHDRAW CHECK FAILED: expected +${amount_usd:.2f}, "
            f"got +${usdc_after - usdc_before:.2f}. TX {tx_hash}. INVESTIGATE."
        )
    logger.info(f"TreasuryExecutor: partial ERC-4626 withdrawal confirmed — ${usdc_before:.2f} → ${usdc_after:.2f}")
    return tx_hash, usdc_before, usdc_after


def withdraw_aave_to_wallet(amount_usd: float, private_key: str) -> str:
    """Withdraw USDC from Aave v3 Arbitrum to the treasury wallet. Returns tx hash."""
    Account    = _EthAccount
    to_address = Account.from_key(private_key).address

    # Destination assertion: only ever withdraw to the known treasury wallet
    if to_address.lower() != _TREASURY_WALLET.lower():
        raise RuntimeError(
            f"ABORT: withdrawal destination {to_address} != treasury wallet {_TREASURY_WALLET}. "
            "Wrong private key? No funds moved."
        )

    _check_eth_gas(to_address)

    amount          = int(amount_usd * (10 ** _USDC_DECIMALS))
    withdraw_data   = _encode_aave_withdraw(_USDC_ARB, amount, to_address)

    # Dry-run the withdrawal before broadcasting
    _simulate_tx(_AAVE_POOL_ARB, withdraw_data, from_addr=to_address)

    usdc_before = get_arb_usdc_balance(to_address)
    logger.info(f"TreasuryExecutor: withdrawing {amount_usd:.2f} USDC from Aave → {to_address[:10]}… (wallet before: ${usdc_before:.2f})")

    tx_hash = _send_tx(_AAVE_POOL_ARB, withdraw_data, private_key, _GAS_WITHDRAW)
    receipt = _wait_receipt(tx_hash)
    if not receipt or receipt.get("status") != "0x1":
        raise RuntimeError(f"Aave withdraw tx failed: {tx_hash}")

    usdc_after = get_arb_usdc_balance(to_address)
    if usdc_after < usdc_before + amount_usd * 0.95:
        raise RuntimeError(
            f"POST-WITHDRAWAL CHECK FAILED: wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f} "
            f"(expected ≥${usdc_before + amount_usd * 0.95:.2f}). TX {tx_hash}. INVESTIGATE."
        )
    logger.info(f"TreasuryExecutor: Aave withdrawal confirmed — wallet USDC ${usdc_before:.2f} → ${usdc_after:.2f}")
    return tx_hash


# ── State machine ─────────────────────────────────────────────────────────────

def advance_proposal(
    proposal: dict,
    exchange_client=None,
    private_key: str = "",
    wallet_address: str = "",
    telegram_fn=None,
) -> dict:
    """Advance a proposal one step. Mutates and returns the proposal."""
    with _EXECUTION_LOCK:
        return _advance_proposal_inner(proposal, exchange_client, private_key, wallet_address, telegram_fn)


def _advance_proposal_inner(
    proposal: dict,
    exchange_client=None,
    private_key: str = "",
    wallet_address: str = "",
    telegram_fn=None,
) -> dict:
    """Inner implementation — called under _EXECUTION_LOCK."""
    status = proposal.get("status", "")
    amount = float(proposal.get("amount_usd", 0))
    now    = datetime.now(timezone.utc).isoformat()

    def _notify(msg: str):
        logger.info(f"TreasuryExecutor: {msg[:120]}")
        if telegram_fn:
            try:
                telegram_fn(msg)
            except Exception:
                pass

    # ── APPROVED → branch on proposal type ───────────────────────────────────
    if status == "APPROVED":

        # ── FUND_TRADING: record baseline HL balance, switch to MONITORING ────
        # Must be first — later branches fall through to DEPLOY_YIELD logic
        if proposal.get("type") == "FUND_TRADING":
            baseline_hl = 0.0
            if exchange_client:
                try:
                    baseline_hl = exchange_client.get_balance()
                except Exception:
                    pass
            proposal.update({
                "status":      "MONITORING",
                "hl_baseline": baseline_hl,
                "updated_at":  now,
            })
            _notify(
                f"📋 *Treasury: HL top-up bewaking gestart*\n"
                f"Wacht op bridge van ${amount:.0f} USDC naar HL.\n"
                f"Huidige HL balans: ${baseline_hl:.2f}\n"
                f"Zodra de balans stijgt → voorstel wordt automatisch afgesloten."
            )
            return proposal

        # ── YIELD_SWITCH: withdraw from old protocol, deposit into new ──────────
        if proposal.get("type") == "YIELD_SWITCH":
            if not private_key:
                proposal.update({"status": "FAILED", "error": "No private key for yield switch", "updated_at": now})
                return proposal
            from_type = proposal.get("from_protocol_type", "aave_v3")
            from_cfg  = proposal.get("from_protocol_config") or {}
            from_label = proposal.get("from_protocol", "?")
            try:
                if from_type == "erc4626":
                    vault_addr = from_cfg.get("vault_address")
                    if not vault_addr:
                        raise RuntimeError(f"vault_address missing in from_protocol_config for {from_label}")
                    switch_amount = proposal.get("switch_amount_usd")
                    if switch_amount and float(switch_amount) < amount * 0.99:
                        # Partial diversification — withdraw only the specified amount
                        tx_hash, _, _ = withdraw_erc4626_partial(vault_addr, float(switch_amount), private_key)
                    else:
                        tx_hash, _, _ = withdraw_erc4626_to_wallet(vault_addr, private_key)
                else:
                    # aave_v3 — read live balance so we withdraw the exact accrued amount
                    Account    = _EthAccount
                    to_address = Account.from_key(private_key).address
                    live_bal   = get_aave_balance(to_address)
                    if live_bal < 1.0:
                        raise RuntimeError(f"Aave balance ${live_bal:.2f} too low to switch")
                    tx_hash = withdraw_aave_to_wallet(round(live_bal, 2), private_key)

                proposal.update({
                    "status":               "SWITCHING",
                    "withdraw_tx":          tx_hash,
                    "withdraw_initiated_at": now,
                    "updated_at":           now,
                })
                _notify(
                    f"🔄 *Treasury: Yield switch gestart*\n"
                    f"Uitgetreden uit {from_label}\n"
                    f"TX: `{tx_hash[:20]}…` — wachten op USDC in treasury wallet…"
                )
            except Exception as e:
                proposal.update({"status": "FAILED", "error": str(e), "updated_at": now})
                _notify(f"❌ *Treasury: Yield switch mislukt (withdraw)*\n`{e}`")
            return proposal

        # ── REBALANCE: withdraw from Aave back to treasury wallet ─────────────
        if proposal.get("type") == "REBALANCE":
            if not private_key:
                proposal.update({"status": "FAILED", "error": "No private key for Aave withdrawal", "updated_at": now})
                return proposal
            try:
                tx_hash = withdraw_aave_to_wallet(amount, private_key)
                proposal.update({"status": "REBALANCING", "aave_withdraw_tx": tx_hash, "updated_at": now})
                _notify(
                    f"💸 *Treasury: Aave withdrawal gestart*\n"
                    f"${amount:.0f} USDC → treasury wallet\nTX: `{tx_hash[:20]}…` — bevestiging afwachten…"
                )
            except Exception as e:
                proposal.update({"status": "FAILED", "error": str(e), "updated_at": now})
                _notify(f"❌ *Treasury: Aave withdrawal mislukt*\n`{e}`")
            return proposal

        # ── DEPLOY_YIELD: USDC already on treasury wallet (direct deposit) ────
        # Skip HL withdrawal — USDC arrived directly, not via bridge
        if proposal.get("source") == "treasury_wallet":
            balance = get_arb_usdc_balance(_TREASURY_WALLET)
            if balance >= amount * _BRIDGE_TOL:
                proposal.update({
                    "status":           "BRIDGED",
                    "arb_usdc_balance": round(balance, 2),
                    "bridged_at":       now,
                })
                _notify(
                    f"✅ *Treasury: USDC bevestigd op treasury wallet*\n"
                    f"${balance:.2f} USDC aanwezig — storten in Aave v3 Arbitrum…"
                )
            else:
                logger.info(
                    f"TreasuryExecutor: treasury wallet USDC ${balance:.2f} < ${amount * _BRIDGE_TOL:.2f} needed — waiting"
                )
            return proposal

        # ── DEPLOY_YIELD: HL → Arbitrum withdrawal ────────────────────────────
        dest = _TREASURY_WALLET  # always withdraw to dedicated treasury wallet
        if _attempt_hl_withdrawal(amount, dest, exchange_client):
            proposal.update({"status": "WITHDRAWING", "withdrawal_destination": dest, "withdrawal_initiated_at": now})
            _notify(
                f"💸 *Treasury: Withdrawal gestart*\n"
                f"${amount:.0f} USDC → treasury wallet (`{dest[:10]}…`)\n"
                f"Bridge ~15 min. Automatische controle loopt."
            )
        else:
            proposal.update({"status": "NEEDS_MANUAL_WITHDRAWAL", "withdrawal_destination": dest, "updated_at": now})
            _notify(
                f"💰 *Treasury: Handmatige withdrawal nodig*\n\n"
                f"Automatische bridge kon niet starten. Voer handmatig uit:\n"
                f"1. app.hyperliquid.xyz → Transfer → Withdraw to Arbitrum\n"
                f"2. Bedrag: ${amount:.0f} USDC\n"
                f"3. Bestemming: `{dest}`\n\n"
                f"Zodra USDC aankomt → Aave deposit automatisch."
            )
        return proposal

    # ── WITHDRAWING / NEEDS_MANUAL_WITHDRAWAL → poll Arbitrum ─────────────────
    if status in ("WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL"):
        dest    = proposal.get("withdrawal_destination", wallet_address)
        balance = get_arb_usdc_balance(dest)
        needed  = amount * _BRIDGE_TOL
        logger.info(f"TreasuryExecutor: Arbitrum USDC @ {dest[:10]}… = ${balance:.2f} (need ≥${needed:.2f})")
        if balance >= needed:
            proposal.update({
                "status":           "BRIDGED",
                "arb_usdc_balance": round(balance, 2),
                "bridged_at":       now,
            })
            _notify(
                f"✅ *Treasury: USDC gearriveerd op Arbitrum*\n"
                f"${balance:.2f} USDC op `{dest[:10]}…`\n"
                f"Storten in {proposal.get('protocol', 'Aave v3')}…"
            )
        return proposal

    # ── BRIDGED → protocol deposit (Aave / ERC-4626 / Compound v3) ───────────
    if status == "BRIDGED":
        if not private_key:
            proposal.update({"status": "FAILED", "error": "No private key for deposit", "updated_at": now})
            _notify("❌ *Treasury: Deposit mislukt* — geen private key geconfigureerd")
            return proposal
        try:
            actual_usdc = get_arb_usdc_balance(_TREASURY_WALLET)
            # Cap at proposal amount + 5% to handle bridge rounding without
            # accidentally sweeping funds reserved for a concurrent FUND_TRADING.
            if actual_usdc >= amount * _BRIDGE_TOL:
                deploy_amount = min(actual_usdc, amount * 1.05)
            else:
                deploy_amount = amount

            protocol_type  = proposal.get("protocol_type", "aave_v3")
            protocol_cfg   = proposal.get("protocol_config") or {}
            protocol_label = proposal.get("protocol", "Aave v3")

            if protocol_type == "erc4626":
                vault_address = protocol_cfg.get("vault_address")
                if not vault_address:
                    raise RuntimeError(
                        f"vault_address not set for {protocol_label}. "
                        "Add it to config/treasury_protocols.json and set automated=true."
                    )
                tx_hash, bal_before, bal_after = _deposit_erc4626(deploy_amount, vault_address, private_key)
            elif protocol_type == "compound_v3":
                comet_address = protocol_cfg.get("comet_address")
                if not comet_address:
                    raise RuntimeError(f"comet_address not set for {protocol_label}.")
                tx_hash, bal_before, bal_after = _deposit_compound_v3(deploy_amount, comet_address, private_key)
            else:
                # Default: aave_v3
                tx_hash, bal_before, bal_after = _deposit_aave(deploy_amount, private_key)

            proposal.update({
                "status":              "DEPLOYED",
                "deployed_amount":     round(deploy_amount, 2),
                "aave_tx":             tx_hash,
                "deployed_at":         now,
                "balance_before_usd":  round(bal_before, 2),
                "balance_after_usd":   round(bal_after, 2),
                "balance_delta_usd":   round(bal_after - bal_before, 2),
            })
            _notify(
                f"🎉 *Treasury: Deployed!*\n"
                f"${deploy_amount:.0f} USDC in {protocol_label}\n"
                f"@ {proposal.get('apy', 0):.1f}% APY · "
                f"${proposal.get('projected_monthly', 0):.2f}/mnd verwacht\n"
                f"TX: `{tx_hash}`"
            )
        except Exception as e:
            proposal.update({"status": "FAILED", "error": str(e), "updated_at": now})
            _notify(f"❌ *Treasury: Deposit mislukt*\n`{e}`")
        return proposal

    # ── SWITCHING → USDC arrived in treasury wallet → deposit into new protocol ─
    if status == "SWITCHING":
        balance    = get_arb_usdc_balance(_TREASURY_WALLET)
        # For partial diversification switches, use switch_amount_usd as the threshold;
        # amount_usd holds the full source balance and would wait forever for a partial amount.
        switch_amt = float(proposal.get("switch_amount_usd") or proposal.get("amount_usd", 0))
        needed     = switch_amt * _BRIDGE_TOL
        if balance < max(needed, 10.0):
            logger.info(f"TreasuryExecutor: SWITCHING — waiting for USDC (${balance:.2f} < ${needed:.2f})")
            return proposal
        # Cap deposit at switch_amt * 1.05 to avoid accidentally sweeping other wallet USDC.
        deposit_amount = min(balance, switch_amt * 1.05)
        if not private_key:
            proposal.update({"status": "FAILED", "error": "No private key for deposit", "updated_at": now})
            return proposal
        protocol_type  = proposal.get("protocol_type", "aave_v3")
        protocol_cfg   = proposal.get("protocol_config") or {}
        protocol_label = proposal.get("protocol", "yield")
        try:
            if protocol_type == "erc4626":
                vault_address = protocol_cfg.get("vault_address")
                if not vault_address:
                    raise RuntimeError(f"vault_address missing for destination {protocol_label}")
                tx_hash, bal_before, bal_after = _deposit_erc4626(deposit_amount, vault_address, private_key)
            elif protocol_type == "compound_v3":
                comet_address = protocol_cfg.get("comet_address")
                if not comet_address:
                    raise RuntimeError(f"comet_address missing for {protocol_label}")
                tx_hash, bal_before, bal_after = _deposit_compound_v3(deposit_amount, comet_address, private_key)
            else:
                tx_hash, bal_before, bal_after = _deposit_aave(deposit_amount, private_key)

            proposal.update({
                "status":             "DEPLOYED",
                "deploy_tx":          tx_hash,
                "deployed_amount":    round(deposit_amount, 2),
                "deployed_at":        now,
                "balance_before_usd": round(bal_before, 2),
                "balance_after_usd":  round(bal_after, 2),
            })
            _notify(
                f"✅ *Treasury: Yield switch voltooid!*\n"
                f"${deposit_amount:.0f} USDC → {protocol_label}\n"
                f"@ {proposal.get('apy', 0):.1f}% APY (+{proposal.get('apy_spread', 0):.1f}% vs vorige)\n"
                f"TX: `{tx_hash}`"
            )
        except Exception as e:
            proposal.update({"status": "FAILED", "error": str(e), "updated_at": now})
            _notify(
                f"❌ *Treasury: Yield switch deposit mislukt*\n`{e}`\n"
                f"USDC staat op treasury wallet — handmatig storten vereist."
            )
        return proposal

    # ── REBALANCING → check Aave withdraw receipt ─────────────────────────────
    if status == "REBALANCING":
        tx_hash = proposal.get("aave_withdraw_tx", "")
        if tx_hash:
            receipt = _wait_receipt(tx_hash, timeout=10)
            if receipt and receipt.get("status") == "0x1":
                proposal.update({"status": "BRIDGE_BACK_NEEDED", "aave_withdrawn_at": now})
                _notify(
                    f"✅ *Treasury: Aave withdrawal bevestigd*\n"
                    f"${amount:.0f} USDC staat klaar op treasury wallet.\n"
                    f"Auto-bridge naar HL gestart in volgende cyclus…"
                )
            elif receipt:
                proposal.update({"status": "FAILED", "error": f"Aave withdraw failed: {tx_hash}", "updated_at": now})
                _notify(f"❌ *Treasury: Aave withdrawal mislukt* TX: `{tx_hash}`")
        return proposal

    # ── BRIDGE_BACK_NEEDED → auto-bridge USDC to HL ───────────────────────────
    if status == "BRIDGE_BACK_NEEDED":
        if not private_key:
            logger.warning("TreasuryExecutor: BRIDGE_BACK_NEEDED — no treasury key, skipping auto-bridge")
            return proposal
        vault_pk = get_vault_private_key()
        if not vault_pk:
            logger.warning("TreasuryExecutor: BRIDGE_BACK_NEEDED — no vault key, skipping auto-bridge")
            return proposal
        baseline_hl = 0.0
        if exchange_client:
            try:
                baseline_hl = exchange_client.get_balance()
            except Exception:
                pass
        try:
            bridge_tx = _bridge_usdc_to_hl(amount, private_key, vault_pk)
            proposal.update({
                "status":              "BRIDGING_TO_HL",
                "bridge_tx":           bridge_tx,
                "bridge_initiated_at": now,
                "hl_baseline":         baseline_hl,
            })
            _notify(
                f"🌉 *Treasury: Auto-bridge naar HL gestart!*\n"
                f"${amount:.0f} USDC van treasury wallet → Hyperliquid vault\n"
                f"TX: `{bridge_tx[:20]}…` — HL crediteert binnen ~2 min"
            )
        except Exception as e:
            proposal.update({"status": "FAILED", "error": str(e), "updated_at": now})
            _notify(f"❌ *Treasury: Auto-bridge mislukt*\n`{e}`")
        return proposal

    # ── BRIDGING_TO_HL → poll HL balance until credited ───────────────────────
    if status == "BRIDGING_TO_HL":
        expected = amount
        baseline = float(proposal.get("hl_baseline", 0))
        current_hl = baseline
        if exchange_client:
            try:
                current_hl = exchange_client.get_balance()
            except Exception:
                pass
        logger.info(
            f"TreasuryExecutor: BRIDGING_TO_HL — HL ${current_hl:.2f} "
            f"(baseline ${baseline:.2f}, expected +${expected:.2f})"
        )
        if current_hl >= baseline + expected * 0.85:
            proposal.update({"status": "COMPLETED", "completed_at": now, "final_hl_balance": current_hl})
            _notify(
                f"✅ *Treasury: Bridge voltooid!*\n"
                f"HL balans: ${current_hl:.2f} (+${current_hl - baseline:.2f})\n"
                f"Trading capaciteit hersteld."
            )
        return proposal

    # ── FUND_TRADING MONITORING → COMPLETED (HL balance check) ───────────────
    if status == "MONITORING" and proposal.get("type") == "FUND_TRADING":
        expected = float(proposal.get("amount_usd", 0))
        baseline = float(proposal.get("hl_baseline", 0))
        current_hl = baseline  # default: no change detected
        if exchange_client:
            try:
                current_hl = exchange_client.get_balance()
            except Exception:
                pass
        logger.info(
            f"TreasuryExecutor: FUND_TRADING monitoring — HL ${current_hl:.2f} "
            f"(baseline ${baseline:.2f}, expected +${expected:.2f})"
        )
        if current_hl >= baseline + expected * 0.9:
            proposal.update({"status": "COMPLETED", "completed_at": now, "final_hl_balance": current_hl})
            _notify(
                f"✅ *Treasury: HL top-up bevestigd*\n"
                f"HL balans: ${current_hl:.2f} (+${current_hl - baseline:.2f})\n"
                f"Trading capaciteit hersteld."
            )
        return proposal

    return proposal  # DEPLOYED / FAILED / PENDING / COMPLETED — no-op


def _fetch_secret_rest(secret_name: str) -> str:
    """
    Fetch a GCP secret via REST API — bypasses the grpc/protobuf SDK which can
    fail with 'inspect.signature' errors when called outside the main process.
    Uses the GCE metadata server for authentication (no credentials needed).
    """
    try:
        import base64 as _b64
        # Get OAuth token from metadata server
        token_req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(token_req, timeout=5) as r:
            token = json.loads(r.read())["access_token"]

        # Fetch secret via Secrets REST API
        project_req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/project/project-id",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(project_req, timeout=5) as r:
            project_id = r.read().decode().strip()

        secret_req = urllib.request.Request(
            f"https://secretmanager.googleapis.com/v1/projects/{project_id}/secrets/{secret_name}/versions/latest:access",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(secret_req, timeout=10) as r:
            data = json.loads(r.read())
        return _b64.b64decode(data["payload"]["data"]).decode().strip()
    except Exception as e:
        logger.debug(f"TreasuryExecutor: REST secret fetch failed for {secret_name}: {e}")
        return ""


def get_executor_private_key() -> tuple[str, str]:
    """
    Returns (private_key, wallet_address) for Arbitrum signing.
    Key resolution order:
      1. env HL_TREASURY_PRIVATE_KEY  (set by main.py via get_all_trading_secrets)
      2. REST API fetch HL_TREASURY_PRIVATE_KEY  (bypasses grpc SDK)
      3. env HL_VAULT_PRIVATE_KEY / HL_PRIVATE_KEY (fallbacks)
    """
    import os
    private_key = ""

    for secret_name in ("HL_TREASURY_PRIVATE_KEY", "HL_VAULT_PRIVATE_KEY", "HL_PRIVATE_KEY"):
        # 1. Check env first (fastest — set by main.py startup)
        val = os.getenv(secret_name, "")
        # 2. Try GCP SDK (may fail in docker exec context)
        if not val:
            try:
                from utils.gcp_secrets import get_secret
                val = get_secret(secret_name) or ""
            except Exception:
                pass
        # 3. REST API fallback (always works on GCE, no SDK dependency)
        if not val:
            val = _fetch_secret_rest(secret_name)
        if val:
            private_key = val
            break

    wallet_address = ""
    if private_key:
        try:
            Account = _EthAccount
            wallet_address = Account.from_key(private_key).address
            if wallet_address.lower() != _TREASURY_WALLET.lower():
                logger.debug(f"TreasuryExecutor: signing with {wallet_address[:10]}… (not the treasury wallet)")
        except Exception as e:
            logger.warning(f"TreasuryExecutor: cannot derive address from key: {e}")

    return private_key, wallet_address
