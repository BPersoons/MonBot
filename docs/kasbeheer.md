# Kasbeheer (Treasury)

> Letterlijk verplaatst uit CLAUDE.md op 2026-09-15 (S3: CLAUDE.md afslanken). De inhoud hieronder is niet herschreven; correcties die sindsdien gelden staan in dit kader.
> 
> - YIELD_SWITCH beslist op **risico-gecorrigeerde** APY (`risk_adjusted_apy`), niet op ruwe APY, met een spread van 1,5pp. De tekst hieronder zegt "APY".
> - Fluid fUSDC (Arbitrum, ERC-4626) is op 2026-09-15 toegevoegd aan `_TRACKED`, `treasury_protocols.json` en `_PROFILES` (nog niet gedeployed; A2-review). Verwacht effect: diversificatie verschuift ~35% van Aave naar Fluid.
> - `tests/pre_flight/check_treasury.py`: 129 controles (was 124).
> - Integriteit van renteprotocollen (share price, liquidityIndex, saldo, USDC-peg) wordt bewaakt door SwarmMonitor Check 24 (`utils/verliesbewaking.py`).
> - ⚠️ **Dry-run was schijnveiligheid (gevonden 2026-09-15, gerepareerd in `5c636a8`, deploy na A1-GO).** De dry-run van supply/deposit stond vóór de approve en revertte daardoor altijd; dat bleef onzichtbaar omdat `_rpc` reverts als "RPC unavailable" inslikte. Nu: revert raiset direct, dry-run ná approve + allowance-check, revert → approve intrekken. Verder: cap max 65% per niet-benchmark-protocol (strikte on-chain saldi), retry-rem na 2 mislukte deploys/switches in 24u, diversificatie vanuit Aave neemt alleen het deelbedrag op, volledige Aave-opname met `uint256.max`.

## Treasury System

The treasury acts as a fully autonomous capital allocator — distributing USDC across yield instruments based on risk/reward, market regime, and liquidity needs.

### Capital Locations
- **Hyperliquid (HL)** — perps trading margin. Target: 30% (WR ≥ 45% → +10pp, WR < 30% → -10pp).
- **Yield protocols** — deployed on Arbitrum, target ~70%. Allocated by `_pick_best_protocol()`.
- **Treasury wallet** (`0x4144e0b5…`) — staging area; USDC here triggers automatic DEPLOY_YIELD proposal.

### Tranche Model
| Tranche | Target | Instruments | Liquidity |
|---|---|---|---|
| Liquidity reserve | ~15% | Aave v3 | Instant |
| Yield core | ~65% | Morpho, GMX GM | 1–3 days |
| Opportunistic | ~20% | HL Funding Harvest, Pendle PT | Position-dependent |

### Protocol Executors
```
TreasuryAgent
  ├── YieldOracle         — on-chain Aave APY via Pool.getReserveData (live)
  ├── RiskModel           — per-protocol risk score (SC/liquidity/counterparty) (live)
  ├── AllocationOptimizer — Gemini LLM tranche split (live, fallback rule-based)
  └── AaveExecutor (live, pool 0x794a61358D…)
      MorphoExecutor (live, BBQUSDC 0x7e97… + GTUSDCC 0x7c57…)
      GainsExecutor (live, gUSDC 0xd3443ee…, ERC-4626)
      FundingHarvestor (live, BTC/ETH HL short)
      PendleExecutor (Fase 3, custom AMM)
```

### Roadmap
- **Fase 1–2** *(voltooid 2026-05-24)*: Morpho ✓ · YIELD_SWITCH ✓ · Gains gUSDC ✓ · FundingHarvest ✓ · RiskModel ✓ · YieldOracle ✓ · AllocationOptimizer ✓
- **Fase 3** *(next)*: Pendle PT executor · Volledig geautomatiseerde multi-protocol rebalancing

### Proposal State Machine
```
PENDING → APPROVED → WITHDRAWING → BRIDGED → DEPLOYED
                   → NEEDS_MANUAL_WITHDRAWAL
                   → MONITORING (FUND_TRADING only) → COMPLETED
REBALANCE: APPROVED → REBALANCING → BRIDGE_BACK_NEEDED → (manual HL deposit)
YIELD_SWITCH: APPROVED (auto) → SWITCHING → DEPLOYED
MANUAL_ACTION_REQUIRED: terminal/informational — no executor acts on it
```
- `run()` every 60 cycles (incl. cycle 1 startup): full DeFiLlama fetch, generate proposals, advance state.
- `run_fast()` every 5 cycles: execution-only pass using cached yield data. Has its OWN local `active` set — add any new proposal status to BOTH `execute_approved_proposals()` AND `run_fast()` local active.
- **YIELD_SWITCH**: fully automatic. Triggered when best automated Arbitrum APY > deployed + 1.5% and balance ≥ $100. One switch at a time. Returns `(proposals, notif_texts)` tuple — callers send Telegram AFTER `_save_proposals()`.
- **YIELD diversification**: automatic. Triggered when single protocol > 80% of yield and total yield > $150. Partial withdrawal to bring source to 65%. `switch_amount_usd` field (not `amount_usd`). Cooldown 12h. Shares YIELD_SWITCH in-flight guard.
- **MANUAL_ACTION_REQUIRED**: emitted when overweight protocol is epoch-based (`immediate_withdraw=false`) — can't auto-move. Fires Telegram alert once per cooldown window. Prefix `TRDM_`. Resolve by manually withdrawing.

### Protocol routing
Use `protocol_type` field (`aave_v3`/`erc4626`/`compound_v3`), not the `protocol` label (can mismatch from pre-fix proposals).

### Pre-flight tests
`tests/pre_flight/check_treasury.py` — 15 checks, 124 assertions, wired into `check_pipeline.py`. Must pass before deploy.

### Treasury Pitfalls

- **False drawdown halt**: `RiskManager.check_portfolio_drawdown()` calls `get_total_yield_balance()` to sum ALL automated protocols. Refactoring to `get_aave_balance()` only makes yield capital look like a drawdown.
- **Curve never good**: `_pick_best_protocol()` hardcoded to never recommend non-Arbitrum non-automated protocols. Do not revert.
- **PENDING TTL**: 6h (`_PROPOSAL_TTL_H`). APPROVED/DEPLOYED/FAILED kept forever in history.
- **`source_treasury` skips bridge**: Goes directly to BRIDGED — USDC already on Arbitrum.
- **Morpho vaults**: Both `automated=true` in `config/treasury_protocols.json`. `vault_address=null` → FAILED proposals.
- **TVL thresholds**: Tier-based (`stable=$5M, medium=$10M, exposure=$50M`). GTUSDCC has $3.2M TVL < $5M threshold — may not appear in opportunities.
- **YIELD_SWITCH SWITCHING**: Must be in `active` set in BOTH `execute_approved_proposals()` AND `run_fast()` local active or switches stall silently.
- **ERC-4626 selector**: `0x6e553f65` = `deposit(uint256,address)`. Compound v3: `0xf2b9fdb8` = `supply(address,uint)`. ERC-4626 partial withdrawal: `0xb460af94` = `withdraw(assets)`.
- **FUND_TRADING proposals**: Informational top-up reminders. Auto-complete when HL balance rises ≥ 90% of proposal amount. User bridges manually via HL web app.
- **FUND_SLEEVE proposals (meta-allocator, G2)**: autonomous funding of the Thematic Exposure Sleeve's separate wallet (`0xBd6c`). Self-contained in `TreasuryAgent` (NOT via `treasury_executor.advance_proposal`): `_check_sleeve_funding()` generates when sleeve < `sleeve_trigger_frac`×target (target = min(`sleeve_cap_usd`, `sleeve_target_pct`% of grand_total)); `_execute_fund_sleeve()` (in run() + run_fast()) runs APPROVED via `_master_send_usdc()` = `sendAsset` master(0x92D4)→sleeve spot→spot with the MASTER key (`_master_signing_client`, HL_VAULT_*). Approval reuses `/approve <id>`; 1st top-up PENDING, then `sleeve_first_topup_approved` flips → auto. **HL transfer rules learned 2026-07-23**: cross-account sends MUST go `sourceDex="spot"` (perp source → "only supports sending assets through spot"); `usdClassTransfer` is disabled on unified accounts; the sleeve's own spot→xyz sweep (`ThematicExposureLab._sweep_idle_to_xyz`, G0) then deploys it to the xyz builder-dex. Config/caps in `config/treasury_allocation.json` (`sleeve_*`). **G3 reverse — SLEEVE_REBALANCE**: `_check_sleeve_rebalance()` pulls excess idle capital (`withdrawable_total`, never position margin) back to the master when sleeve > `sleeve_rebalance_frac`×target (1.40) or > cap; auto-APPROVED (de-risking direction, Telegram-notified); `_execute_sleeve_rebalance()` = `_sleeve_send_to_master()` two hops with the SLEEVE key (xyz→spot, then sleeve spot→master spot). All sendAsset signing shares the `TreasuryAgent._send_asset()` static helper.
- **RPC for Arbitrum**: `https://arbitrum.gateway.tenderly.co` — only working public RPC from GCP. drpc.org/meowrpc.com/arb1.arbitrum.io → 403. ankr requires key. zan.top rate-limits. Retry-with-backoff in `_rpc()` (2s, 4s). 3s sleep between approve + supply in `_deposit_aave()`.
- **HL bridge**: Bridge2 (`0x2Df1c51E09aECF9cacB7bc98cB1742757f163dF7`), selector `0xb30b5bce`. Signature tuple order: `(uint256 r, uint256 s, uint8 v)` NOT `(v,r,s)`. EIP-2612 permit, no separate approve TX.
- **EIP-2612 USDC on Arbitrum**: `name="USD Coin"`, `version="2"`, `chainId=42161`, `verifyingContract=0xaf88d065...`. nonces selector=`0x7ecebe00`. Sign: `Account.sign_typed_data(pk, full_message={...})`. r/s are `int` — use `_u256()`.
- **Bridge step 1 skippable**: If USDC already on vault Arb (from failed prior attempt), step 1 skipped, full balance bridged — auto-recovers stuck funds.
- **Spurious YIELD_SWITCH on missing APY**: If deployed protocol absent from cached opps, `current_apy` defaults 0.0 → triggers switch. Skip switch when `pid not in apy_by_id`.
- **Morpho BBQUSDC deposit cap**: Large deposits ($1,670+) revert. Route large amounts to Aave v3. Also $214–220 deposits FAILED (RPC 403 on dry-run + revert) — watch retry behaviour.
- **Liquidity guard — epoch-based vaults never auto-deposit destination**: Protocols with `immediate_withdraw=false` (Gains gUSDC) excluded from ALL automated deployment paths: `_pick_best_protocol()`, `AllocationOptimizer.optimize()`, `_check_yield_switch()`, `_check_yield_diversification()`. Can still withdraw manually and read balance. New protocols: set `immediate_withdraw` honestly in config.
- **SWITCHING uses `switch_amount_usd`**: For partial switches, `amount_usd` = full source balance; only `switch_amount_usd` was withdrawn. Handler: `switch_amt = float(proposal.get("switch_amount_usd") or proposal.get("amount_usd", 0))`. Deposit capped at `switch_amt * 1.05`.
- **GMX GM / Gains gUSDC**: Single-sided USDC counterparty risk — vault absorbs losses when traders win. Statistically favourable long-term.
- **Funding Harvest**: Min rate `_HARVEST_MIN_RATE_8H=0.01%/8h`. BTC/ETH only (`_HARVEST_ALLOWED_ASSETS`). Max notional $150. Auto-closes after 48h or rate < `0.003%/8h`. State survives restarts via `treasury_harvest.json`.
- **Harvest/sleeve guard — er zijn VIER plekken, niet drie**: `"harvest": True` én `"thematic_exposure": True` moeten worden overgeslagen in (1) de backfill-pass `execution_agent.py:153`, (2) de startup-sync `execution_agent.py:284`, (3) `strategy_manager.evaluate_position()` — én (4) **`main.py`'s Pass 3 RECONCILE** (~regel 989). Pre-flight check 11 verifieert alleen de eerste drie.

  > ⚠️ Deze regel noemde vroeger "Pass 3 (EXTERNAL_CLOSURE sync)" als één van drie, en dat las als de startup-sync in `execution_agent`. De gelijknamige pass in `main.py` had daardoor **nooit** een guard. Gevolg (ontdekt 2026-08-12): de dip-koper draait op een aparte wallet `0xBd6c`, terwijl `hl_pos_map` van de hoofdwallet `0x92D4` komt — zijn posities staan daar dus per definitie nooit in, en werden sinds de wallet-splitsing van 2026-07-18 **allemaal 5 minuten na aankoop als valse `EXTERNAL_CLOSURE` weggeschreven** met verzonnen exitprijs en nep-P&L. Geen geld verloren (Pass 3 stuurt geen order), maar de handelshistorie bestond niet én ProjectLead's dubbele-positie-guard — die op een OPEN regel matcht — werkte bijna vier weken niet. De rente-oogst ontsnapte alleen omdat die wél op de hoofdwallet draait. **Bij een nieuwe guard: tel de plekken in de code, niet in de documentatie.**
- **Pendle PT**: Custom AMM, not ERC-4626. Requires `swapExactTokenForPt()`. Must hold to maturity to redeem at par.

### Fase 2 Components

**`utils/treasury_risk.py` — RiskModel**
- 5 dimensions: sc(0.25), liquidity(0.25), counterparty(0.30), maturity(0.10), tvl(0.10). Must sum 1.0.
- `enrich_opportunities(opps)` adds `risk_score` dict + `risk_adjusted_apy`, re-sorts by risk-adjusted APY.
- New protocol without `_PROFILES` entry gets `_UNKNOWN_PROFILE` (conservative 0.50) and ranks below well-profiled ones.

**`utils/treasury_yield_oracle.py` — YieldOracle**
- `Aave v3 Pool.getReserveData(USDC)` — selector `0x35ea6a75`. `currentLiquidityRate` at ABI slot 2 (bytes 64–95, third field). APY = `((1 + rate_ray/RAY/SPY)^SPY - 1) * 100`. RAY=1e27, SPY=31536000. Sanity: [0%, 50%].
- Must run BEFORE RiskModel enrichment (pre-flight check 13 verifies). Wrong slot → nonsensical APY caught by sanity filter.

**`utils/treasury_allocation.py` — AllocationOptimizer**
- Gemini LLM returns `[{protocol_id, allocation_pct, rationale}]`. Below $150: skip LLM, use best risk-adjusted protocol. Min alloc $50/tranche.
- Produces multiple DEPLOY_YIELD proposals (one per tranche), IDs `TRP_{now}_{idx}`. In-flight check blocks new proposals while ANY tranche is executing.
- `yield_balances` must be passed from `run()` into `generate_proposals()`. Fast path uses `_pick_best_protocol()` (no LLM).
