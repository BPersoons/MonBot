"""
TreasuryAgent — capital efficiency monitor.

Runs every 60 cycles (~1 hour). Responsibilities:
- Track idle USDC on Hyperliquid (free margin not used by open trades)
- Fetch live APY from Aave v3, Morpho, Compound on Arbitrum via DeFiLlama
- Generate human-reviewable proposals: "bridge $X to Aave @ Y% APY"
- Send Telegram alert for new proposals
- Save state to treasury_state.json for dashboard

NO automatic execution — all proposals require human approval.
Bridge path: HL → Arbitrum (native HL bridge) → Aave v3 Arbitrum.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("TreasuryAgent")


def _telegram_token() -> str:
    v = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not v:
        try:
            from utils.gcp_secrets import get_secret
            v = get_secret("TELEGRAM_BOT_TOKEN") or ""
        except Exception:
            pass
    return v


def _telegram_chat_id() -> str:
    v = os.getenv("TELEGRAM_CHAT_ID", "")
    if not v:
        try:
            from utils.gcp_secrets import get_secret
            v = get_secret("TELEGRAM_CHAT_ID") or ""
        except Exception:
            pass
    return v


# DeFiLlama pool filters: (project, chain, symbol, label, risk_tier, min_tvl_usd)
# risk_tier: "stable" | "medium" | "exposure"
# min_tvl_usd: filters out dust pools so we always hit the main pool
_TRACKED = [
    # ── Tier 1: Pure stablecoins — smart contract risk only ───────────────────
    ("aave-v3",     "Arbitrum", "USDC",  "Aave v3 · Arbitrum · USDC",          "stable"),
    ("aave-v3",     "Arbitrum", "USDT",  "Aave v3 · Arbitrum · USDT",          "stable"),
    ("morpho-blue", "Arbitrum", "USDC",  "Morpho · Arbitrum · USDC",           "stable"),
    ("compound-v3",   "Arbitrum", "USDC",  "Compound v3 · Arbitrum · USDC",       "stable"),
    ("gains-network", "Arbitrum", "USDC",  "Gains Network · gUSDC · Arbitrum",  "stable"),
    ("aave-v3",       "Ethereum", "USDC",  "Aave v3 · Ethereum · USDC",          "stable"),
    ("aave-v3",     "Ethereum", "USDT",  "Aave v3 · Ethereum · USDT",          "stable"),
    ("spark",       "Ethereum", "USDS",  "Spark · Ethereum · USDS (MakerDAO)", "stable"),
    ("spark",       "Ethereum", "DAI",   "Spark · Ethereum · DAI",             "stable"),
    # ── Tier 2: Delta-neutral — funding rate mechanism, higher yield ──────────
    ("ethena-usde", "Ethereum", "SUSDE", "Ethena · sUSDe (delta-neutraal)",    "medium"),
    ("curve-dex",   "Ethereum", "crvUSD","Curve · crvUSD",                     "medium"),
    # ── Tier 3: Price exposure — only relevant if you already hold the asset ──
    ("lido",        "Ethereum", "stETH", "Lido · stETH (ETH staking)",         "exposure"),
    ("aave-v3",     "Ethereum", "WBTC",  "Aave v3 · Ethereum · WBTC lending",  "exposure"),
]

# Minimum TVL per risk tier — uniform standard so all protocols compete on equal footing.
# Add a new _TRACKED entry without worrying about the threshold; it derives from the tier.
_MIN_TVL_BY_TIER = {
    "stable":   5_000_000,   # $5M — any reputable stable protocol is liquid enough
    "medium":  10_000_000,   # $10M — extra buffer for delta-neutral / less-known pools
    "exposure": 50_000_000,  # $50M — price-risk instruments require deeper liquidity
}

# Thresholds (deployment)
_YIELD_SWITCH_MIN_SPREAD = 1.5   # % APY improvement needed to trigger an automatic yield switch
_YIELD_SWITCH_MIN_USD    = 100   # minimum deployed balance worth switching (gas cost break-even)

# Thresholds
_IDLE_DEPLOY_PCT       = 0.60   # free margin > 60% of HL balance → consider deploying
_IDLE_TARGET_PCT       = 0.35   # after deployment: keep 35% of HL balance as buffer
_MIN_DEPLOY_USD        = 100    # minimum worth bridging
_MIN_APY               = 3.0    # minimum APY to bother recommending
_PROPOSAL_TTL_H        = 6      # hours before refreshing a PENDING proposal
_REBALANCE_TRIGGER_PCT = 0.25   # HL free margin < 25% of total capital → rebalance
_REBALANCE_MIN_USD     = 50     # minimum Aave balance worth reclaiming
_HL_EXCESS_MIN_USD     = 100    # minimum HL excess worth withdrawing to yield

# Yield diversification thresholds
_MAX_SINGLE_CONCENTRATION = 80.0   # % above which auto-diversification triggers
_DIVERSIFY_TARGET_PCT     = 65.0   # target max % for source protocol after diversification
_DIVERSIFY_MIN_TOTAL_USD  = 150.0  # min total yield before diversifying (gas efficiency)
_DIVERSIFY_COOLDOWN_H     = 12     # hours between diversification proposals


class TreasuryAgent:
    def __init__(self, exchange_client=None, db_client=None):
        self.exchange_client = exchange_client
        self.db_client = db_client
        try:
            from utils.treasury_allocation import AllocationOptimizer
            self._optimizer = AllocationOptimizer()
        except Exception as e:
            logger.warning(f"TreasuryAgent: AllocationOptimizer init failed ({e}) — will use rule-based fallback")
            self._optimizer = None

    # ── HL snapshot ───────────────────────────────────────────────────────────

    def get_hl_snapshot(self) -> dict:
        if not self.exchange_client:
            return {"error": "no exchange client", "balance": 0, "free_margin": 0, "idle_pct": 0}
        try:
            balance  = self.exchange_client.get_balance()
            free     = self.exchange_client.get_free_margin()
            deployed = max(0.0, balance - free)
            idle_pct = free / balance * 100 if balance > 0 else 0.0
            return {
                "balance":         round(balance,  2),
                "free_margin":     round(free,     2),
                "deployed_margin": round(deployed, 2),
                "idle_pct":        round(idle_pct, 1),
            }
        except Exception as e:
            logger.error(f"HL snapshot failed: {e}")
            return {"error": str(e), "balance": 0, "free_margin": 0, "idle_pct": 0}

    # ── Protocol config ───────────────────────────────────────────────────────

    def _load_protocol_config(self) -> list[dict]:
        try:
            with open("config/treasury_protocols.json") as f:
                return json.load(f).get("protocols", [])
        except Exception:
            return []

    # ── Cached opportunities ──────────────────────────────────────────────────

    def _load_cached_opportunities(self) -> list[dict]:
        try:
            with open("treasury_state.json") as f:
                return json.load(f).get("opportunities", [])
        except Exception:
            return []

    # ── Allocation config ─────────────────────────────────────────────────────

    def _load_allocation_config(self) -> dict:
        defaults = {
            "target_trade_pct":      30,
            "rebalance_drift_pct":   10,
            "min_hl_buffer_usd":    200,
            "adapt_to_performance": True,
            "perf_lookback_trades":  30,
            "perf_high_wr_threshold": 45,
            "perf_high_wr_boost_pp":  10,
            "perf_low_wr_threshold":  30,
            "perf_low_wr_reduce_pp":  10,
        }
        try:
            with open("config/treasury_allocation.json") as f:
                defaults.update(json.load(f))
        except Exception:
            pass
        return defaults

    def _get_recent_wr(self, lookback: int = 30) -> float | None:
        """Win rate of last N closed trades. Returns None if insufficient data."""
        try:
            with open("trade_log.json") as f:
                raw = json.load(f)
            trades = list(raw.values()) if isinstance(raw, dict) else raw
            closed = [
                t for t in trades
                if t.get("status") == "CLOSED"
                and t.get("pnl") is not None
                and not (t.get("id", "")).startswith("RECOVERED_")
            ]
            closed.sort(key=lambda t: t.get("exit_time") or t.get("updated_at") or "")
            recent = closed[-lookback:]
            if len(recent) < 5:
                return None
            wins = sum(1 for t in recent if (t.get("pnl") or 0) > 0)
            return wins / len(recent) * 100
        except Exception:
            return None

    def _read_current_regime(self) -> str:
        """Read last detected market regime from market_regime.json (written by ResearchAgent)."""
        try:
            with open("market_regime.json") as f:
                return json.load(f).get("regime", "NEUTRAL")
        except Exception:
            return "NEUTRAL"

    def _compute_target_allocation(self, total_portfolio: float) -> dict:
        """
        Returns target HL (trading) vs yield allocation.
        Base: target_trade_pct from config.
        Adapts: strong WR → boost trading %, weak WR → reduce it.
        Adapts: RANGING market → reduce HL target by regime_adj_pp (floor: min_trade_pct).
        When RANGING the market isn't trading — capital earns more in yield than sitting idle.
        """
        cfg = self._load_allocation_config()
        base_pct = cfg["target_trade_pct"]
        effective_pct = base_pct
        reason_parts = [f"basis {base_pct}% trading"]

        if cfg.get("adapt_to_performance"):
            wr = self._get_recent_wr(cfg.get("perf_lookback_trades", 30))
            if wr is not None:
                high_thr = cfg.get("perf_high_wr_threshold", 45)
                low_thr  = cfg.get("perf_low_wr_threshold",  30)
                if wr >= high_thr:
                    boost        = cfg.get("perf_high_wr_boost_pp", 10)
                    effective_pct = min(effective_pct + boost, 60)
                    reason_parts.append(f"WR={wr:.0f}% > {high_thr}% → +{boost}pp boost")
                elif wr < low_thr:
                    reduce       = cfg.get("perf_low_wr_reduce_pp", 10)
                    effective_pct = max(effective_pct - reduce, 10)
                    reason_parts.append(f"WR={wr:.0f}% < {low_thr}% → -{reduce}pp reductie")
                else:
                    reason_parts.append(f"WR={wr:.0f}% (neutraal)")

        if cfg.get("adapt_to_regime", True):
            regime = self._read_current_regime()
            regime_adjs = cfg.get("regime_adj_pp", {"RANGING": -10, "VOLATILE": 0, "TRENDING_BULL": 0, "TRENDING_BEAR": 0})
            adj = regime_adjs.get(regime, 0)
            if adj != 0:
                min_pct = cfg.get("min_trade_pct", 15)
                effective_pct = max(effective_pct + adj, min_pct)
                reason_parts.append(f"regime={regime} → {'+' if adj > 0 else ''}{adj}pp")

        target_trade = round(max(
            total_portfolio * effective_pct / 100,
            cfg.get("min_hl_buffer_usd", 200),
        ), 2)
        target_yield = round(max(total_portfolio - target_trade, 0), 2)

        return {
            "target_trade_usd":    target_trade,
            "target_yield_usd":    target_yield,
            "effective_trade_pct": effective_pct,
            "reason":              " | ".join(reason_parts),
        }

    # ── Yield opportunities ───────────────────────────────────────────────────

    def get_yield_opportunities(self) -> list[dict]:
        """Fetch live APY from DeFiLlama, enriched with protocol config (automated flag, addresses)."""
        try:
            req = urllib.request.Request(
                "https://yields.llama.fi/pools",
                headers={"User-Agent": "AgentTrader/1.0"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                pools = json.loads(resp.read()).get("data", [])
        except Exception as e:
            logger.warning(f"DeFiLlama fetch failed: {e}")
            return []

        protocol_configs = self._load_protocol_config()

        results = []
        for project, chain, sym, label, risk_tier in _TRACKED:
            min_tvl = _MIN_TVL_BY_TIER.get(risk_tier, 5_000_000)
            matches = [
                p for p in pools
                if (p.get("project") or "").lower() == project
                and (p.get("chain")   or "").lower() == chain.lower()
                and sym.lower() in (p.get("symbol") or "").lower()
                and (p.get("tvlUsd") or 0) >= min_tvl
            ]
            if not matches:
                continue
            best_pool = max(matches, key=lambda p: p.get("tvlUsd") or 0)
            apy       = round(best_pool.get("apy") or 0, 2)
            pool_id   = best_pool.get("pool", "")

            # Match to protocol config — by pool_id first, then project+chain
            cfg = next((
                c for c in protocol_configs
                if (c.get("defillama_pool_id") and c["defillama_pool_id"] == pool_id)
                or (
                    c.get("defillama_project", "").lower() == project
                    and c.get("defillama_chain", "").lower() == chain.lower()
                    and not c.get("defillama_pool_id")  # don't match specific-pool configs generically
                )
            ), None)

            automated = bool(cfg and cfg.get("automated") and (
                cfg.get("pool_address") or cfg.get("vault_address") or cfg.get("comet_address")
            ))

            results.append({
                "label":           label,
                "project":         project,
                "chain":           chain,
                "risk_tier":       risk_tier,
                "apy":             apy,
                "apy_base":        round(best_pool.get("apyBase")   or 0, 2),
                "apy_reward":      round(best_pool.get("apyReward") or 0, 2),
                "tvl_usd":         int(best_pool.get("tvlUsd") or 0),
                "pool_id":         pool_id,
                "automated":       automated,
                "protocol_config": cfg,
            })

        results.sort(key=lambda x: -x["apy"])

        # On-chain APY verification — updates 'apy' for Aave; must run before risk model
        try:
            from utils.treasury_yield_oracle import enrich_with_onchain_apy
            results = enrich_with_onchain_apy(results)
        except Exception as e:
            logger.debug(f"TreasuryAgent: YieldOracle enrichment failed: {e}")

        # Risk scoring — uses corrected 'apy' field; re-sorts by risk_adjusted_apy
        try:
            from utils.treasury_risk import enrich_opportunities
            results = enrich_opportunities(results)
        except Exception as e:
            logger.warning(f"TreasuryAgent: risk enrichment failed (falling back to raw APY sort): {e}")

        return results

    # ── Smart allocation ──────────────────────────────────────────────────────

    def _pick_best_protocol(self, opportunities: list[dict]) -> tuple[dict | None, bool]:
        """
        Returns (best_opportunity, is_automated).

        Priority:
          1. Automated Arbitrum — ranked by risk-adjusted APY (no bridge, instant, low gas)
          2. Automated any chain — only if raw APY meets threshold, ranked by risk-adjusted APY
          3. Non-automated Arbitrum — informational only (requires manual steps but same chain)
          4. Never recommend non-Arbitrum non-automated protocols (Ethereum bridge = extra risk + UX)
        """
        _rank = lambda o: o.get("risk_adjusted_apy") or o.get("apy", 0)
        # Liquidity guard: epoch-based vaults (immediate_withdraw=false, e.g. Gains
        # gUSDC) are never an automated deposit destination — capital deposited there
        # cannot be auto-withdrawn, which blocks diversification and HL rebalancing.
        _liquid = lambda o: bool((o.get("protocol_config") or {}).get("immediate_withdraw", True))

        # 1. Best automated protocol on Arbitrum — ranked by risk-adjusted APY
        automated_arb = [o for o in opportunities if o.get("automated") and o["chain"].lower() == "arbitrum" and _liquid(o)]
        if automated_arb:
            return max(automated_arb, key=_rank), True

        # 2. Automated elsewhere, but only if APY justifies the cross-chain complexity
        automated_any = [o for o in opportunities if o.get("automated") and o["apy"] >= _MIN_APY and _liquid(o)]
        if automated_any:
            return max(automated_any, key=_rank), True

        # 3. Non-automated Arbitrum — at least it's the same chain (vault address needed)
        manual_arb = [
            o for o in opportunities
            if not o.get("automated") and o["chain"].lower() == "arbitrum" and o["apy"] >= _MIN_APY
        ]
        if manual_arb:
            return max(manual_arb, key=_rank), False

        # 4. No good option on Arbitrum — nothing to recommend
        return None, False

    # ── Proposals ─────────────────────────────────────────────────────────────

    def generate_proposals(
        self,
        hl: dict,
        opportunities: list[dict],
        treasury_usdc: float = 0,
        aave_balance: float | None = None,
        yield_balances: dict | None = None,
    ) -> list[dict]:
        """
        Portfolio-aware allocation: splits treasury USDC between HL top-up and yield.
        Uses AllocationOptimizer (LLM) to distribute yield capital across tranches;
        falls back to rule-based single-protocol if LLM is unavailable.

        Returns:
          - N × DEPLOY_YIELD proposals (one per allocated tranche)
          - 0–1 × FUND_TRADING proposal (manual HL bridge reminder)
        """
        from utils.treasury_executor import get_total_yield_balance as _get_total_yield, _TREASURY_WALLET

        hl_balance = hl.get("balance", 0)
        # Total deployed yield across ALL automated protocols — not just Aave. Counting
        # only aave_balance undersizes total_portfolio (and the target allocation) once
        # capital sits in Morpho/Gains. Prefer the explicit yield_balances passed by run();
        # fall back to aave_balance for back-compat, then to an on-chain total fetch.
        if yield_balances:
            total_yield = round(sum(yield_balances.values()), 2)
        elif aave_balance is not None:
            total_yield = aave_balance
        else:
            try:
                total_yield = _get_total_yield(_TREASURY_WALLET)
            except Exception:
                total_yield = 0.0

        total_portfolio = round(hl_balance + total_yield + treasury_usdc, 2)
        if total_portfolio < _MIN_DEPLOY_USD or not opportunities:
            return []

        # Target allocation — performance-adaptive
        target      = self._compute_target_allocation(total_portfolio)
        target_trade = target["target_trade_usd"]
        trade_pct    = target["effective_trade_pct"]
        yield_pct    = 100 - trade_pct

        # Split treasury USDC: first top up HL to target, then rest to yield
        hl_deficit  = max(0, round(target_trade - hl_balance, 2))
        hl_topup    = round(min(hl_deficit, max(0, treasury_usdc - 50)), 2)  # keep $50 gas buffer
        to_yield    = round(treasury_usdc - hl_topup, 2)

        proposals: list[dict] = []
        now_str = datetime.utcnow().strftime("%Y%m%d_%H%M")

        # ── Proposal(s): DEPLOY_YIELD ─────────────────────────────────────────
        if to_yield >= _MIN_DEPLOY_USD:
            # AllocationOptimizer: LLM-based multi-protocol split (falls back to rule-based)
            allocations: list[dict] = []
            if self._optimizer:
                try:
                    allocations = self._optimizer.optimize(
                        to_yield, opportunities, yield_balances or {}
                    )
                except Exception as e:
                    logger.warning(f"TreasuryAgent: optimizer failed ({e}), falling back")

            if not allocations:
                # Final fallback: single-protocol rule-based
                best, executable = self._pick_best_protocol(opportunities)
                if best:
                    allocations = [{
                        "protocol_id":     (best.get("protocol_config") or {}).get("id", ""),
                        "protocol_config": best.get("protocol_config"),
                        "tranche":         (best.get("risk_score") or {}).get("tranche", "yield_core"),
                        "amount_usd":      to_yield,
                        "apy":             best["apy"],
                        "risk_adjusted_apy": best.get("risk_adjusted_apy", best["apy"]),
                        "rationale":       f"Rule-based: best risk-adjusted APY ({best['label']})",
                    }]

            hl_note = (
                f" HL top-up van ${hl_topup:.0f} ook aanbevolen (zie FUND_TRADING voorstel)."
                if hl_topup >= 50 else ""
            )

            for idx, alloc in enumerate(allocations):
                pid     = alloc.get("protocol_id", "")
                cfg     = alloc.get("protocol_config") or {}
                amt     = alloc["amount_usd"]
                apy     = alloc.get("apy", 0)
                monthly = round(amt * apy / 100 / 12, 2)
                yearly  = round(amt * apy / 100, 2)
                label   = cfg.get("label", pid)
                p_type  = cfg.get("type", "aave_v3")
                executable = bool(cfg and (cfg.get("pool_address") or cfg.get("vault_address")))

                proposals.append({
                    "id":                f"TRP_{now_str}_{idx}",
                    "type":              "DEPLOY_YIELD",
                    "status":            "APPROVED",
                    "auto_initiated":    True,
                    "source":            "treasury_wallet",
                    "title":             f"Deploy ${amt:.0f} → {label} @ {apy:.1f}% APY [{alloc.get('tranche','yield_core')}]",
                    "amount_usd":        amt,
                    "source_hl":         0,
                    "source_treasury":   amt,
                    "protocol":          label,
                    "protocol_id":       pid,
                    "protocol_type":     p_type,
                    "protocol_config":   cfg or None,
                    "chain":             "Arbitrum",
                    "apy":               apy,
                    "risk_adjusted_apy": alloc.get("risk_adjusted_apy", apy),
                    "tranche":           alloc.get("tranche", "yield_core"),
                    "projected_monthly": monthly,
                    "projected_yearly":  yearly,
                    "executable":        executable,
                    "allocation": {
                        "total_portfolio":      total_portfolio,
                        "target_trade_usd":     target_trade,
                        "target_trade_pct":     trade_pct,
                        "target_yield_pct":     yield_pct,
                        "hl_topup_recommended": hl_topup,
                        "target_reason":        target["reason"],
                        "optimizer_tranches":   len(allocations),
                    },
                    "rationale": (
                        f"Portfolio ${total_portfolio:.0f}: doel {trade_pct}% trading | {yield_pct}% yield. "
                        f"[{target['reason']}]. Tranche '{alloc.get('tranche','yield_core')}': "
                        f"${amt:.0f} → {label} @ {apy:.1f}% (risk-adj {alloc.get('risk_adjusted_apy', apy):.2f}%). "
                        f"Verwacht: ${monthly:.2f}/mnd.{hl_note} "
                        f"Optimizer: {alloc.get('rationale', '')}"
                    ),
                    "created_at":  datetime.utcnow().isoformat(),
                    "approved_at": datetime.utcnow().isoformat(),
                })

        # ── Proposal 2: FUND_TRADING — manual bridge to HL ───────────────────
        if hl_topup >= 50:
            proposals.append({
                "id":           f"TRF_{now_str}",
                "type":         "FUND_TRADING",
                "status":       "PENDING",
                "title":        f"Bridge ${hl_topup:.0f} → HL (trading kapitaal top-up)",
                "amount_usd":   hl_topup,
                "chain":        "Arbitrum",
                "apy":          0.0,
                "projected_monthly": 0.0,
                "projected_yearly":  0.0,
                "executable":   False,
                "allocation": {
                    "total_portfolio":  total_portfolio,
                    "current_hl":       hl_balance,
                    "target_trade_usd": target_trade,
                    "target_trade_pct": trade_pct,
                    "target_reason":    target["reason"],
                },
                "rationale": (
                    f"HL kapitaal: ${hl_balance:.0f} → doel ${target_trade:.0f} ({trade_pct}% van ${total_portfolio:.0f}). "
                    f"Meer HL-kapitaal = grotere Kelly-posities en hogere verwachte winst. "
                    f"{target['reason']}."
                ),
                "steps": [
                    "1. Ga naar app.hyperliquid.xyz → Transfer → Deposit to HL",
                    "2. Selecteer Arbitrum als source chain",
                    f"3. Stuur ${hl_topup:.0f} USDC van treasury wallet naar HL",
                    "4. Dit voorstel wordt automatisch afgesloten zodra HL-balans stijgt",
                ],
                "created_at": datetime.utcnow().isoformat(),
            })

        return proposals

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_proposals(self) -> list[dict]:
        try:
            with open("treasury_proposals.json") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_proposals(self, proposals: list[dict]) -> None:
        try:
            with open("treasury_proposals.json", "w") as f:
                json.dump(proposals, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save proposals: {e}")

    def _upsert_proposals(self, new_proposals: list[dict]) -> list[dict]:
        """Merge new proposals with existing — replace stale PENDING ones."""
        existing = self._load_proposals()
        now_ts = datetime.utcnow().timestamp()

        # Keep APPROVED/REJECTED history; drop stale PENDING
        kept = [
            p for p in existing
            if p.get("status") != "PENDING"
            or (now_ts - self._parse_ts(p.get("created_at", ""))) < _PROPOSAL_TTL_H * 3600
        ]
        # Don't duplicate proposals that are still active (any in-flight status)
        active_statuses = {
            "PENDING", "APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL",
            "BRIDGED", "REBALANCING", "MONITORING",
        }
        active_types = {p["type"] for p in kept if p.get("status") in active_statuses}
        added = [p for p in new_proposals if p["type"] not in active_types]
        merged = kept + added
        self._save_proposals(merged)
        return added  # return only the truly new ones

    @staticmethod
    def _parse_ts(v: str) -> float:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

    # ── Telegram ─────────────────────────────────────────────────────────────

    def _send_telegram(self, text: str) -> None:
        token = _telegram_token()
        chat  = _telegram_chat_id()
        if not token or not chat:
            return
        try:
            import json as _j
            body = _j.dumps({
                "chat_id": chat, "text": text, "parse_mode": "Markdown",
            }).encode('utf-8')
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=body, method="POST",
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    # ── Auto-rebalance ────────────────────────────────────────────────────────

    def _check_rebalance_needed(self, hl: dict, all_proposals: list) -> list:
        """
        If HL balance has drifted more than rebalance_drift_pct below the target trading
        allocation, auto-create a REBALANCE proposal to pull funds back from Aave.
        """
        from utils.treasury_executor import get_aave_balance, _TREASURY_WALLET

        hl_balance = hl.get("balance", 0)
        if hl_balance <= 0:
            return all_proposals

        aave_bal = get_aave_balance(_TREASURY_WALLET)
        if aave_bal < _REBALANCE_MIN_USD:
            return all_proposals

        total = round(hl_balance + aave_bal, 2)
        target = self._compute_target_allocation(total)
        target_trade = target["target_trade_usd"]
        cfg = self._load_allocation_config()
        drift_usd = total * cfg.get("rebalance_drift_pct", 10) / 100

        # Only trigger if HL is significantly below target (drift threshold)
        if hl_balance >= target_trade - drift_usd:
            return all_proposals

        # Skip if a rebalance is already in flight
        active_rebalance = {"REBALANCING", "BRIDGE_BACK_NEEDED", "APPROVED"}
        if any(p.get("type") == "REBALANCE" and p.get("status") in active_rebalance for p in all_proposals):
            return all_proposals

        needed = min(round(target_trade - hl_balance, 2), aave_bal)
        if needed < _REBALANCE_MIN_USD:
            return all_proposals

        hl_pct = round(hl_balance / total * 100, 1)
        proposal = {
            "id":             f"TRR_{datetime.utcnow().strftime('%Y%m%d_%H%M')}",
            "type":           "REBALANCE",
            "status":         "APPROVED",
            "auto_initiated": True,
            "title":          f"Rebalance: ${needed:.0f} Aave → HL (target {target['effective_trade_pct']}%)",
            "amount_usd":     needed,
            "protocol":       "Aave v3 Arbitrum",
            "chain":          "Arbitrum",
            "apy":            0.0,
            "projected_monthly": 0.0,
            "projected_yearly":  0.0,
            "rationale": (
                f"HL is ${hl_balance:.0f} ({hl_pct}% van ${total:.0f}) — "
                f"doel is {target['effective_trade_pct']}% (${target_trade:.0f}). "
                f"[{target['reason']}]. "
                f"Terughalen ${needed:.0f} uit Aave om trading capaciteit te herstellen."
            ),
            "steps": [
                f"1. Automatisch: Aave withdraw ${needed:.0f} USDC → treasury wallet",
                f"2. Handmatig (~1 min): app.hyperliquid.xyz → Deposit → Arbitrum → ${needed:.0f} USDC",
            ],
            "created_at": datetime.utcnow().isoformat(),
        }
        all_proposals.append(proposal)
        logger.info(
            f"💰 Treasury: rebalance triggered — HL ${hl_balance:.0f} ({hl_pct}%) < target "
            f"${target_trade:.0f} ({target['effective_trade_pct']}%), reclaiming ${needed:.0f} from Aave"
        )
        self._send_telegram(
            f"⚠️ *Treasury: Automatische rebalance*\n"
            f"HL: ${hl_balance:.0f} ({hl_pct}%) — doel: {target['effective_trade_pct']}% (${target_trade:.0f})\n"
            f"[{target['reason']}]\n"
            f"Aave withdraw ${needed:.0f} wordt gestart."
        )
        return all_proposals

    # ── HL excess → yield ─────────────────────────────────────────────────────

    def _check_hl_excess(self, hl: dict, all_proposals: list, opportunities: list) -> list:
        """
        Symmetric to _check_rebalance_needed(): if HL is significantly above the target
        trading allocation, auto-create an approved DEPLOY_YIELD (source='hl') to move
        the excess to the best automated Arbitrum yield protocol.
        Safe: caps withdrawal at 90% of free margin so open positions are never touched.
        """
        from utils.treasury_executor import get_total_yield_balance, get_arb_usdc_balance, _TREASURY_WALLET

        hl_balance  = hl.get("balance", 0)
        free_margin = hl.get("free_margin", 0)
        if hl_balance <= 0 or free_margin <= 0:
            return all_proposals

        # Block if any DEPLOY_YIELD is already in-flight (avoid concurrent withdrawals)
        in_flight = {"APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED"}
        if any(p.get("type") == "DEPLOY_YIELD" and p.get("status") in in_flight for p in all_proposals):
            return all_proposals

        try:
            yield_bal     = get_total_yield_balance(_TREASURY_WALLET)
            treasury_usdc = get_arb_usdc_balance(_TREASURY_WALLET)
        except Exception:
            return all_proposals

        total = round(hl_balance + yield_bal + treasury_usdc, 2)
        if total <= 0:
            return all_proposals

        target       = self._compute_target_allocation(total)
        target_trade = target["target_trade_usd"]
        cfg          = self._load_allocation_config()
        drift_usd    = total * cfg.get("rebalance_drift_pct", 10) / 100

        if hl_balance <= target_trade + drift_usd:
            return all_proposals

        excess = round(hl_balance - target_trade, 2)
        # Never touch margin in use — cap at 90% of free margin
        safe_withdraw = round(min(excess, free_margin * 0.9), 2)
        if safe_withdraw < _HL_EXCESS_MIN_USD:
            return all_proposals

        best, is_automated = self._pick_best_protocol(opportunities or [])
        if not best or not is_automated:
            logger.debug("TreasuryAgent: HL excess detected but no automated protocol available — skipping")
            return all_proposals

        protocol_label = best["label"]
        protocol_id    = best.get("id", "aave-v3-arbitrum-usdc")
        protocol_type  = best.get("type", "aave_v3")
        protocol_cfg   = best.get("protocol_config")
        apy            = best["apy"]
        hl_pct         = round(hl_balance / total * 100, 1)
        monthly        = round(safe_withdraw * (apy / 100) / 12, 2)
        now_str        = datetime.utcnow().strftime("%Y%m%d_%H%M")

        proposal = {
            "id":                f"TRP_{now_str}_excess",
            "type":              "DEPLOY_YIELD",
            "status":            "APPROVED",
            "source":            "hl",
            "auto_initiated":    True,
            "title":             f"HL excess ${safe_withdraw:.0f} → {protocol_label} @ {apy:.1f}% APY",
            "amount_usd":        safe_withdraw,
            "source_hl":         safe_withdraw,
            "source_treasury":   0.0,
            "protocol":          protocol_label,
            "protocol_id":       protocol_id,
            "protocol_type":     protocol_type,
            "protocol_config":   protocol_cfg,
            "chain":             best.get("chain", "Arbitrum"),
            "apy":               apy,
            "projected_monthly": monthly,
            "projected_yearly":  round(safe_withdraw * (apy / 100), 2),
            "executable":        True,
            "rationale": (
                f"HL ${hl_balance:.0f} ({hl_pct}% van ${total:.0f}) — "
                f"doel {target['effective_trade_pct']}% (${target_trade:.0f}). "
                f"Excess ${excess:.0f}, vrij margin ${free_margin:.0f}. "
                f"Withdrawal ${safe_withdraw:.0f} → {protocol_label} @ {apy:.1f}% APY. "
                f"Verwacht: ${monthly:.2f}/mnd."
            ),
            "created_at":  datetime.utcnow().isoformat(),
            "approved_at": datetime.utcnow().isoformat(),
        }

        all_proposals.append(proposal)
        logger.info(
            f"💰 Treasury: HL excess — ${hl_balance:.0f} ({hl_pct}%) > target "
            f"${target_trade:.0f} ({target['effective_trade_pct']}%) — "
            f"auto-withdrawing ${safe_withdraw:.0f} to {protocol_label}"
        )
        self._send_telegram(
            f"💸 *Treasury: HL excess → yield*\n"
            f"HL: ${hl_balance:.0f} ({hl_pct}%) — doel: {target['effective_trade_pct']}% (${target_trade:.0f})\n"
            f"Withdrawing ${safe_withdraw:.0f} → {protocol_label} @ {apy:.1f}% APY\n"
            f"Verwacht: ${monthly:.2f}/mnd"
        )
        return all_proposals

    # ── Treasury wallet USDC detection ───────────────────────────────────────

    def _check_treasury_wallet_usdc(self, all_proposals: list, opportunities: list) -> list:
        """
        If USDC sits idle on the treasury wallet (e.g. user deposited directly),
        create a PENDING DEPLOY_YIELD proposal with source='treasury_wallet'.
        The executor skips the HL bridge step for these proposals.
        """
        from utils.treasury_executor import get_arb_usdc_balance, _TREASURY_WALLET

        # Skip if any DEPLOY_YIELD proposal is already active
        active = {"APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED"}
        if any(p.get("type") == "DEPLOY_YIELD" and p.get("status") in active for p in all_proposals):
            return all_proposals

        balance = get_arb_usdc_balance(_TREASURY_WALLET)
        if balance < _MIN_DEPLOY_USD:
            return all_proposals

        # Pick best Arbitrum yield; fall back to Aave label if none found
        best = next(
            (o for o in opportunities if o["apy"] >= _MIN_APY and o["chain"].lower() == "arbitrum"),
            None,
        )
        if not best:
            best = {"label": "Aave v3 · Arbitrum · USDC", "apy": 0.0}

        monthly = round(balance * (best["apy"] / 100) / 12, 2)
        yearly  = round(balance * (best["apy"] / 100), 2)

        proposal = {
            "id":                f"TRW_{datetime.utcnow().strftime('%Y%m%d_%H%M')}",
            "type":              "DEPLOY_YIELD",
            "status":            "PENDING",
            "source":            "treasury_wallet",  # USDC already on Arbitrum — skip bridge
            "title":             f"Deploy ${balance:.0f} treasury wallet USDC → Aave",
            "amount_usd":        round(balance, 2),
            "protocol":          best["label"],
            "chain":             "Arbitrum",
            "apy":               best["apy"],
            "projected_monthly": monthly,
            "projected_yearly":  yearly,
            "buffer_remaining":  0,
            "rationale": (
                f"${balance:.0f} USDC gedetecteerd op treasury wallet ({_TREASURY_WALLET[:10]}…). "
                f"Geen bridge nodig — direct storten in {best['label']} @ {best['apy']:.1f}% APY. "
                f"Verwacht: ${monthly:.2f}/mnd | ${yearly:.2f}/jaar."
            ),
            "steps": [
                f"1. Automatisch: approve + supply ${balance:.0f} USDC → Aave v3 Arbitrum",
            ],
            "created_at": datetime.utcnow().isoformat(),
        }

        all_proposals.append(proposal)
        logger.info(f"💰 Treasury: ${balance:.0f} USDC gedetecteerd op treasury wallet — voorstel aangemaakt")
        self._send_telegram(
            f"💰 *Treasury: USDC gedetecteerd*\n"
            f"${balance:.0f} USDC op treasury wallet ({_TREASURY_WALLET[:10]}…)\n"
            f"Keur goed in het dashboard om automatisch te storten bij Aave."
        )
        return all_proposals

    # ── Yield balance tracking ────────────────────────────────────────────────

    def _get_yield_balances(self) -> dict:
        """Returns {protocol_id: balance_usd} for every automated protocol."""
        from utils.treasury_executor import get_aave_balance, get_erc4626_balance, _TREASURY_WALLET
        balances: dict[str, float] = {}
        for cfg in self._load_protocol_config():
            if not cfg.get("automated"):
                continue
            pid   = cfg["id"]
            ptype = cfg.get("type", "")
            try:
                if ptype == "aave_v3":
                    balances[pid] = get_aave_balance(_TREASURY_WALLET)
                elif ptype == "erc4626":
                    vault = cfg.get("vault_address")
                    balances[pid] = get_erc4626_balance(vault, _TREASURY_WALLET) if vault else 0.0
            except Exception as e:
                logger.debug(f"TreasuryAgent: yield balance failed for {pid}: {e}")
                balances[pid] = 0.0
        return balances

    def _check_yield_switch(
        self,
        opportunities: list,
        yield_balances: dict,
        all_proposals: list,
    ) -> tuple[list, list]:
        """
        Auto-create a YIELD_SWITCH proposal when a better automated Arbitrum protocol
        offers ≥ _YIELD_SWITCH_MIN_SPREAD % more APY than the currently deployed protocol.
        Only one switch runs at a time.
        """
        pending_notifs: list[str] = []

        # Skip if a switch is already in flight
        switch_active = {"APPROVED", "SWITCHING"}
        if any(p.get("type") == "YIELD_SWITCH" and p.get("status") in switch_active for p in all_proposals):
            return all_proposals, pending_notifs

        # Cooldown: skip if any switch was created within the last 6 hours (prevents restart spam)
        _SWITCH_COOLDOWN_H = 6
        cutoff = datetime.utcnow().timestamp() - _SWITCH_COOLDOWN_H * 3600
        recent = next(
            (p for p in all_proposals
             if p.get("type") == "YIELD_SWITCH"
             and self._parse_ts(p.get("created_at", "")) > cutoff),
            None,
        )
        if recent:
            logger.debug(
                f"TreasuryAgent: yield switch cooldown — last switch {recent['id']} "
                f"({recent.get('status')}) < {_SWITCH_COOLDOWN_H}h ago"
            )
            return all_proposals, pending_notifs

        # Risk-adjusted APY with raw fallback — the decision basis for switching.
        def _ra(o):
            return o.get("risk_adjusted_apy", o.get("apy", 0.0))

        # Candidate switch DESTINATIONS: automated Arbitrum protocols that we can also
        # withdraw from. Exclude immediate_withdraw=false (epoch-based, e.g. Gains gUSDC) —
        # switching INTO a one-way vault traps the capital (no auto-exit; it then blocks
        # diversification and HL rebalancing). Such protocols can still be funded by the
        # LLM allocator's opportunistic tranche (which is capped), just not by this blind switch.
        auto_arb = [
            o for o in opportunities
            if o.get("automated")
            and o.get("chain", "").lower() == "arbitrum"
            and (o.get("protocol_config") or {}).get("immediate_withdraw", True)
        ]
        if not auto_arb:
            return all_proposals, pending_notifs
        # Rank by RISK-ADJUSTED APY, not raw — consistent with _pick_best_protocol() and
        # _check_yield_diversification(). Ranking on raw APY alone consolidates everything
        # into the highest-headline-yield vault regardless of counterparty risk.
        best     = max(auto_arb, key=_ra)
        best_cfg = best.get("protocol_config") or {}
        best_id  = best_cfg.get("id", "")
        best_apy = best.get("apy", 0.0)   # raw — for display / projected yield
        best_ra  = _ra(best)              # risk-adjusted — for the switch decision

        # APY lookup tables for currently deployed protocols (raw for display, risk-adj for decision)
        apy_by_id = {
            (o.get("protocol_config") or {}).get("id", ""): o.get("apy", 0.0)
            for o in opportunities
            if o.get("protocol_config")
        }
        ra_by_id = {
            (o.get("protocol_config") or {}).get("id", ""): _ra(o)
            for o in opportunities
            if o.get("protocol_config")
        }

        protocol_cfgs = {c["id"]: c for c in self._load_protocol_config()}

        for pid, deployed_bal in yield_balances.items():
            if deployed_bal < _YIELD_SWITCH_MIN_USD:
                continue
            if pid == best_id:
                continue  # already in the best protocol
            if pid not in apy_by_id:
                # Protocol APY unknown (not in opportunities list) — skip rather than assume 0%
                logger.debug(f"TreasuryAgent: {pid} not in opportunities — skipping yield switch (APY unknown)")
                continue
            from_cfg = protocol_cfgs.get(pid, {})
            if not from_cfg.get("immediate_withdraw", True):
                logger.debug(f"TreasuryAgent: {pid} skipped as switch source — immediate_withdraw=false (epoch-based)")
                continue
            current_apy = apy_by_id[pid]
            if current_apy <= 0.0:
                # A deployed automated protocol with 0% APY almost always means the APY
                # read failed (DeFiLlama partial fetch / blocked on-chain call), not a real
                # 0% yield. Treat it as "unknown — don't move" to avoid a spurious switch.
                logger.debug(f"TreasuryAgent: {pid} reports {current_apy}% APY — skipping switch (assume stale read)")
                continue
            # Decide on RISK-ADJUSTED spread; display the raw spread (real extra yield).
            current_ra = ra_by_id.get(pid, current_apy)
            spread_ra  = best_ra - current_ra
            if spread_ra < _YIELD_SWITCH_MIN_SPREAD:
                continue
            spread = best_apy - current_apy
            now_str    = datetime.utcnow().strftime("%Y%m%d_%H%M")
            monthly    = round(deployed_bal * best_apy / 100 / 12, 2)
            yearly     = round(deployed_bal * best_apy / 100, 2)
            extra_mth  = round(deployed_bal * spread / 100 / 12, 2)
            extra_yr   = round(deployed_bal * spread / 100, 2)

            proposal = {
                "id":                   f"TRS_{now_str}",
                "type":                 "YIELD_SWITCH",
                "status":               "APPROVED",
                "auto_initiated":       True,
                "title":                f"Yield switch: {from_cfg.get('label', pid)} → {best['label']} (+{spread:.1f}% APY)",
                "amount_usd":           round(deployed_bal, 2),
                "from_protocol":        from_cfg.get("label", pid),
                "from_protocol_type":   from_cfg.get("type", "aave_v3"),
                "from_protocol_config": from_cfg,
                "protocol":             best["label"],
                "protocol_id":          best_id,
                "protocol_type":        best_cfg.get("type", "aave_v3"),
                "protocol_config":      best_cfg,
                "chain":                best["chain"],
                "apy":                  best_apy,
                "from_apy":             current_apy,
                "apy_spread":           round(spread, 2),
                "apy_spread_risk_adj":  round(spread_ra, 2),
                "projected_monthly":    monthly,
                "projected_yearly":     yearly,
                "rationale": (
                    f"${deployed_bal:.0f} in {from_cfg.get('label', pid)} @ {current_apy:.1f}% APY. "
                    f"Beter: {best['label']} @ {best_apy:.1f}% (+{spread:.1f}%). "
                    f"Extra rendement: ${extra_mth:.2f}/mnd | ${extra_yr:.2f}/jaar."
                ),
                "created_at": datetime.utcnow().isoformat(),
            }
            all_proposals.append(proposal)
            logger.info(
                f"💱 Treasury: yield switch triggered — {from_cfg.get('label', pid)} "
                f"({current_apy:.1f}%) → {best['label']} ({best_apy:.1f}%) on ${deployed_bal:.0f}"
            )
            pending_notifs.append(
                f"💱 *Treasury: Yield switch*\n"
                f"${deployed_bal:.0f} uit {from_cfg.get('label', pid)} @ {current_apy:.1f}%\n"
                f"→ {best['label']} @ {best_apy:.1f}% (+{spread:.1f}%)\n"
                f"Extra: ${extra_mth:.2f}/mnd | ${extra_yr:.2f}/jaar"
            )
            break  # one switch at a time

        return all_proposals, pending_notifs

    def _check_yield_diversification(
        self,
        opportunities: list,
        yield_balances: dict,
        all_proposals: list,
    ) -> tuple[list, list]:
        """
        Auto-create a partial YIELD_SWITCH proposal when one protocol holds
        more than _MAX_SINGLE_CONCENTRATION % of total yield capital.
        Moves enough to bring the concentration down to _DIVERSIFY_TARGET_PCT.
        Uses switch_amount_usd for partial withdrawal (not full balance).
        """
        pending_notifs: list[str] = []

        total_yield = sum(yield_balances.values())
        if total_yield < _DIVERSIFY_MIN_TOTAL_USD:
            return all_proposals, pending_notifs

        # Skip if any YIELD_SWITCH is already in-flight (prevents overlap with APY-driven switches)
        switch_active = {"APPROVED", "SWITCHING"}
        if any(p.get("type") == "YIELD_SWITCH" and p.get("status") in switch_active for p in all_proposals):
            return all_proposals, pending_notifs

        # Cooldown: skip if a diversification proposal was created recently
        cutoff = datetime.utcnow().timestamp() - _DIVERSIFY_COOLDOWN_H * 3600
        recent = next(
            (p for p in all_proposals
             if p.get("type") == "YIELD_SWITCH"
             and p.get("diversification") is True
             and self._parse_ts(p.get("created_at", "")) > cutoff),
            None,
        )
        if recent:
            logger.debug(
                f"TreasuryAgent: diversification cooldown — last proposal {recent['id']} "
                f"({recent.get('status')}) < {_DIVERSIFY_COOLDOWN_H}h ago"
            )
            return all_proposals, pending_notifs

        # Find the most concentrated protocol
        overweight_pid = max(yield_balances, key=lambda pid: yield_balances[pid], default=None)
        if not overweight_pid:
            return all_proposals, pending_notifs
        overweight_bal = yield_balances[overweight_pid]
        overweight_pct = overweight_bal / total_yield * 100

        if overweight_pct <= _MAX_SINGLE_CONCENTRATION:
            return all_proposals, pending_notifs

        # Amount to move: bring source down to target concentration
        move_amount = overweight_bal - total_yield * _DIVERSIFY_TARGET_PCT / 100
        if move_amount < 50.0:
            return all_proposals, pending_notifs

        # Best automated Arbitrum destination other than the overweight protocol.
        # Liquidity guard: exclude epoch-based vaults (immediate_withdraw=false,
        # e.g. Gains gUSDC) — diversifying INTO a one-way vault trades a
        # concentration problem for a trapped-capital problem.
        auto_arb = [
            o for o in opportunities
            if o.get("automated")
            and o.get("chain", "").lower() == "arbitrum"
            and (o.get("protocol_config") or {}).get("id", "") != overweight_pid
            and bool((o.get("protocol_config") or {}).get("immediate_withdraw", True))
        ]
        if not auto_arb:
            return all_proposals, pending_notifs
        best     = max(auto_arb, key=lambda o: o.get("risk_adjusted_apy", o.get("apy", 0)))
        best_cfg = best.get("protocol_config") or {}
        best_id  = best_cfg.get("id", "")
        best_apy = best.get("apy", 0.0)

        protocol_cfgs = {c["id"]: c for c in self._load_protocol_config()}
        from_cfg      = protocol_cfgs.get(overweight_pid, {})
        if not from_cfg:
            logger.warning(f"TreasuryAgent: diversification skipped — no config for {overweight_pid}")
            return all_proposals, pending_notifs
        if not from_cfg.get("immediate_withdraw", True):
            # Source needs epoch-based withdrawal (e.g. Gains gUSDC) — we can't auto-move it.
            # Don't silently swallow this: surface a manual-action alert. The inert
            # informational proposal (no executor active set lists MANUAL_ACTION_REQUIRED)
            # also doubles as the diversification cooldown record, so this fires at most
            # once per _DIVERSIFY_COOLDOWN_H window rather than every fast cycle.
            logger.warning(
                f"TreasuryAgent: {overweight_pid} is {overweight_pct:.0f}% of yield but requires "
                f"epoch-based withdrawal (immediate_withdraw=false) — manual rebalance needed."
            )
            now_str = datetime.utcnow().strftime("%Y%m%d_%H%M")
            all_proposals.append({
                "id":              f"TRDM_{now_str}",
                "type":            "YIELD_SWITCH",
                "status":          "MANUAL_ACTION_REQUIRED",
                "diversification": True,
                "auto_initiated":  True,
                "title": (
                    f"Manual diversificatie nodig: {from_cfg.get('label', overweight_pid)} "
                    f"{overweight_pct:.0f}% van yield"
                ),
                "amount_usd":      round(overweight_bal, 2),
                "from_protocol":   from_cfg.get("label", overweight_pid),
                "rationale": (
                    f"{from_cfg.get('label', overweight_pid)} heeft {overweight_pct:.0f}% van yield "
                    f"(${overweight_bal:.0f} van ${total_yield:.0f}) maar ondersteunt geen directe "
                    f"withdrawal (epoch-based). Handmatige herverdeling vereist."
                ),
                "created_at": datetime.utcnow().isoformat(),
            })
            pending_notifs.append(
                f"⚠️ *Treasury: handmatige diversificatie*\n"
                f"{from_cfg.get('label', overweight_pid)} = {overweight_pct:.0f}% van yield "
                f"(${overweight_bal:.0f}/${total_yield:.0f})\n"
                f"Epoch-based protocol — kan niet automatisch verplaatst worden. "
                f"Withdraw handmatig om de concentratie te verlagen."
            )
            return all_proposals, pending_notifs

        now_str  = datetime.utcnow().strftime("%Y%m%d_%H%M")
        proposal = {
            "id":                   f"TRD_{now_str}",
            "type":                 "YIELD_SWITCH",
            "status":               "APPROVED",
            "auto_initiated":       True,
            "diversification":      True,
            "title": (
                f"Diversificatie: ${move_amount:.0f} uit "
                f"{from_cfg.get('label', overweight_pid)} → {best['label']}"
            ),
            "amount_usd":           round(overweight_bal, 2),
            "switch_amount_usd":    round(move_amount, 2),
            "from_protocol":        from_cfg.get("label", overweight_pid),
            "from_protocol_type":   from_cfg.get("type", "erc4626"),
            "from_protocol_config": from_cfg,
            "protocol":             best["label"],
            "protocol_id":          best_id,
            "protocol_type":        best_cfg.get("type", "aave_v3"),
            "protocol_config":      best_cfg,
            "chain":                best["chain"],
            "apy":                  best_apy,
            "rationale": (
                f"{from_cfg.get('label', overweight_pid)} heeft {overweight_pct:.0f}% van yield "
                f"(${overweight_bal:.0f} van ${total_yield:.0f}). "
                f"Doel: max {_DIVERSIFY_TARGET_PCT:.0f}% per protocol. "
                f"${move_amount:.0f} USDC → {best['label']} @ {best_apy:.1f}% APY."
            ),
            "created_at": datetime.utcnow().isoformat(),
        }
        all_proposals.append(proposal)
        logger.info(
            f"🔀 Treasury: diversification triggered — {from_cfg.get('label', overweight_pid)} "
            f"{overweight_pct:.0f}% → move ${move_amount:.0f} to {best['label']}"
        )
        pending_notifs.append(
            f"🔀 *Treasury: Diversificatie*\n"
            f"{from_cfg.get('label', overweight_pid)} heeft {overweight_pct:.0f}% concentratie\n"
            f"${move_amount:.0f} → {best['label']} @ {best_apy:.1f}% APY\n"
            f"Doel: max {_DIVERSIFY_TARGET_PCT:.0f}% per protocol"
        )
        return all_proposals, pending_notifs

    # ── Funding Harvest ───────────────────────────────────────────────────────
    #
    # Opens a small HL short when funding rate is high, collecting funding
    # payments from longs. Auto-closes when rate drops or max hold time expires.
    # Stored in treasury_harvest.json (separate from trade_log / proposals).

    _HARVEST_MIN_RATE_8H    = 0.01   # %/8h to open  (≈10.95% APR, 8× fee break-even)
    _HARVEST_CLOSE_RATE_8H  = 0.003  # %/8h to close (≈3.28% APR)
    _HARVEST_MAX_NOTIONAL   = 150    # USD notional — small, safe
    _HARVEST_MAX_HOLD_H     = 48     # auto-close after this many hours regardless
    _HARVEST_ALLOWED_ASSETS = frozenset({"BTC", "ETH"})  # liquid only

    def _get_hl_funding_rates(self) -> dict:
        """Fetch HL funding rates via public info API. Returns {asset: %/8h}."""
        payload = json.dumps({"type": "metaAndAssetCtxs"}).encode()
        import urllib.request as _req
        r = _req.Request(
            "https://api.hyperliquid.xyz/info",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with _req.urlopen(r, timeout=10) as resp:
            data = json.loads(resp.read())
        meta   = data[0]
        ctxs   = data[1]
        assets = [a["name"] for a in meta["universe"]]
        return {
            name: float(ctx["funding"]) * 100
            for name, ctx in zip(assets, ctxs)
            if ctx.get("funding") is not None
        }

    def _get_harvest_state(self) -> dict:
        try:
            with open("treasury_harvest.json") as f:
                return json.load(f)
        except Exception:
            return {"status": "IDLE"}

    def _save_harvest_state(self, state: dict) -> None:
        try:
            with open("treasury_harvest.json", "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"TreasuryAgent: harvest state save failed: {e}")

    def _open_harvest_position(self, asset: str, rate_pct: float) -> bool:
        """Open a market short on HL for funding harvest. Returns True on success."""
        if not self.exchange_client:
            return False
        try:
            price = self.exchange_client.get_market_price(asset)
            if not price or price <= 0:
                logger.warning(f"TreasuryAgent: harvest — no price for {asset}")
                return False

            size = round(self._HARVEST_MAX_NOTIONAL / price, 6)
            notional = size * price
            if notional < 10:
                logger.warning(f"TreasuryAgent: harvest — notional ${notional:.2f} below $10 HL minimum")
                return False

            order = self.exchange_client.create_order(asset, "SELL", size, order_type="market")
            if not order:
                logger.error(f"TreasuryAgent: harvest — order placement failed for {asset}")
                return False

            fill_price = float(order.get("average") or order.get("price") or price)
            trade_id   = f"HARVEST_{asset}_{int(datetime.utcnow().timestamp() * 1000)}"
            now_iso    = datetime.utcnow().isoformat()

            # Add to trade_log so execution_agent doesn't reconcile it as phantom
            harvest_record = {
                "id":           trade_id,
                "ticker":       asset,
                "action":       "SELL",
                "status":       "OPEN",
                "harvest":      True,   # guards: execution_agent + strategy_manager skip this
                "entry_price":  fill_price,
                "quantity":     size,
                "size_usd":     round(notional, 2),
                "entry_time":   datetime.utcnow().timestamp(),
                "pnl":          0.0,
                "rate_at_open": rate_pct,
                "analyst_signals": {},
            }
            try:
                with open("trade_log.json") as f:
                    log = json.load(f)
                if isinstance(log, dict):
                    log[trade_id] = harvest_record
                else:
                    log.append(harvest_record)
                with open("trade_log.json", "w") as f:
                    json.dump(log, f, indent=2)
            except Exception as e:
                logger.warning(f"TreasuryAgent: harvest — trade_log update failed: {e}")

            self._save_harvest_state({
                "status":       "ACTIVE",
                "asset":        asset,
                "side":         "short",
                "size":         size,
                "notional_usd": round(notional, 2),
                "entry_price":  fill_price,
                "trade_id":     trade_id,
                "opened_at":    now_iso,
                "max_close_at": datetime.utcnow().timestamp() + self._HARVEST_MAX_HOLD_H * 3600,
                "rate_at_open": rate_pct,
                "last_rate":    rate_pct,
                "last_check":   now_iso,
            })

            logger.info(
                f"💱 TreasuryAgent: harvest SHORT opened — {asset} {size:.6f} "
                f"@ ${fill_price:.2f} | funding {rate_pct:.4f}%/8h "
                f"({rate_pct * 3 * 365:.1f}% APR)"
            )
            self._send_telegram(
                f"💱 *Treasury: Funding Harvest gestart*\n"
                f"SHORT {asset} {size:.6f} (${notional:.0f} notional)\n"
                f"Funding: {rate_pct:.4f}%/8h = {rate_pct * 3 * 365:.1f}% APR\n"
                f"Auto-close na {self._HARVEST_MAX_HOLD_H}h of rate < {self._HARVEST_CLOSE_RATE_8H:.3f}%/8h"
            )
            return True
        except Exception as e:
            logger.error(f"TreasuryAgent: harvest open failed: {e}")
            return False

    def _close_harvest_position(self, state: dict, reason: str) -> bool:
        """Close the active harvest short. Returns True on success."""
        if not self.exchange_client:
            return False
        try:
            asset    = state.get("asset", "")
            size     = float(state.get("size", 0))
            trade_id = state.get("trade_id", "")
            if not asset or size <= 0:
                return False

            order = self.exchange_client.create_order(asset, "BUY", size, order_type="market")
            if not order:
                logger.error(f"TreasuryAgent: harvest close — order failed for {asset}")
                return False

            fill_price   = float(order.get("average") or order.get("price") or state.get("entry_price", 0))
            entry_price  = float(state.get("entry_price", fill_price))
            pnl          = round((entry_price - fill_price) * size, 4)
            now_iso      = datetime.utcnow().isoformat()

            # Mark trade_log entry CLOSED
            if trade_id:
                try:
                    with open("trade_log.json") as f:
                        log = json.load(f)
                    update = {"status": "CLOSED", "exit_price": fill_price,
                              "pnl": pnl, "close_reason": reason, "exit_time": now_iso}
                    if isinstance(log, dict):
                        if trade_id in log:
                            log[trade_id].update(update)
                    else:
                        for t in log:
                            if t.get("id") == trade_id:
                                t.update(update)
                                break
                    with open("trade_log.json", "w") as f:
                        json.dump(log, f, indent=2)
                except Exception as e:
                    logger.warning(f"TreasuryAgent: harvest close — trade_log update failed: {e}")

            self._save_harvest_state({"status": "IDLE"})
            logger.info(f"💱 TreasuryAgent: harvest closed — {asset} @ ${fill_price:.2f} pnl=${pnl:.2f} reason={reason}")
            self._send_telegram(
                f"✅ *Treasury: Funding Harvest gesloten*\n"
                f"SHORT {asset} @ ${fill_price:.2f} | P&L: ${pnl:+.2f}\n"
                f"Reden: {reason}"
            )
            return True
        except Exception as e:
            logger.error(f"TreasuryAgent: harvest close failed: {e}")
            return False

    def _check_funding_harvest(self) -> None:
        """Open a harvest short if conditions are met. Called from run()."""
        state = self._get_harvest_state()
        if state.get("status") != "IDLE":
            return
        if not self.exchange_client:
            return
        try:
            rates = self._get_hl_funding_rates()
        except Exception as e:
            logger.debug(f"TreasuryAgent: funding rate fetch failed: {e}")
            return

        candidates = [
            (asset, rate) for asset, rate in rates.items()
            if asset in self._HARVEST_ALLOWED_ASSETS and rate >= self._HARVEST_MIN_RATE_8H
        ]
        if not candidates:
            logger.debug(
                f"TreasuryAgent: no harvest candidate "
                f"(best BTC={rates.get('BTC',0):.4f}% ETH={rates.get('ETH',0):.4f}%/8h, "
                f"threshold={self._HARVEST_MIN_RATE_8H}%)"
            )
            return

        asset, rate = max(candidates, key=lambda x: x[1])
        logger.info(f"💱 TreasuryAgent: harvest candidate — {asset} @ {rate:.4f}%/8h ({rate*3*365:.1f}% APR)")
        self._open_harvest_position(asset, rate)

    def _monitor_funding_harvest(self) -> None:
        """Monitor open harvest position; close if conditions no longer met. Called from run() + run_fast()."""
        state = self._get_harvest_state()
        if state.get("status") != "ACTIVE":
            return
        if not self.exchange_client:
            return

        asset     = state.get("asset", "")
        max_close = float(state.get("max_close_at", 0))
        now       = datetime.utcnow().timestamp()

        # 1. Max hold time
        if max_close > 0 and now >= max_close:
            logger.info(f"TreasuryAgent: harvest — max hold {self._HARVEST_MAX_HOLD_H}h reached for {asset}")
            self._close_harvest_position(state, f"max_hold_{self._HARVEST_MAX_HOLD_H}h")
            return

        # 2. Check current funding rate
        try:
            rates = self._get_hl_funding_rates()
        except Exception as e:
            logger.debug(f"TreasuryAgent: harvest rate check failed: {e}")
            return

        current_rate = rates.get(asset, 0.0)
        state["last_rate"]  = current_rate
        state["last_check"] = datetime.utcnow().isoformat()
        self._save_harvest_state(state)

        if current_rate < self._HARVEST_CLOSE_RATE_8H:
            logger.info(
                f"TreasuryAgent: harvest — {asset} rate {current_rate:.4f}%/8h "
                f"< {self._HARVEST_CLOSE_RATE_8H}%/8h → closing"
            )
            self._close_harvest_position(
                state, f"rate_below_threshold ({current_rate:.4f}%/8h)"
            )
            return

        # 3. Confirm position still live on HL (guard against external closure)
        try:
            positions = self.exchange_client.fetch_all_positions()
            live = [
                p for p in positions
                if p.get("symbol", "").split("/")[0].upper() == asset.upper()
                and abs(float((p.get("info") or {}).get("szi", 0) or p.get("contracts") or 0)) > 1e-9
            ]
            if not live:
                logger.warning(f"TreasuryAgent: harvest — {asset} no longer on HL (externally closed)")
                trade_id = state.get("trade_id", "")
                if trade_id:
                    try:
                        with open("trade_log.json") as f:
                            log = json.load(f)
                        update = {"status": "CLOSED", "close_reason": "external_closure",
                                  "exit_time": datetime.utcnow().isoformat()}
                        if isinstance(log, dict):
                            if trade_id in log:
                                log[trade_id].update(update)
                        else:
                            for t in log:
                                if t.get("id") == trade_id:
                                    t.update(update); break
                        with open("trade_log.json", "w") as f:
                            json.dump(log, f, indent=2)
                    except Exception:
                        pass
                self._save_harvest_state({"status": "IDLE"})
                return
        except Exception as e:
            logger.debug(f"TreasuryAgent: harvest position check failed: {e}")

        logger.info(
            f"💱 TreasuryAgent: harvest OK — {asset} rate={current_rate:.4f}%/8h "
            f"(open={state.get('rate_at_open', 0):.4f}%/8h, "
            f"hold={int((now - float(state.get('opened_at', now) if isinstance(state.get('opened_at'), (int,float)) else now)) / 3600 + 1)}h)"
        )

    # ── Execution ─────────────────────────────────────────────────────────────

    def execute_approved_proposals(self, all_proposals: list) -> list:
        """Advance state machine for all active (non-terminal) proposals."""
        from utils.treasury_executor import advance_proposal, get_executor_private_key

        private_key, wallet_address = get_executor_private_key()
        active = {
            "APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED",
            "MONITORING", "REBALANCING", "BRIDGE_BACK_NEEDED", "BRIDGING_TO_HL",
            "SWITCHING",
        }

        for i, p in enumerate(all_proposals):
            if p.get("status") in active:
                all_proposals[i] = advance_proposal(
                    p,
                    exchange_client=self.exchange_client,
                    private_key=private_key,
                    wallet_address=wallet_address,
                    telegram_fn=self._send_telegram,
                )
        return all_proposals

    # ── Fast path (every 5 cycles) ────────────────────────────────────────────

    def run_fast(self) -> None:
        """
        Lightweight execution-only pass. Called every 5 cycles (~5 min).
        Uses cached yield data from last full run() to avoid DeFiLlama API call.
        """
        from utils.treasury_executor import get_arb_usdc_balance, _TREASURY_WALLET

        hl            = self.get_hl_snapshot()
        all_proposals = self._load_proposals()

        # Check if rebalance is needed (HL margin < 25% of total capital)
        all_proposals = self._check_rebalance_needed(hl, all_proposals)

        # Yield switch + HL excess checks using cached opportunities (avoid DeFiLlama call in fast path)
        cached_opps = self._load_cached_opportunities()
        switch_notifs: list[str] = []
        diversify_notifs: list[str] = []
        if cached_opps:
            try:
                yield_balances = self._get_yield_balances()
                all_proposals, switch_notifs = self._check_yield_switch(cached_opps, yield_balances, all_proposals)
                all_proposals, diversify_notifs = self._check_yield_diversification(cached_opps, yield_balances, all_proposals)
            except Exception as e:
                logger.debug(f"TreasuryAgent fast: yield switch/diversification check failed: {e}")
            try:
                all_proposals = self._check_hl_excess(hl, all_proposals, cached_opps)
            except Exception as e:
                logger.debug(f"TreasuryAgent fast: HL excess check failed: {e}")

        # Monitor open funding harvest position
        self._monitor_funding_harvest()

        # Detect treasury wallet USDC — generate proposal if none in-flight.
        # Also skip when a YIELD_SWITCH is SWITCHING: that USDC belongs to the switch.
        in_flight = {"APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED"}
        has_in_flight = (
            any(p.get("type") == "DEPLOY_YIELD" and p.get("status") in in_flight for p in all_proposals)
            or any(p.get("type") == "YIELD_SWITCH" and p.get("status") == "SWITCHING" for p in all_proposals)
        )
        if not has_in_flight:
            treasury_usdc = get_arb_usdc_balance(_TREASURY_WALLET)
            if treasury_usdc >= _MIN_DEPLOY_USD:
                cached_opps = self._load_cached_opportunities()
                if cached_opps:
                    new_proposals = self.generate_proposals(hl, cached_opps, treasury_usdc=treasury_usdc)
                    if new_proposals:
                        self._upsert_proposals(new_proposals)
                        all_proposals = self._load_proposals()
                        logger.info(f"💰 TreasuryAgent fast: ${treasury_usdc:.0f} treasury USDC → proposal created")
                else:
                    logger.debug("TreasuryAgent fast: no cached yield data yet — skipping proposal generation")
        else:
            treasury_usdc = 0.0

        # Advance any APPROVED / in-flight proposals (including FUND_TRADING MONITORING)
        active = {
            "APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED",
            "REBALANCING", "MONITORING", "BRIDGE_BACK_NEEDED", "BRIDGING_TO_HL",
            "SWITCHING",
        }
        has_active = any(p.get("status") in active for p in all_proposals)
        if has_active:
            all_proposals = self.execute_approved_proposals(all_proposals)
        self._save_proposals(all_proposals)
        for msg in switch_notifs:
            self._send_telegram(msg)
        for msg in diversify_notifs:
            self._send_telegram(msg)
        logger.info("💰 TreasuryAgent fast run: complete")

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> dict:
        logger.info("💰 TreasuryAgent: analysing capital efficiency...")
        from utils.treasury_executor import get_arb_usdc_balance, get_aave_balance, _TREASURY_WALLET

        hl            = self.get_hl_snapshot()
        opportunities = self.get_yield_opportunities()
        treasury_usdc = get_arb_usdc_balance(_TREASURY_WALLET)

        # Fetch all deployed yield balances (Aave + ERC-4626 vaults + future protocols)
        yield_balances: dict[str, float] = {}
        try:
            yield_balances = self._get_yield_balances()
        except Exception as e:
            logger.warning(f"Yield balance fetch failed: {e}")

        total_yield   = sum(yield_balances.values())
        aave_balance  = yield_balances.get("aave-v3-arbitrum-usdc", 0.0)  # kept for proposal generation compat
        total_portfolio = round(hl.get("balance", 0) + total_yield + treasury_usdc, 2)
        allocation = self._compute_target_allocation(total_portfolio) if total_portfolio > 0 else {}

        # Generate proposals only if none are already in-flight (avoid duplicates).
        # Also block when a YIELD_SWITCH is SWITCHING: the USDC in the treasury wallet
        # already belongs to that switch and must not be claimed by a new DEPLOY_YIELD.
        all_proposals = self._load_proposals()
        in_flight = {"APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED"}
        has_in_flight = (
            any(p.get("type") == "DEPLOY_YIELD" and p.get("status") in in_flight for p in all_proposals)
            or any(p.get("type") == "YIELD_SWITCH" and p.get("status") == "SWITCHING" for p in all_proposals)
        )
        new_ones: list[dict] = []
        if not has_in_flight:
            proposals = self.generate_proposals(
                hl, opportunities,
                treasury_usdc=treasury_usdc,
                aave_balance=aave_balance,
                yield_balances=yield_balances,
            )
            new_ones  = self._upsert_proposals(proposals)
            all_proposals = self._load_proposals()

        # Auto-rebalance: pull funds back from Aave if HL margin is getting tight
        all_proposals = self._check_rebalance_needed(hl, all_proposals)

        # Auto HL excess: move surplus above trading target to best yield protocol
        all_proposals = self._check_hl_excess(hl, all_proposals, opportunities)

        # Auto yield-switch: move capital to highest-APY automated protocol if spread > threshold
        all_proposals, _switch_notifs = self._check_yield_switch(opportunities, yield_balances, all_proposals)

        # Auto yield-diversification: partial switch when one protocol > _MAX_SINGLE_CONCENTRATION
        all_proposals, _diversify_notifs = self._check_yield_diversification(opportunities, yield_balances, all_proposals)

        # Funding harvest: open/monitor HL short when funding rate is high
        self._check_funding_harvest()
        self._monitor_funding_harvest()

        # Advance state machine for any approved/in-progress proposals
        all_proposals = self.execute_approved_proposals(all_proposals)
        self._save_proposals(all_proposals)

        state = {
            "hl_snapshot":          hl,
            "aave_balance":         round(aave_balance, 2),
            "yield_balances":       {k: round(v, 2) for k, v in yield_balances.items()},
            "total_yield":          round(total_yield, 2),
            "treasury_wallet_usdc": round(treasury_usdc, 2),
            "total_portfolio":      total_portfolio,
            "allocation":           allocation,
            "opportunities":        opportunities,
            "proposals":            all_proposals,
            "pending_count":        sum(1 for p in all_proposals if p.get("status") == "PENDING"),
            "funding_harvest":      self._get_harvest_state(),
            "timestamp":            datetime.utcnow().isoformat(),
        }

        try:
            with open("treasury_state.json", "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save treasury_state: {e}")

        # Telegram for yield switch / diversification notifications (sent after save)
        for msg in _switch_notifs:
            self._send_telegram(msg)
        for msg in _diversify_notifs:
            self._send_telegram(msg)

        # Telegram for genuinely new proposals
        for p in new_ones:
            ptype  = p.get("type", "")
            status = p.get("status", "PENDING")
            if ptype == "FUND_TRADING":
                action_line = "_Handmatige stap vereist — zie stappen hieronder_"
            elif status == "APPROVED":
                action_line = "🤖 _Wordt automatisch uitgevoerd_"
            else:
                action_line = f"✅ `/approve {p['id']}` · 🚫 `/reject {p['id']}`"
            msg = (
                f"💰 *Treasury Voorstel* — `{p['id']}`\n"
                f"*{p['title']}*\n\n"
                f"{p['rationale']}\n\n"
                f"{action_line}"
            )
            self._send_telegram(msg)
            logger.info(f"📨 Treasury proposal sent: {p['id']}")

        opp_str = f"{opportunities[0]['apy']:.1f}% ({opportunities[0]['label']})" if opportunities else "—"
        logger.info(
            f"💰 Treasury: HL idle={hl.get('idle_pct', 0):.0f}% (${hl.get('free_margin', 0):.0f}) | "
            f"treasury wallet=${treasury_usdc:.0f} | "
            f"best yield={opp_str} | {len(new_ones)} new proposal(s)"
        )
        return state
