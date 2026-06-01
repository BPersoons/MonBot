"""
Pre-flight treasury system validator.

15 checks — no network calls, no secrets, no side effects:
  1. TreasuryAgent + executor functions import cleanly
  2. Key method signatures match caller expectations
  3. generate_proposals() returns correct structure + field set
  4. advance_proposal() routes BRIDGED by protocol_type (not always Aave)
  5. config/treasury_protocols.json is valid + automated protocols have addresses
  6. RiskManager.check_portfolio_drawdown() includes Aave balance
  7. main.py wires up both treasury_agent.run() and run_fast()
  8. _check_yield_switch() triggers/skips correctly
  9. advance_proposal() YIELD_SWITCH APPROVED→SWITCHING routing
 10. advance_proposal() SWITCHING→DEPLOYED routing (incl. partial switch_amount_usd)
 11. Funding Harvest: methods, constants, guards, and wiring
 12. RiskModel: profiles, weights, scoring, enrich_opportunities integration
 13. YieldOracle: import, ABI decode, enrichment logic, wiring order in treasury_agent
 14. AllocationOptimizer: import, LLM parse, validation, fallback, multi-proposal output
 15. _check_yield_diversification(): trigger, cooldown, partial switch_amount_usd

Usage:
    python -m tests.pre_flight.check_treasury
"""

import inspect
import json
import logging
import os
import sys
import unittest.mock as mock

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PreFlight-Treasury")

_FAKE_PK = "a" * 64  # non-empty, truthy; never hits real crypto in mocked tests


class _Result:
    def __init__(self):
        self.failures: list[str] = []
        self.passed = 0

    def ok(self, msg: str):
        self.passed += 1
        logger.info(f"  OK  {msg}")

    def fail(self, msg: str):
        self.failures.append(msg)
        logger.error(f" FAIL {msg}")

    def skip(self, msg: str):
        logger.info(f" SKIP {msg}")


# ── 1. Imports ────────────────────────────────────────────────────────────────

def check_imports(r: _Result):
    try:
        from agents.treasury_agent import TreasuryAgent  # noqa: F401
        r.ok("TreasuryAgent importable")
    except Exception as e:
        r.fail(f"TreasuryAgent import failed: {e}")
        return

    try:
        from utils.treasury_executor import (  # noqa: F401
            advance_proposal, get_aave_balance, get_arb_usdc_balance,
            get_executor_private_key, _TREASURY_WALLET,
            get_erc4626_balance, get_total_yield_balance,
            withdraw_erc4626_to_wallet, withdraw_aave_to_wallet,
            withdraw_erc4626_partial,
        )
        r.ok("treasury_executor: key functions importable (incl. withdraw_erc4626_partial)")
    except Exception as e:
        r.fail(f"treasury_executor import failed: {e}")


# ── 2. Signatures ─────────────────────────────────────────────────────────────

def check_signatures(r: _Result):
    try:
        from agents.treasury_agent import TreasuryAgent
        from utils.treasury_executor import advance_proposal
    except Exception as e:
        r.fail(f"Cannot import for signature check: {e}")
        return

    contracts = [
        ("TreasuryAgent.__init__",             TreasuryAgent.__init__,              ["exchange_client", "db_client"]),
        ("TreasuryAgent.generate_proposals",   TreasuryAgent.generate_proposals,   ["hl", "opportunities", "treasury_usdc"]),
        ("TreasuryAgent.execute_approved_proposals", TreasuryAgent.execute_approved_proposals, ["all_proposals"]),
        ("TreasuryAgent.run",                  TreasuryAgent.run,                   []),
        ("TreasuryAgent.run_fast",             TreasuryAgent.run_fast,              []),
        ("advance_proposal",                   advance_proposal,                    ["proposal", "exchange_client", "private_key", "wallet_address", "telegram_fn"]),
    ]

    for desc, fn, required in contracts:
        try:
            params = set(inspect.signature(fn).parameters) - {"self"}
            missing = [p for p in required if p not in params]
            if missing:
                r.fail(f"Signature mismatch {desc}: missing {missing} (got {sorted(params)})")
            else:
                r.ok(f"Signature OK: {desc}")
        except Exception as e:
            r.fail(f"Cannot inspect {desc}: {e}")


# ── 3. generate_proposals() logic ─────────────────────────────────────────────

def check_generate_proposals_logic(r: _Result):
    try:
        from agents.treasury_agent import TreasuryAgent
        from utils import treasury_executor as te
    except Exception as e:
        r.fail(f"Cannot import for generate_proposals check: {e}")
        return

    agent = TreasuryAgent()

    hl = {"balance": 300.0, "free_margin": 280.0, "deployed_margin": 20.0, "idle_pct": 93.0}
    mock_cfg = {
        "id": "aave-v3-arbitrum-usdc", "type": "aave_v3", "automated": True,
        "pool_address": "0x794a61358D6845594F94dc1DB02A252b5b4814aD",
        "asset_address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "receipt_token": "0x724dc807b04555b71ed48a6896b6F41593b8C637",
    }
    opps = [{
        "label": "Aave v3 · Arbitrum · USDC", "project": "aave-v3", "chain": "Arbitrum",
        "risk_tier": "stable", "apy": 4.0, "apy_base": 4.0, "apy_reward": 0.0,
        "tvl_usd": 100_000_000, "pool_id": "arb-usdc", "automated": True, "protocol_config": mock_cfg,
    }]

    # Case A: HL underfunded + $2500 treasury USDC → split between HL top-up and yield
    proposals = agent.generate_proposals(hl, opps, treasury_usdc=2500.0, aave_balance=200.0)
    if not proposals:
        r.fail("generate_proposals: returned [] with $2500 treasury USDC")
        return
    r.ok(f"generate_proposals: returned {len(proposals)} proposal(s)")

    deploy_props = [p for p in proposals if p.get("type") == "DEPLOY_YIELD"]
    topup_props  = [p for p in proposals if p.get("type") == "FUND_TRADING"]

    if deploy_props:
        p = deploy_props[0]
        required = ["id", "type", "status", "amount_usd", "protocol_type", "protocol_config",
                    "executable", "rationale", "source_treasury", "allocation"]
        missing = [f for f in required if f not in p]
        if missing:
            r.fail(f"DEPLOY_YIELD proposal missing fields: {missing}")
        else:
            r.ok("DEPLOY_YIELD proposal has all required fields incl. allocation")

        if p.get("protocol_type") == "aave_v3":
            r.ok("generate_proposals: protocol_type correctly set")
        else:
            r.fail(f"generate_proposals: expected protocol_type='aave_v3', got '{p.get('protocol_type')}'")

        if p.get("executable") is True:
            r.ok("generate_proposals: automated Arbitrum protocol → executable=True")
        else:
            r.fail("generate_proposals: automated Arbitrum protocol should be executable=True")

        if p.get("amount_usd", 2500) < 2500:
            r.ok(f"generate_proposals: ${p['amount_usd']:.0f} to yield (split correctly — HL gets top-up)")
        else:
            r.fail("generate_proposals: all $2500 goes to yield — portfolio allocation split missing")
    else:
        r.fail("generate_proposals: no DEPLOY_YIELD proposal generated")

    if topup_props:
        tp = topup_props[0]
        r.ok(f"generate_proposals: FUND_TRADING proposal ${tp.get('amount_usd', 0):.0f} to HL top-up")
    else:
        r.ok("generate_proposals: no FUND_TRADING (HL already at target)")

    # Case B: no opportunities → []
    result_b = agent.generate_proposals(hl, [], treasury_usdc=0, aave_balance=0.0)
    if result_b:
        r.fail("generate_proposals: should return [] when no opportunities")
    else:
        r.ok("generate_proposals: returns [] when no opportunities")

    # Case C: nothing deployable → []
    result_c = agent.generate_proposals(hl, opps, treasury_usdc=0, aave_balance=0.0)
    if result_c:
        r.fail("generate_proposals: should return [] when no capital to deploy")
    else:
        r.ok("generate_proposals: returns [] when nothing to deploy")

    # Case D: _pick_best_protocol never recommends non-Arbitrum non-automated (Curve bug)
    curve_opp = {
        "label": "Curve crvUSD", "project": "curve-dex", "chain": "Ethereum",
        "risk_tier": "medium", "apy": 8.0, "automated": False, "protocol_config": None,
    }
    best, _ = agent._pick_best_protocol([curve_opp])
    if best is None:
        r.ok("_pick_best_protocol: Curve (Ethereum non-automated) correctly rejected")
    else:
        r.fail(f"_pick_best_protocol: returned '{best['label']}' — Curve/Ethereum bug not fixed")


# ── 4. advance_proposal protocol routing ──────────────────────────────────────

def check_advance_proposal_routing(r: _Result):
    try:
        from utils import treasury_executor as te
    except Exception as e:
        r.fail(f"Cannot import treasury_executor: {e}")
        return

    # Test A: erc4626 without vault_address → FAILED, must NOT silently call Aave
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=500.0), \
         mock.patch.object(te, "_deposit_aave",
                           side_effect=AssertionError("_deposit_aave called for erc4626!")):
        result = te.advance_proposal(
            {
                "status": "BRIDGED", "amount_usd": 500.0,
                "protocol": "Morpho", "protocol_type": "erc4626",
                "protocol_config": {"vault_address": None},
                "apy": 3.56, "projected_monthly": 14.83,
            },
            private_key=_FAKE_PK,
        )

    if result.get("status") == "FAILED" and "vault_address" in result.get("error", ""):
        r.ok("advance_proposal: erc4626 without vault_address → FAILED (not silent Aave fallback)")
    else:
        r.fail(
            f"advance_proposal: erc4626 routing wrong — "
            f"status={result.get('status')} error={result.get('error', '')[:80]}"
        )

    # Test B: aave_v3 → calls _deposit_aave
    aave_calls: list = []
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=200.0), \
         mock.patch.object(te, "_deposit_aave",
                           side_effect=lambda amt, pk: aave_calls.append(amt) or "0xfaketx"):
        te.advance_proposal(
            {
                "status": "BRIDGED", "amount_usd": 200.0,
                "protocol": "Aave v3", "protocol_type": "aave_v3",
                "apy": 4.0, "projected_monthly": 6.67,
            },
            private_key=_FAKE_PK,
        )

    if aave_calls:
        r.ok("advance_proposal: protocol_type=aave_v3 routes to _deposit_aave")
    else:
        r.fail("advance_proposal: aave_v3 did NOT call _deposit_aave")

    # Test C: compound_v3 without comet_address → FAILED, not Aave
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=200.0), \
         mock.patch.object(te, "_deposit_aave",
                           side_effect=AssertionError("_deposit_aave called for compound_v3!")):
        result_c = te.advance_proposal(
            {
                "status": "BRIDGED", "amount_usd": 200.0,
                "protocol": "Compound v3", "protocol_type": "compound_v3",
                "protocol_config": {"comet_address": None},
                "apy": 3.0, "projected_monthly": 5.0,
            },
            private_key=_FAKE_PK,
        )

    if result_c.get("status") == "FAILED":
        r.ok("advance_proposal: compound_v3 without comet_address → FAILED (not Aave fallback)")
    else:
        r.fail(f"advance_proposal: compound_v3 routing wrong — status={result_c.get('status')}")

    # Test D: unknown status → no-op (proposal unchanged)
    noop = te.advance_proposal({"status": "DEPLOYED", "amount_usd": 100.0}, private_key=_FAKE_PK)
    if noop.get("status") == "DEPLOYED":
        r.ok("advance_proposal: terminal status DEPLOYED → no-op")
    else:
        r.fail(f"advance_proposal: DEPLOYED proposal mutated unexpectedly → {noop.get('status')}")


# ── 5. Protocol config JSON ────────────────────────────────────────────────────

def check_protocol_config(r: _Result):
    config_path = os.path.join(os.getcwd(), "config", "treasury_protocols.json")
    if not os.path.exists(config_path):
        r.fail("config/treasury_protocols.json missing")
        return

    try:
        with open(config_path) as f:
            data = json.load(f)
        r.ok("config/treasury_protocols.json is valid JSON")
    except Exception as e:
        r.fail(f"config/treasury_protocols.json parse error: {e}")
        return

    protocols = data.get("protocols", [])
    if not protocols:
        r.fail("config/treasury_protocols.json has no protocols defined")
        return

    required_fields = ["id", "type", "chain", "automated"]
    for p in protocols:
        pid = p.get("id", "?")
        missing = [f for f in required_fields if f not in p]
        if missing:
            r.fail(f"Protocol '{pid}' missing required fields: {missing}")
        else:
            r.ok(f"Protocol '{pid}': required fields present")

        if p.get("automated"):
            has_addr = any(p.get(k) for k in ("pool_address", "vault_address", "comet_address"))
            if not has_addr:
                r.fail(f"Protocol '{pid}' has automated=true but no executable address configured")
            else:
                r.ok(f"Protocol '{pid}': automated=true with valid address")


# ── 6. Drawdown includes Aave balance ─────────────────────────────────────────

def check_drawdown_includes_aave(r: _Result):
    try:
        from agents.risk_manager import RiskManager
        src = inspect.getsource(RiskManager.check_portfolio_drawdown)
    except Exception as e:
        r.fail(f"Cannot inspect RiskManager.check_portfolio_drawdown: {e}")
        return

    # Accept either specific Aave balance or the broader total yield balance function
    if "get_total_yield_balance" in src:
        r.ok("RiskManager.check_portfolio_drawdown: includes total yield balance — all protocol deployments won't trigger false halt")
    elif "get_aave_balance" in src:
        r.ok("RiskManager.check_portfolio_drawdown: includes Aave balance — treasury deployments won't trigger false halt")
    else:
        r.fail(
            "RiskManager.check_portfolio_drawdown: does NOT include Aave balance — "
            "treasury deployments look like drawdown and will block trading"
        )


# ── 7. Swarm integration (main.py) ────────────────────────────────────────────

def check_swarm_integration(r: _Result):
    main_path = os.path.join(os.getcwd(), "main.py")
    if not os.path.exists(main_path):
        r.skip("main.py not found")
        return

    with open(main_path, encoding="utf-8") as f:
        src = f.read()

    if "treasury_agent.run()" in src and "treasury_agent.run_fast()" in src:
        r.ok("main.py wires up treasury_agent.run() and treasury_agent.run_fast()")
    elif "treasury_agent.run()" in src:
        r.fail("main.py only calls treasury_agent.run() — run_fast() not wired up (5-min execution path missing)")
    else:
        r.fail("main.py does not call treasury_agent.run() — treasury not running")

    # Dashboard approve handler should spawn execution thread
    dashboard_path = os.path.join(os.getcwd(), "utils", "dashboard_server.py")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, encoding="utf-8") as f:
            dash_src = f.read()
        if "advance_proposal" in dash_src:
            r.ok("dashboard_server.py: approve handler calls advance_proposal (instant execution)")
        else:
            r.fail("dashboard_server.py: approve handler does not call advance_proposal — approvals will only execute on next treasury cycle")


# ── 8. _check_yield_switch() trigger logic ────────────────────────────────────

def check_yield_switch_logic(r: _Result):
    try:
        from agents.treasury_agent import TreasuryAgent, _YIELD_SWITCH_MIN_SPREAD, _YIELD_SWITCH_MIN_USD
    except Exception as e:
        r.fail(f"Cannot import TreasuryAgent for yield_switch check: {e}")
        return

    agent = TreasuryAgent()

    def _make_opp(pid: str, apy: float, chain: str = "Arbitrum", automated: bool = True) -> dict:
        return {
            "label":        pid,
            "project":      pid,
            "chain":        chain,
            "apy":          apy,
            "automated":    automated,
            "protocol_config": {
                "id":           pid,
                "type":         "erc4626" if "morpho" in pid else "aave_v3",
                "vault_address": "0x" + "a" * 40 if "morpho" in pid else None,
                "label":        pid,
            },
        }

    # Case A: triggers when spread ≥ threshold and balance ≥ minimum
    opps_a = [_make_opp("aave-v3-arbitrum-usdc", 4.0), _make_opp("morpho-bbq", 7.0)]
    balances_a = {"aave-v3-arbitrum-usdc": 500.0}
    result_a, notifs_a = agent._check_yield_switch(opps_a, balances_a, [])
    switch_a = [p for p in result_a if p.get("type") == "YIELD_SWITCH"]
    if switch_a:
        r.ok(f"_check_yield_switch: triggers when spread={7.0-4.0:.1f}% ≥ {_YIELD_SWITCH_MIN_SPREAD:.1f}%")
        if switch_a[0].get("status") == "APPROVED":
            r.ok("_check_yield_switch: new proposal auto-status=APPROVED")
        else:
            r.fail(f"_check_yield_switch: expected status=APPROVED, got {switch_a[0].get('status')}")
        if switch_a[0].get("auto_initiated") is True:
            r.ok("_check_yield_switch: auto_initiated=True on triggered proposal")
        else:
            r.fail("_check_yield_switch: auto_initiated should be True")
        if notifs_a:
            r.ok("_check_yield_switch: notification queued (not sent) — will fire after _save_proposals")
        else:
            r.fail("_check_yield_switch: expected notification text in return tuple")
    else:
        r.fail(f"_check_yield_switch: should trigger at 3.0% spread (threshold={_YIELD_SWITCH_MIN_SPREAD}%)")

    # Case B: does NOT trigger when spread < threshold
    opps_b = [_make_opp("aave-v3-arbitrum-usdc", 4.0), _make_opp("morpho-bbq", 4.9)]
    balances_b = {"aave-v3-arbitrum-usdc": 500.0}
    result_b, _ = agent._check_yield_switch(opps_b, balances_b, [])
    if not any(p.get("type") == "YIELD_SWITCH" for p in result_b):
        r.ok(f"_check_yield_switch: no trigger when spread=0.9% < {_YIELD_SWITCH_MIN_SPREAD}%")
    else:
        r.fail("_check_yield_switch: triggered below spread threshold — too aggressive")

    # Case C: does NOT trigger when balance < minimum
    opps_c = [_make_opp("aave-v3-arbitrum-usdc", 4.0), _make_opp("morpho-bbq", 8.0)]
    balances_c = {"aave-v3-arbitrum-usdc": _YIELD_SWITCH_MIN_USD - 1}
    result_c, _ = agent._check_yield_switch(opps_c, balances_c, [])
    if not any(p.get("type") == "YIELD_SWITCH" for p in result_c):
        r.ok(f"_check_yield_switch: no trigger when balance ${_YIELD_SWITCH_MIN_USD - 1} < ${_YIELD_SWITCH_MIN_USD} minimum")
    else:
        r.fail("_check_yield_switch: triggered below minimum balance — gas cost not justified")

    # Case D: does NOT trigger when a YIELD_SWITCH is already in-flight
    in_flight = [{"type": "YIELD_SWITCH", "status": "SWITCHING"}]
    result_d, _ = agent._check_yield_switch(opps_a, balances_a, in_flight)
    switch_d = [p for p in result_d if p.get("type") == "YIELD_SWITCH" and p.get("status") != "SWITCHING"]
    if not switch_d:
        r.ok("_check_yield_switch: skipped when SWITCHING already in-flight (one switch at a time)")
    else:
        r.fail("_check_yield_switch: created second switch while one is already SWITCHING")

    # Case E: does NOT trigger when already in the best protocol
    opps_e = [_make_opp("morpho-bbq", 8.0)]  # morpho-bbq IS the best
    balances_e = {"morpho-bbq": 500.0}         # and we are already deployed there
    result_e, _ = agent._check_yield_switch(opps_e, balances_e, [])
    if not any(p.get("type") == "YIELD_SWITCH" for p in result_e):
        r.ok("_check_yield_switch: no trigger when already in best protocol")
    else:
        r.fail("_check_yield_switch: triggered switch to same protocol — pid match check broken")

    def _make_opp_ra(pid: str, apy: float, ra: float, immediate: bool = True) -> dict:
        o = _make_opp(pid, apy)
        o["risk_adjusted_apy"] = ra
        o["protocol_config"]["immediate_withdraw"] = immediate
        return o

    # Case F: ranks on RISK-ADJUSTED APY, not raw. A high-headline-yield but high-risk
    # destination must NOT trigger a switch when its risk-adjusted spread is below the
    # threshold. Regression guard for the Gains-consolidation bug: raw spread 3.5% would
    # have triggered, but risk-adjusted spread is 1.3% (< 1.5%).
    opps_f = [
        _make_opp_ra("aave-v3-arbitrum-usdc", 3.0, 2.5),
        _make_opp_ra("highraw-lowriskadj", 6.5, 3.8),
    ]
    balances_f = {"aave-v3-arbitrum-usdc": 500.0}
    result_f, _ = agent._check_yield_switch(opps_f, balances_f, [])
    if not any(p.get("type") == "YIELD_SWITCH" for p in result_f):
        r.ok("_check_yield_switch: ranks on risk-adjusted APY — no switch when risk-adj spread 1.3% < threshold (raw 3.5%)")
    else:
        r.fail("_check_yield_switch: switched on RAW APY spread — risk model ignored (Gains-consolidation regression)")

    # Case G: an epoch-based destination (immediate_withdraw=false) must be excluded as a
    # switch target — moving INTO a one-way vault traps the capital. Even a huge spread
    # must not create a switch.
    opps_g = [
        _make_opp_ra("aave-v3-arbitrum-usdc", 3.0, 2.5, immediate=True),
        _make_opp_ra("gains-epoch", 10.0, 8.0, immediate=False),
    ]
    balances_g = {"aave-v3-arbitrum-usdc": 500.0}
    result_g, _ = agent._check_yield_switch(opps_g, balances_g, [])
    if not any(p.get("type") == "YIELD_SWITCH" for p in result_g):
        r.ok("_check_yield_switch: epoch-based (immediate_withdraw=false) excluded as switch destination")
    else:
        r.fail("_check_yield_switch: switched INTO an epoch-based vault — would trap capital")


# ── 9. YIELD_SWITCH APPROVED → SWITCHING routing ─────────────────────────────

def check_yield_switch_approved_routing(r: _Result):
    try:
        from utils import treasury_executor as te
    except Exception as e:
        r.fail(f"Cannot import treasury_executor: {e}")
        return

    # Test A: erc4626 from_protocol_type → calls withdraw_erc4626_to_wallet → SWITCHING
    erc4626_calls: list = []
    with mock.patch.object(te, "withdraw_erc4626_to_wallet",
                           side_effect=lambda va, pk: erc4626_calls.append(va) or ("0xfaketx", 0, 100)):
        result = te.advance_proposal(
            {
                "status":              "APPROVED",
                "type":                "YIELD_SWITCH",
                "amount_usd":          500.0,
                "from_protocol":       "Aave v3",
                "from_protocol_type":  "erc4626",
                "from_protocol_config": {"vault_address": "0x" + "a" * 40},
                "protocol":            "Morpho BBQUSDC",
                "protocol_type":       "erc4626",
                "protocol_config":     {"vault_address": "0x" + "b" * 40},
                "apy":                 8.0,
            },
            private_key=_FAKE_PK,
        )

    if erc4626_calls:
        r.ok("YIELD_SWITCH APPROVED (erc4626 source): routes to withdraw_erc4626_to_wallet")
    else:
        r.fail("YIELD_SWITCH APPROVED (erc4626 source): did NOT call withdraw_erc4626_to_wallet")

    if result.get("status") == "SWITCHING":
        r.ok("YIELD_SWITCH APPROVED → SWITCHING after erc4626 withdrawal")
    else:
        r.fail(f"YIELD_SWITCH APPROVED: expected status=SWITCHING, got {result.get('status')} err={result.get('error','')[:80]}")

    # Test B: aave_v3 from_protocol_type → calls withdraw_aave_to_wallet → SWITCHING
    aave_calls: list = []
    with mock.patch.object(te, "get_aave_balance", return_value=500.0), \
         mock.patch.object(te, "withdraw_aave_to_wallet",
                           side_effect=lambda amt, pk: aave_calls.append(amt) or "0xfaketx"):
        result_b = te.advance_proposal(
            {
                "status":              "APPROVED",
                "type":                "YIELD_SWITCH",
                "amount_usd":          500.0,
                "from_protocol":       "Aave v3",
                "from_protocol_type":  "aave_v3",
                "from_protocol_config": {},
                "protocol":            "Morpho BBQUSDC",
                "protocol_type":       "erc4626",
                "protocol_config":     {"vault_address": "0x" + "b" * 40},
                "apy":                 8.0,
            },
            private_key=_FAKE_PK,
        )

    if aave_calls:
        r.ok("YIELD_SWITCH APPROVED (aave_v3 source): routes to withdraw_aave_to_wallet")
    else:
        r.fail("YIELD_SWITCH APPROVED (aave_v3 source): did NOT call withdraw_aave_to_wallet")

    if result_b.get("status") == "SWITCHING":
        r.ok("YIELD_SWITCH APPROVED (aave_v3) → SWITCHING")
    else:
        r.fail(f"YIELD_SWITCH APPROVED (aave_v3): expected SWITCHING, got {result_b.get('status')} err={result_b.get('error','')[:80]}")

    # Test C: missing private key → FAILED immediately (no funds touched)
    result_c = te.advance_proposal(
        {"status": "APPROVED", "type": "YIELD_SWITCH", "amount_usd": 500.0},
        private_key="",
    )
    if result_c.get("status") == "FAILED":
        r.ok("YIELD_SWITCH APPROVED: no private key → FAILED immediately (safe)")
    else:
        r.fail(f"YIELD_SWITCH APPROVED: no key should FAIL, got {result_c.get('status')}")

    # Test D: erc4626 source with no vault_address → FAILED (not silent crash)
    result_d = te.advance_proposal(
        {
            "status":              "APPROVED",
            "type":                "YIELD_SWITCH",
            "amount_usd":          500.0,
            "from_protocol_type":  "erc4626",
            "from_protocol_config": {"vault_address": None},
        },
        private_key=_FAKE_PK,
    )
    if result_d.get("status") == "FAILED" and result_d.get("error"):
        r.ok("YIELD_SWITCH APPROVED (erc4626 source, no vault_address) → FAILED with error")
    else:
        r.fail(f"YIELD_SWITCH (erc4626 no vault_addr): expected FAILED, got {result_d.get('status')}")


# ── 10. SWITCHING → DEPLOYED routing ─────────────────────────────────────────

def check_yield_switch_switching_routing(r: _Result):
    try:
        from utils import treasury_executor as te
    except Exception as e:
        r.fail(f"Cannot import treasury_executor: {e}")
        return

    # Test A: SWITCHING + USDC arrived → deposits into erc4626 destination → DEPLOYED
    deposit_calls: list = []
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=500.0), \
         mock.patch.object(te, "_deposit_erc4626",
                           side_effect=lambda amt, va, pk: deposit_calls.append((amt, va)) or ("0xfaketx", 0, 500)):
        result = te.advance_proposal(
            {
                "status":          "SWITCHING",
                "type":            "YIELD_SWITCH",
                "amount_usd":      480.0,
                "protocol":        "Morpho BBQUSDC",
                "protocol_type":   "erc4626",
                "protocol_config": {"vault_address": "0x" + "b" * 40},
                "apy":             8.0,
                "apy_spread":      4.0,
            },
            private_key=_FAKE_PK,
        )

    if deposit_calls:
        r.ok("SWITCHING: erc4626 destination → calls _deposit_erc4626")
    else:
        r.fail("SWITCHING: erc4626 destination — _deposit_erc4626 not called")

    if result.get("status") == "DEPLOYED":
        r.ok("SWITCHING → DEPLOYED after erc4626 deposit")
    else:
        r.fail(f"SWITCHING: expected DEPLOYED, got {result.get('status')} err={result.get('error','')[:80]}")

    # Test B: SWITCHING + USDC not arrived yet → no-op (stays SWITCHING)
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=10.0), \
         mock.patch.object(te, "_deposit_erc4626",
                           side_effect=AssertionError("should not deposit yet")):
        result_b = te.advance_proposal(
            {
                "status":          "SWITCHING",
                "type":            "YIELD_SWITCH",
                "amount_usd":      480.0,
                "protocol_type":   "erc4626",
                "protocol_config": {"vault_address": "0x" + "b" * 40},
            },
            private_key=_FAKE_PK,
        )

    if result_b.get("status") == "SWITCHING":
        r.ok("SWITCHING: USDC not arrived → no-op (stays SWITCHING, no premature deposit)")
    else:
        r.fail(f"SWITCHING: should stay SWITCHING when USDC not arrived, got {result_b.get('status')}")

    # Test C: SWITCHING + aave_v3 destination → _deposit_aave
    aave_dep_calls: list = []
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=500.0), \
         mock.patch.object(te, "_deposit_aave",
                           side_effect=lambda amt, pk: aave_dep_calls.append(amt) or ("0xfaketx", 0, 500)):
        result_c = te.advance_proposal(
            {
                "status":          "SWITCHING",
                "type":            "YIELD_SWITCH",
                "amount_usd":      480.0,
                "protocol":        "Aave v3",
                "protocol_type":   "aave_v3",
                "protocol_config": {},
                "apy":             5.0,
                "apy_spread":      1.5,
            },
            private_key=_FAKE_PK,
        )

    if aave_dep_calls:
        r.ok("SWITCHING: aave_v3 destination → calls _deposit_aave")
    else:
        r.fail("SWITCHING: aave_v3 destination — _deposit_aave not called")

    if result_c.get("status") == "DEPLOYED":
        r.ok("SWITCHING (aave_v3 destination) → DEPLOYED")
    else:
        r.fail(f"SWITCHING (aave_v3): expected DEPLOYED, got {result_c.get('status')}")

    # Test D: SWITCHING partial switch — switch_amount_usd < amount_usd, arrived=$735
    # needed = 735 * _BRIDGE_TOL (≈ 698), not 2102 * _BRIDGE_TOL (≈ 1997)
    partial_dep_calls: list = []
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=735.0), \
         mock.patch.object(te, "_deposit_erc4626",
                           side_effect=lambda amt, va, pk: partial_dep_calls.append(amt) or ("0xfaketx", 0, 735)):
        result_d = te.advance_proposal(
            {
                "status":           "SWITCHING",
                "type":             "YIELD_SWITCH",
                "amount_usd":       2102.0,     # full source balance
                "switch_amount_usd": 735.0,     # only this was withdrawn
                "protocol":         "Aave v3",
                "protocol_type":    "erc4626",
                "protocol_config":  {"vault_address": "0x" + "b" * 40},
                "apy":              5.0,
                "apy_spread":       1.5,
            },
            private_key=_FAKE_PK,
        )

    if result_d.get("status") == "DEPLOYED":
        r.ok("SWITCHING partial (switch_amount_usd=735, amount_usd=2102): proceeds when $735 arrived")
    else:
        r.fail(f"SWITCHING partial: expected DEPLOYED, got {result_d.get('status')} err={result_d.get('error','')[:80]}")

    if partial_dep_calls and abs(partial_dep_calls[0] - 735.0) <= 735.0 * 0.05:
        r.ok(f"SWITCHING partial: deposits ≈ switch_amount_usd (${partial_dep_calls[0]:.2f}), not full amount_usd $2102")
    elif partial_dep_calls:
        r.fail(f"SWITCHING partial: deposit amount ${partial_dep_calls[0]:.2f} ≠ expected ≈$735")
    else:
        r.fail("SWITCHING partial: _deposit_erc4626 not called")

    # Test E: partial switch — USDC not arrived yet (only $200, needed ≈ 698) → stays SWITCHING
    with mock.patch.object(te, "get_arb_usdc_balance", return_value=200.0), \
         mock.patch.object(te, "_deposit_erc4626",
                           side_effect=AssertionError("should not deposit yet")):
        result_e = te.advance_proposal(
            {
                "status":           "SWITCHING",
                "type":             "YIELD_SWITCH",
                "amount_usd":       2102.0,
                "switch_amount_usd": 735.0,
                "protocol_type":    "erc4626",
                "protocol_config":  {"vault_address": "0x" + "b" * 40},
            },
            private_key=_FAKE_PK,
        )

    if result_e.get("status") == "SWITCHING":
        r.ok("SWITCHING partial: $200 < needed $698 → stays SWITCHING (no premature deposit)")
    else:
        r.fail(f"SWITCHING partial: should stay SWITCHING when USDC insufficient, got {result_e.get('status')}")


# ── 11. Funding Harvest: methods, constants, guards, wiring ──────────────────

def check_funding_harvest(r: _Result):
    try:
        from agents.treasury_agent import TreasuryAgent
    except Exception as e:
        r.fail(f"Cannot import TreasuryAgent for harvest check: {e}")
        return

    # a. Required constants
    required_constants = [
        "_HARVEST_MIN_RATE_8H", "_HARVEST_CLOSE_RATE_8H",
        "_HARVEST_MAX_NOTIONAL", "_HARVEST_MAX_HOLD_H", "_HARVEST_ALLOWED_ASSETS",
    ]
    for c in required_constants:
        if hasattr(TreasuryAgent, c):
            r.ok(f"TreasuryAgent.{c} constant defined")
        else:
            r.fail(f"TreasuryAgent.{c} constant missing")

    # b. Required methods
    required_methods = [
        "_get_hl_funding_rates", "_get_harvest_state", "_save_harvest_state",
        "_open_harvest_position", "_close_harvest_position",
        "_check_funding_harvest", "_monitor_funding_harvest",
    ]
    for m in required_methods:
        if callable(getattr(TreasuryAgent, m, None)):
            r.ok(f"TreasuryAgent.{m}() defined")
        else:
            r.fail(f"TreasuryAgent.{m}() missing")

    # c. run() calls _check_funding_harvest and _monitor_funding_harvest
    run_src = inspect.getsource(TreasuryAgent.run)
    if "_check_funding_harvest" in run_src:
        r.ok("TreasuryAgent.run() calls _check_funding_harvest()")
    else:
        r.fail("TreasuryAgent.run() does NOT call _check_funding_harvest()")
    if "_monitor_funding_harvest" in run_src:
        r.ok("TreasuryAgent.run() calls _monitor_funding_harvest()")
    else:
        r.fail("TreasuryAgent.run() does NOT call _monitor_funding_harvest()")

    # d. run() state dict includes funding_harvest
    if "funding_harvest" in run_src:
        r.ok("TreasuryAgent.run() includes funding_harvest in state dict")
    else:
        r.fail("TreasuryAgent.run() state dict missing 'funding_harvest' key")

    # e. run_fast() calls _monitor_funding_harvest
    fast_src = inspect.getsource(TreasuryAgent.run_fast)
    if "_monitor_funding_harvest" in fast_src:
        r.ok("TreasuryAgent.run_fast() calls _monitor_funding_harvest()")
    else:
        r.fail("TreasuryAgent.run_fast() does NOT call _monitor_funding_harvest()")

    # f. execution_agent.py guards harvest trades in backfill and Pass 3
    exec_path = os.path.join(os.getcwd(), "agents", "execution_agent.py")
    if os.path.exists(exec_path):
        with open(exec_path, encoding="utf-8") as f:
            exec_src = f.read()
        harvest_guard_count = exec_src.count('t.get("harvest")')
        if harvest_guard_count >= 2:
            r.ok(f"execution_agent.py: {harvest_guard_count} harvest guards (backfill + Pass 3)")
        elif harvest_guard_count == 1:
            r.fail("execution_agent.py: only 1 harvest guard — need guards in BOTH backfill and Pass 3")
        else:
            r.fail("execution_agent.py: no harvest guard — harvest positions will be managed by strategy_manager and external closure sync")
    else:
        r.fail("agents/execution_agent.py not found")

    # g. strategy_manager.py guards harvest trades in evaluate_position
    sm_path = os.path.join(os.getcwd(), "agents", "strategy_manager.py")
    if os.path.exists(sm_path):
        with open(sm_path, encoding="utf-8") as f:
            sm_src = f.read()
        if 'trade.get("harvest")' in sm_src:
            r.ok("strategy_manager.py: harvest guard in evaluate_position()")
        else:
            r.fail("strategy_manager.py: no harvest guard — strategy_manager will manage harvest positions")
    else:
        r.fail("agents/strategy_manager.py not found")

    # h. Threshold sanity: close < open
    open_thresh  = getattr(TreasuryAgent, "_HARVEST_MIN_RATE_8H", None)
    close_thresh = getattr(TreasuryAgent, "_HARVEST_CLOSE_RATE_8H", None)
    if open_thresh and close_thresh:
        if close_thresh < open_thresh:
            r.ok(f"Harvest thresholds sane: open={open_thresh}% > close={close_thresh}%/8h")
        else:
            r.fail(f"Harvest thresholds inverted: open={open_thresh}% ≤ close={close_thresh}%/8h — position will close immediately")


# ── 12. RiskModel: profiles, weights, scoring, integration ───────────────────

def check_risk_model(r: _Result):
    try:
        from utils.treasury_risk import (
            score_protocol, risk_adjusted_apy, enrich_opportunities,
            _WEIGHTS, _PROFILES,
        )
    except Exception as e:
        r.fail(f"Cannot import treasury_risk: {e}")
        return

    # a. Weights sum to 1.0
    total = sum(_WEIGHTS.values())
    if abs(total - 1.0) < 1e-9:
        r.ok(f"RiskModel: weights sum to 1.0 ({list(_WEIGHTS.values())})")
    else:
        r.fail(f"RiskModel: weights sum to {total:.6f}, expected 1.0")

    # b. All live automated protocols have a profile
    live_protocols = [
        "aave-v3-arbitrum-usdc",
        "morpho-bbqusdc-arbitrum",
        "morpho-gtusdcc-arbitrum",
        "gains-network-arbitrum-usdc",
    ]
    for pid in live_protocols:
        if pid in _PROFILES:
            r.ok(f"RiskModel: profile defined for '{pid}'")
        else:
            r.fail(f"RiskModel: no profile for live protocol '{pid}'")

    # c. All scores in each profile are 0–1
    for pid, profile in _PROFILES.items():
        for dim in ("sc", "liquidity", "counterparty", "maturity"):
            val = profile.get(dim, -1)
            if 0.0 <= val <= 1.0:
                pass
            else:
                r.fail(f"RiskModel: profile '{pid}'.{dim}={val} out of range [0,1]")
    r.ok("RiskModel: all static profile scores in range [0,1]")

    # d. score_protocol returns correct structure
    result = score_protocol("aave-v3-arbitrum-usdc", tvl_usd=500_000_000)
    required_keys = {"overall", "components", "label", "description", "tranche"}
    missing = required_keys - set(result.keys())
    if missing:
        r.fail(f"score_protocol: missing keys {missing}")
    else:
        r.ok("score_protocol: returns correct structure (overall, components, label, description, tranche)")

    if 0.0 < result["overall"] <= 1.0:
        r.ok(f"score_protocol: Aave overall score {result['overall']} in (0,1]")
    else:
        r.fail(f"score_protocol: Aave overall={result['overall']} out of range")

    # e. Aave scores higher than Gains (safest vs highest-risk protocol)
    aave_score  = score_protocol("aave-v3-arbitrum-usdc",        tvl_usd=500_000_000)["overall"]
    gains_score = score_protocol("gains-network-arbitrum-usdc",  tvl_usd=6_000_000)["overall"]
    if aave_score > gains_score:
        r.ok(f"score_protocol: Aave ({aave_score:.3f}) > Gains ({gains_score:.3f}) — risk ordering correct")
    else:
        r.fail(f"score_protocol: Gains ({gains_score:.3f}) >= Aave ({aave_score:.3f}) — risk ordering inverted")

    # f. risk_adjusted_apy discounts correctly
    ra = risk_adjusted_apy(10.0, 0.80)
    if abs(ra - 8.0) < 1e-6:
        r.ok("risk_adjusted_apy: 10.0% × 0.80 = 8.0%")
    else:
        r.fail(f"risk_adjusted_apy: expected 8.0, got {ra}")

    # g. enrich_opportunities adds fields and re-sorts by risk_adjusted_apy
    opps = [
        {"label": "Aave",  "apy": 3.5, "tvl_usd": 500_000_000, "protocol_config": {"id": "aave-v3-arbitrum-usdc"}},
        {"label": "Gains", "apy": 6.7, "tvl_usd": 6_000_000,   "protocol_config": {"id": "gains-network-arbitrum-usdc"}},
        {"label": "Morpho","apy": 5.9, "tvl_usd": 13_000_000,  "protocol_config": {"id": "morpho-bbqusdc-arbitrum"}},
    ]
    enriched = enrich_opportunities(opps)

    if all("risk_score" in o and "risk_adjusted_apy" in o for o in enriched):
        r.ok("enrich_opportunities: adds risk_score and risk_adjusted_apy to all opps")
    else:
        r.fail("enrich_opportunities: missing risk_score or risk_adjusted_apy on some opps")

    # Gains has highest raw APY (6.7%) but should NOT be first after risk adjustment
    first = enriched[0]["label"]
    if first != "Gains":
        r.ok(f"enrich_opportunities: re-sorted by risk_adjusted_apy — '{first}' leads (not raw Gains 6.7%)")
    else:
        gains_ra  = next(o["risk_adjusted_apy"] for o in enriched if o["label"] == "Gains")
        others_ra = [o["risk_adjusted_apy"] for o in enriched if o["label"] != "Gains"]
        if gains_ra >= max(others_ra):
            r.ok("enrich_opportunities: Gains leads — risk_adjusted_apy still highest (check scores)")
        else:
            r.fail("enrich_opportunities: Gains (high counterparty risk) still leads after risk adjustment")

    # h. _pick_best_protocol in treasury_agent uses risk_adjusted_apy
    from agents.treasury_agent import TreasuryAgent
    src = inspect.getsource(TreasuryAgent._pick_best_protocol)
    if "risk_adjusted_apy" in src:
        r.ok("TreasuryAgent._pick_best_protocol: sorts by risk_adjusted_apy")
    else:
        r.fail("TreasuryAgent._pick_best_protocol: still sorts by raw apy — RiskModel not integrated")


# ── 13. YieldOracle: ABI decode, enrichment logic, wiring order ──────────────

def check_yield_oracle(r: _Result):
    try:
        from utils.treasury_yield_oracle import (
            enrich_with_onchain_apy, get_aave_supply_apy,
            _RAY, _SPY, _AAVE_POOL, _USDC_ARB,
        )
    except Exception as e:
        r.fail(f"Cannot import treasury_yield_oracle: {e}")
        return

    r.ok("treasury_yield_oracle imports cleanly")

    # a. Constants sanity
    if _RAY == 10 ** 27:
        r.ok(f"YieldOracle: RAY = 1e27 correct")
    else:
        r.fail(f"YieldOracle: RAY = {_RAY} — expected 1e27")

    if _SPY == 365 * 24 * 3600:
        r.ok(f"YieldOracle: SPY = 31536000 correct")
    else:
        r.fail(f"YieldOracle: SPY = {_SPY} — expected 31536000")

    # b. ABI decode: construct a mock response matching the on-chain struct layout
    #    Slot 0: configuration (zeros)
    #    Slot 1: liquidityIndex = 1 RAY
    #    Slot 2: currentLiquidityRate ≈ 3.5% APY in Ray
    #    Formula: rate_per_sec ≈ 0.035/SPY → rate_ray = rate_per_sec * RAY * SPY ≈ 0.035 * RAY
    import math
    target_apy  = 3.5   # %
    # Invert: apy = (1 + r/RAY/SPY)^SPY - 1 → r/RAY = (1+apy)^(1/SPY) - 1 ≈ ln(1+apy)/SPY
    rate_annual = math.log(1 + target_apy / 100)   # ≈ apy for small values
    rate_ray    = int(rate_annual * _RAY)

    mock_bytes = (0).to_bytes(32, "big") + _RAY.to_bytes(32, "big") + rate_ray.to_bytes(32, "big")
    mock_hex   = "0x" + mock_bytes.hex()

    with mock.patch("utils.treasury_yield_oracle._eth_call", return_value=mock_hex):
        try:
            apy = get_aave_supply_apy()
            if abs(apy - target_apy) < 0.1:
                r.ok(f"YieldOracle: ABI decode correct — mocked rate → {apy:.4f}% (expected ≈{target_apy}%)")
            else:
                r.fail(f"YieldOracle: ABI decode off — got {apy:.4f}%, expected ≈{target_apy}%")
        except Exception as e:
            r.fail(f"YieldOracle: get_aave_supply_apy() raised: {e}")

    # c. Sanity filter: implausible value (e.g. 999%) falls back to DeFiLlama
    bad_rate_ray = int(9.99 * _RAY)  # ~999% APY
    bad_bytes = (0).to_bytes(32, "big") + _RAY.to_bytes(32, "big") + bad_rate_ray.to_bytes(32, "big")
    with mock.patch("utils.treasury_yield_oracle._eth_call", return_value="0x" + bad_bytes.hex()):
        opps = [{"apy": 3.0, "apy_defillama": 3.0, "protocol_config": {"id": "aave-v3-arbitrum-usdc"}}]
        enriched = enrich_with_onchain_apy(opps)
        if enriched[0]["apy_source"] == "defillama":
            r.ok("YieldOracle: implausible on-chain APY (999%) rejected → falls back to DeFiLlama")
        else:
            r.fail(f"YieldOracle: sanity filter failed — used {enriched[0]['apy']:.0f}% on-chain APY")

    # d. enrich_with_onchain_apy sets apy_source correctly
    with mock.patch("utils.treasury_yield_oracle._eth_call", return_value=mock_hex):
        opps = [
            {"apy": 3.0, "protocol_config": {"id": "aave-v3-arbitrum-usdc"}},
            {"apy": 6.0, "protocol_config": {"id": "gains-network-arbitrum-usdc"}},
        ]
        enriched = enrich_with_onchain_apy(opps)
        aave_opp  = next(o for o in enriched if o["protocol_config"]["id"] == "aave-v3-arbitrum-usdc")
        gains_opp = next(o for o in enriched if o["protocol_config"]["id"] == "gains-network-arbitrum-usdc")

        if aave_opp.get("apy_source") == "on-chain":
            r.ok("YieldOracle: Aave opp → apy_source='on-chain'")
        else:
            r.fail(f"YieldOracle: Aave opp → apy_source='{aave_opp.get('apy_source')}' (expected 'on-chain')")

        if gains_opp.get("apy_source") == "defillama":
            r.ok("YieldOracle: Gains opp → apy_source='defillama' (no on-chain support)")
        else:
            r.fail(f"YieldOracle: Gains opp → apy_source='{gains_opp.get('apy_source')}' (expected 'defillama')")

        if "apy_defillama" in aave_opp:
            r.ok("YieldOracle: apy_defillama preserved for comparison")
        else:
            r.fail("YieldOracle: apy_defillama field missing — original DeFiLlama value lost")

    # e. Wiring order in treasury_agent: YieldOracle enrichment before risk enrichment
    from agents.treasury_agent import TreasuryAgent
    src = inspect.getsource(TreasuryAgent.get_yield_opportunities)
    oracle_pos = src.find("enrich_with_onchain_apy")
    risk_pos   = src.find("enrich_opportunities")
    if oracle_pos != -1 and risk_pos != -1 and oracle_pos < risk_pos:
        r.ok("TreasuryAgent.get_yield_opportunities: YieldOracle runs before RiskModel (correct order)")
    elif oracle_pos == -1:
        r.fail("TreasuryAgent.get_yield_opportunities: enrich_with_onchain_apy not called")
    else:
        r.fail("TreasuryAgent.get_yield_opportunities: RiskModel runs before YieldOracle — risk scores use stale APY")


# ── 14. AllocationOptimizer: parse, validate, fallback, multi-proposal ────────

def check_allocation_optimizer(r: _Result):
    try:
        from utils.treasury_allocation import AllocationOptimizer, _MIN_ALLOC_USD, _SPLIT_THRESHOLD
    except Exception as e:
        r.fail(f"Cannot import AllocationOptimizer: {e}")
        return

    r.ok("AllocationOptimizer imports cleanly")

    opt = AllocationOptimizer()

    def _make_opp(pid, apy, risk_adj, tranche, chain="Arbitrum", automated=True):
        return {
            "apy":               apy,
            "risk_adjusted_apy": risk_adj,
            "automated":         automated,
            "chain":             chain,
            "tvl_usd":           10_000_000,
            "protocol_config":   {"id": pid, "type": "erc4626", "vault_address": "0x" + "a" * 40, "label": pid},
            "risk_score":        {"overall": 0.80, "label": "MEDIUM-LOW", "tranche": tranche},
        }

    opps = [
        _make_opp("aave-v3-arbitrum-usdc",       3.5, 3.44, "liquidity_reserve"),
        _make_opp("morpho-bbqusdc-arbitrum",      3.95, 3.26, "yield_core"),
        _make_opp("gains-network-arbitrum-usdc",  6.7,  3.92, "opportunistic"),
    ]

    # a. Below split threshold → rule-based single protocol (no LLM)
    result_small = opt.optimize(total_usd=100.0, opportunities=opps)
    if len(result_small) == 1:
        r.ok(f"AllocationOptimizer: ${100} < threshold → single-protocol fallback (no LLM)")
    elif len(result_small) == 0:
        r.fail("AllocationOptimizer: returned empty for $100 (above _MIN_ALLOC_USD)")
    else:
        r.fail(f"AllocationOptimizer: ${100} should be single-protocol, got {len(result_small)} entries")

    # b. Rule-based fallback picks highest risk_adjusted_apy
    if result_small and result_small[0]["protocol_id"] == "gains-network-arbitrum-usdc":
        r.ok("AllocationOptimizer: rule-based picks highest risk_adjusted_apy (Gains 3.92%)")
    elif result_small:
        # Gains is highest risk-adj (3.92 > 3.44 > 3.26)
        r.fail(f"AllocationOptimizer: rule-based picked '{result_small[0]['protocol_id']}' — expected Gains (highest risk-adj APY 3.92%)")

    # c. Below _MIN_ALLOC_USD → empty
    result_tiny = opt.optimize(total_usd=10.0, opportunities=opps)
    if result_tiny == []:
        r.ok(f"AllocationOptimizer: ${10} < _MIN_ALLOC_USD → empty list")
    else:
        r.fail(f"AllocationOptimizer: should return [] for ${10}, got {result_tiny}")

    # d. No automated Arbitrum protocols → empty
    non_arb = [_make_opp("compound-eth", 4.0, 3.5, "yield_core", chain="Ethereum")]
    result_none = opt.optimize(total_usd=500.0, opportunities=non_arb)
    if result_none == []:
        r.ok("AllocationOptimizer: no automated Arbitrum protocols → empty list")
    else:
        r.fail(f"AllocationOptimizer: non-Arbitrum only should return [], got {result_none}")

    # e. _validate_and_build: valid LLM output → correct allocation entries
    llm_output = [
        {"protocol_id": "aave-v3-arbitrum-usdc",      "allocation_pct": 15, "rationale": "liquidity buffer"},
        {"protocol_id": "morpho-bbqusdc-arbitrum",     "allocation_pct": 65, "rationale": "core yield"},
        {"protocol_id": "gains-network-arbitrum-usdc", "allocation_pct": 20, "rationale": "opportunistic"},
    ]
    try:
        validated = opt._validate_and_build(llm_output, 1000.0, opps)
        if len(validated) == 3:
            r.ok("AllocationOptimizer._validate_and_build: 3-way split → 3 entries")
        else:
            r.fail(f"AllocationOptimizer._validate_and_build: expected 3 entries, got {len(validated)}")

        total = sum(a["amount_usd"] for a in validated)
        if abs(total - 1000.0) <= 1.0:
            r.ok(f"AllocationOptimizer._validate_and_build: amounts sum to ${total:.2f} ≈ $1000")
        else:
            r.fail(f"AllocationOptimizer._validate_and_build: amounts sum to ${total:.2f} (expected $1000)")
    except Exception as e:
        r.fail(f"AllocationOptimizer._validate_and_build failed: {e}")

    # f. _validate_and_build: invalid protocol ID filtered out → remaining valid
    bad_llm = [
        {"protocol_id": "fake-protocol-xyz", "allocation_pct": 50, "rationale": "bad"},
        {"protocol_id": "aave-v3-arbitrum-usdc", "allocation_pct": 50, "rationale": "ok"},
    ]
    try:
        validated_bad = opt._validate_and_build(bad_llm, 1000.0, opps)
        if len(validated_bad) == 1 and validated_bad[0]["protocol_id"] == "aave-v3-arbitrum-usdc":
            r.ok("AllocationOptimizer._validate_and_build: invalid protocol ID filtered out")
        else:
            r.fail(f"AllocationOptimizer._validate_and_build: bad ID not filtered correctly: {validated_bad}")
    except Exception as e:
        r.fail(f"AllocationOptimizer._validate_and_build with bad ID raised: {e}")

    # g. LLM mock → end-to-end optimize() with parsed JSON
    llm_json = '[{"protocol_id":"aave-v3-arbitrum-usdc","allocation_pct":15,"rationale":"r1"},{"protocol_id":"morpho-bbqusdc-arbitrum","allocation_pct":65,"rationale":"r2"},{"protocol_id":"gains-network-arbitrum-usdc","allocation_pct":20,"rationale":"r3"}]'
    mock_llm = mock.MagicMock()
    mock_llm.available = True
    mock_llm.analyze_text.return_value = llm_json
    opt._llm = mock_llm
    try:
        result_llm = opt.optimize(total_usd=1000.0, opportunities=opps)
        if len(result_llm) == 3:
            r.ok("AllocationOptimizer.optimize: LLM path → 3 DEPLOY proposals")
        else:
            r.fail(f"AllocationOptimizer.optimize: LLM path → expected 3, got {len(result_llm)}")
        total_llm = sum(a["amount_usd"] for a in result_llm)
        if abs(total_llm - 1000.0) <= 1.0:
            r.ok(f"AllocationOptimizer.optimize: LLM amounts sum correctly (${total_llm:.2f})")
        else:
            r.fail(f"AllocationOptimizer.optimize: LLM amounts sum ${total_llm:.2f} ≠ $1000")
    except Exception as e:
        r.fail(f"AllocationOptimizer.optimize LLM path raised: {e}")

    # h. LLM fails → graceful fallback to single-protocol
    opt._llm = None  # reset to force init path
    failing_llm = mock.MagicMock()
    failing_llm.available = True
    failing_llm.analyze_text.side_effect = RuntimeError("LLM timeout")
    opt._llm = failing_llm
    result_fail = opt.optimize(total_usd=1000.0, opportunities=opps)
    if len(result_fail) == 1:
        r.ok("AllocationOptimizer.optimize: LLM failure → graceful single-protocol fallback")
    else:
        r.fail(f"AllocationOptimizer.optimize: LLM failure should yield 1-entry fallback, got {len(result_fail)}")

    # i. generate_proposals produces multi-proposal output with AllocationOptimizer
    from agents.treasury_agent import TreasuryAgent
    ta_instance = TreasuryAgent()
    if hasattr(ta_instance, '_optimizer'):
        r.ok("TreasuryAgent: has _optimizer instance attribute")
    else:
        r.fail("TreasuryAgent: missing _optimizer attribute — AllocationOptimizer not wired up in __init__")

    src = inspect.getsource(TreasuryAgent.generate_proposals)
    if "yield_balances" in src and "_optimizer" in src:
        r.ok("TreasuryAgent.generate_proposals: uses _optimizer and accepts yield_balances")
    elif "_optimizer" not in src:
        r.fail("TreasuryAgent.generate_proposals: _optimizer not called")
    else:
        r.fail("TreasuryAgent.generate_proposals: yield_balances parameter missing")


# ── 15. Yield diversification: trigger, partial switch_amount_usd, cooldown ──

def check_yield_diversification(r: _Result):
    try:
        from agents.treasury_agent import (
            TreasuryAgent,
            _MAX_SINGLE_CONCENTRATION, _DIVERSIFY_TARGET_PCT,
            _DIVERSIFY_MIN_TOTAL_USD, _DIVERSIFY_COOLDOWN_H,
        )
    except Exception as e:
        r.fail(f"Cannot import diversification constants: {e}")
        return

    agent = TreasuryAgent()

    def _make_opp(pid: str, apy: float, ptype: str = "aave_v3", vault: str | None = None) -> dict:
        cfg: dict = {"id": pid, "type": ptype, "label": pid}
        if vault:
            cfg["vault_address"] = vault
        return {
            "label": pid, "project": pid, "chain": "Arbitrum",
            "apy": apy, "automated": True,
            "protocol_config": cfg,
        }

    # Aave as source (supports immediate_withdraw), Morpho+Gains as destinations
    opps = [
        _make_opp("aave-v3-arbitrum-usdc", 5.0),
        _make_opp("morpho-bbqusdc-arbitrum", 6.0, "erc4626", "0x" + "7" * 40),
        _make_opp("gains-network-arbitrum-usdc", 6.7, "erc4626", "0x" + "d" * 40),
    ]

    # Case A: 100% concentration ($2100 Aave) → should trigger (Aave supports immediate_withdraw)
    balances_a = {"aave-v3-arbitrum-usdc": 2100.0, "morpho-bbqusdc-arbitrum": 0.0}
    result_a, notifs_a = agent._check_yield_diversification(opps, balances_a, [])
    div_a = [p for p in result_a if p.get("type") == "YIELD_SWITCH" and p.get("diversification")]
    if div_a:
        r.ok(f"_check_yield_diversification: triggers at 100% concentration (> {_MAX_SINGLE_CONCENTRATION:.0f}% threshold)")
        prop = div_a[0]
        if prop.get("status") == "APPROVED":
            r.ok("_check_yield_diversification: proposal auto-status=APPROVED")
        else:
            r.fail(f"_check_yield_diversification: expected APPROVED, got {prop.get('status')}")
        sw_amt = prop.get("switch_amount_usd", 0)
        expected_move = 2100.0 - 2100.0 * _DIVERSIFY_TARGET_PCT / 100
        if abs(sw_amt - expected_move) <= 5.0:
            r.ok(f"_check_yield_diversification: switch_amount_usd=${sw_amt:.0f} ≈ expected ${expected_move:.0f}")
        else:
            r.fail(f"_check_yield_diversification: switch_amount_usd=${sw_amt:.0f}, expected ≈${expected_move:.0f}")
        if prop.get("amount_usd") == 2100.0:
            r.ok("_check_yield_diversification: amount_usd=full source balance (for reference)")
        else:
            r.fail(f"_check_yield_diversification: amount_usd should be full balance 2100, got {prop.get('amount_usd')}")
        if notifs_a:
            r.ok("_check_yield_diversification: notification queued (not sent)")
        else:
            r.fail("_check_yield_diversification: expected notification text in return tuple")
    else:
        r.fail("_check_yield_diversification: should trigger at 100% concentration but did not")

    # Case A2: 100% concentration ($2100 Gains) → no AUTO switch (immediate_withdraw=false,
    # epoch-based), but a MANUAL_ACTION_REQUIRED alert + notification must be emitted so the
    # overweight isn't silently swallowed.
    balances_a2 = {"gains-network-arbitrum-usdc": 2100.0, "aave-v3-arbitrum-usdc": 0.0}
    result_a2, notifs_a2 = agent._check_yield_diversification(opps, balances_a2, [])
    auto_div_a2 = [p for p in result_a2 if p.get("type") == "YIELD_SWITCH"
                   and p.get("diversification") and p.get("status") == "APPROVED"]
    manual_a2 = [p for p in result_a2 if p.get("status") == "MANUAL_ACTION_REQUIRED"]
    if not auto_div_a2:
        r.ok("_check_yield_diversification: Gains Network not auto-switched (immediate_withdraw=false)")
    else:
        r.fail("_check_yield_diversification: Gains Network auto-diversified despite immediate_withdraw=false")
    if manual_a2 and notifs_a2:
        r.ok("_check_yield_diversification: Gains overweight emits MANUAL_ACTION_REQUIRED alert + notification")
    else:
        r.fail("_check_yield_diversification: expected MANUAL_ACTION_REQUIRED alert for epoch-based overweight")

    # Case B: 70% concentration ($1400 Aave, $600 Morpho) → below threshold, no trigger
    balances_b = {"aave-v3-arbitrum-usdc": 1400.0, "morpho-bbqusdc-arbitrum": 600.0}
    result_b, _ = agent._check_yield_diversification(opps, balances_b, [])
    div_b = [p for p in result_b if p.get("type") == "YIELD_SWITCH" and p.get("diversification")]
    if not div_b:
        r.ok(f"_check_yield_diversification: no trigger at 70% concentration (≤ {_MAX_SINGLE_CONCENTRATION:.0f}%)")
    else:
        r.fail("_check_yield_diversification: triggered below concentration threshold")

    # Case C: total yield < minimum → no trigger even at 100%
    balances_c = {"aave-v3-arbitrum-usdc": 100.0, "morpho-bbqusdc-arbitrum": 0.0}
    result_c, _ = agent._check_yield_diversification(opps, balances_c, [])
    div_c = [p for p in result_c if p.get("type") == "YIELD_SWITCH" and p.get("diversification")]
    if not div_c:
        r.ok(f"_check_yield_diversification: no trigger when total yield ${sum(balances_c.values()):.0f} < ${_DIVERSIFY_MIN_TOTAL_USD:.0f}")
    else:
        r.fail("_check_yield_diversification: triggered below minimum total yield (gas not justified)")

    # Case D: YIELD_SWITCH already in-flight → skip (prevents overlap with APY-driven switch)
    in_flight = [{"type": "YIELD_SWITCH", "status": "SWITCHING"}]
    result_d, _ = agent._check_yield_diversification(opps, balances_a, in_flight)
    div_d = [p for p in result_d if p.get("type") == "YIELD_SWITCH" and p.get("diversification")]
    if not div_d:
        r.ok("_check_yield_diversification: skips when YIELD_SWITCH is already SWITCHING")
    else:
        r.fail("_check_yield_diversification: created proposal while another switch in-flight")

    # Case E: cooldown — recent diversification proposal → no new trigger
    from datetime import datetime
    recent_prop = {
        "type": "YIELD_SWITCH", "diversification": True, "status": "DEPLOYED",
        "id": "TRD_test", "created_at": datetime.utcnow().isoformat(),
    }
    result_e, _ = agent._check_yield_diversification(opps, balances_a, [recent_prop])
    div_e = [p for p in result_e if p.get("type") == "YIELD_SWITCH" and p.get("diversification") and p.get("id") != "TRD_test"]
    if not div_e:
        r.ok(f"_check_yield_diversification: cooldown respected — no new proposal within {_DIVERSIFY_COOLDOWN_H}h")
    else:
        r.fail("_check_yield_diversification: created new diversification proposal during cooldown window")

    # Case F: _check_yield_diversification wired into run() and run_fast()
    import inspect
    src_run = inspect.getsource(TreasuryAgent.run)
    src_fast = inspect.getsource(TreasuryAgent.run_fast)
    if "_check_yield_diversification" in src_run:
        r.ok("TreasuryAgent.run: calls _check_yield_diversification")
    else:
        r.fail("TreasuryAgent.run: _check_yield_diversification not wired in")
    if "_check_yield_diversification" in src_fast:
        r.ok("TreasuryAgent.run_fast: calls _check_yield_diversification")
    else:
        r.fail("TreasuryAgent.run_fast: _check_yield_diversification not wired in")
    if "_diversify_notifs" in src_run:
        r.ok("TreasuryAgent.run: sends _diversify_notifs after _save_proposals")
    else:
        r.fail("TreasuryAgent.run: _diversify_notifs not sent after save")


# ── Runner ────────────────────────────────────────────────────────────────────

def run_all_checks() -> bool:
    r = _Result()

    logger.info("--- 1/12  Imports ---")
    check_imports(r)

    logger.info("--- 2/12  Signatures ---")
    check_signatures(r)

    logger.info("--- 3/12  generate_proposals() logic ---")
    check_generate_proposals_logic(r)

    logger.info("--- 4/12  advance_proposal() protocol routing ---")
    check_advance_proposal_routing(r)

    logger.info("--- 5/12  Protocol config JSON ---")
    check_protocol_config(r)

    logger.info("--- 6/12  Drawdown includes Aave balance ---")
    check_drawdown_includes_aave(r)

    logger.info("--- 7/12  Swarm integration (main.py wiring) ---")
    check_swarm_integration(r)

    logger.info("--- 8/12  _check_yield_switch() trigger logic ---")
    check_yield_switch_logic(r)

    logger.info("--- 9/12  YIELD_SWITCH APPROVED→SWITCHING routing ---")
    check_yield_switch_approved_routing(r)

    logger.info("--- 10/12 SWITCHING→DEPLOYED routing ---")
    check_yield_switch_switching_routing(r)

    logger.info("--- 11/15 Funding Harvest methods, constants, guards, wiring ---")
    check_funding_harvest(r)

    logger.info("--- 12/15 RiskModel: profiles, weights, scoring, integration ---")
    check_risk_model(r)

    logger.info("--- 13/15 YieldOracle: ABI decode, enrichment, wiring order ---")
    check_yield_oracle(r)

    logger.info("--- 14/15 AllocationOptimizer: parse, validate, fallback, multi-proposal ---")
    check_allocation_optimizer(r)

    logger.info("--- 15/15 Yield diversification: trigger, partial switch_amount_usd, cooldown ---")
    check_yield_diversification(r)

    logger.info(f"\nResult: {r.passed} passed, {len(r.failures)} failed")
    for f in r.failures:
        logger.error(f"  -> {f}")
    return len(r.failures) == 0


if __name__ == "__main__":
    project_root = os.getcwd()
    sys.path.insert(0, project_root)
    logger.info("PRE-FLIGHT: Treasury system validation")

    ok = run_all_checks()

    if ok:
        logger.info("PRE-FLIGHT TREASURY CHECK PASSED")
        sys.exit(0)
    else:
        logger.error("PRE-FLIGHT TREASURY CHECK FAILED — fix errors before deploying")
        sys.exit(1)
