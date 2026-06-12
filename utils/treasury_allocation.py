"""
AllocationOptimizer — Gemini LLM-based multi-protocol capital allocation.

Replaces the "all capital → single best protocol" logic with a structured
LLM call that reasons over risk/reward, liquidity needs, and tranche targets.

Tranche targets (soft constraints, ±10pp flexibility):
  liquidity_reserve  ~15%  — Aave v3 (instant exit)
  yield_core         ~65%  — Morpho (1-3d exit)
  opportunistic      ~20%  — Gains Network, Funding Harvest

Fallback: if LLM fails or returns invalid JSON, uses rule-based allocation
(all capital to the highest risk-adjusted APY automated Arbitrum protocol).

Usage:
    from utils.treasury_allocation import AllocationOptimizer
    optimizer = AllocationOptimizer()
    allocations = optimizer.optimize(to_yield, opportunities, current_allocation)
    # returns [{"protocol_id", "protocol_config", "tranche", "amount_usd", "rationale"}, ...]
"""

import json
import logging
import re

logger = logging.getLogger("AllocationOptimizer")

_MIN_ALLOC_USD      = 50.0   # skip a tranche if its amount is below this
_SPLIT_THRESHOLD    = 150.0  # below this total, skip multi-protocol split (gas inefficient)
_TRANCHE_TARGETS    = {"liquidity_reserve": 15, "yield_core": 65, "opportunistic": 20}
_PCT_SUM_TOLERANCE  = 5      # allow ±5pp rounding slop in LLM output


class AllocationOptimizer:
    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            try:
                from utils.llm_client import LLMClient
                self._llm = LLMClient()
            except Exception as e:
                logger.warning(f"AllocationOptimizer: LLM init failed ({e}) — rule-based fallback only")
                self._llm = False  # sentinel: tried and failed
        return self._llm if self._llm else None

    # ── Prompt building ───────────────────────────────────────────────────────

    def _build_prompt(
        self,
        total_usd: float,
        automated_opps: list[dict],
        current_allocation: dict,
    ) -> str:
        rows = []
        for o in automated_opps:
            pid   = (o.get("protocol_config") or {}).get("id", "?")
            rs    = o.get("risk_score") or {}
            rows.append(
                f"  {pid}: APY={o.get('apy', 0):.2f}% | "
                f"risk_adj_APY={o.get('risk_adjusted_apy', 0):.2f}% | "
                f"risk={rs.get('label','?')} ({rs.get('overall',0):.2f}) | "
                f"tranche={rs.get('tranche','?')} | "
                f"TVL=${o.get('tvl_usd',0)/1e6:.1f}M"
            )

        current_str = (
            ", ".join(f"{k}: ${v:.0f}" for k, v in current_allocation.items() if v > 0)
            or "nothing deployed yet"
        )

        tranche_str = "\n".join(
            f"  - {t} ({pct}%): ${total_usd * pct / 100:.0f}"
            for t, pct in _TRANCHE_TARGETS.items()
        )

        protocol_block = "\n".join(rows) if rows else "  (none available)"

        return f"""You are a treasury allocation optimizer for a crypto trading system on Arbitrum.

TASK: Allocate ${total_usd:.2f} USDC across yield protocols to maximize risk-adjusted return while maintaining operational liquidity.

AVAILABLE PROTOCOLS (automated, Arbitrum only):
{protocol_block}

CURRENT DEPLOYMENT: {current_str}

TRANCHE TARGETS (soft constraints — deviate up to ±10pp if risk/reward strongly favors it):
{tranche_str}

RULES:
1. Only allocate to protocols listed above (use exact protocol_id strings)
2. allocation_pct values must sum to exactly 100
3. Minimum ${_MIN_ALLOC_USD:.0f} per protocol — round down and skip if below
4. If a tranche has no suitable protocol, fold its allocation into the next-best tranche
5. Briefly justify each decision (1 sentence)

Respond ONLY with a JSON array — no markdown, no commentary:
[
  {{"protocol_id": "aave-v3-arbitrum-usdc", "allocation_pct": 15, "rationale": "..."}},
  {{"protocol_id": "morpho-bbqusdc-arbitrum", "allocation_pct": 65, "rationale": "..."}},
  {{"protocol_id": "gains-network-arbitrum-usdc", "allocation_pct": 20, "rationale": "..."}}
]"""

    # ── LLM call + parse ──────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> list[dict]:
        """Call LLM, extract JSON array, validate structure. Raises on any failure."""
        llm = self._get_llm()
        if not llm:
            raise RuntimeError("LLM unavailable")

        raw = llm.analyze_text(prompt, agent_name="AllocationOptimizer", thinking=False)

        # Strip markdown fences if present
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        # Find outermost JSON array
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON array in LLM response: {raw[:200]}")

        allocations = json.loads(m.group())
        if not isinstance(allocations, list) or not allocations:
            raise ValueError("LLM returned empty or non-list allocation")

        # Validate each entry
        valid_ids = set()  # populated by caller
        for entry in allocations:
            if not isinstance(entry, dict):
                raise ValueError(f"Non-dict entry: {entry}")
            if "protocol_id" not in entry or "allocation_pct" not in entry:
                raise ValueError(f"Missing required keys in: {entry}")

        return allocations

    # ── Validation + normalization ────────────────────────────────────────────

    def _validate_and_build(
        self,
        llm_allocations: list[dict],
        total_usd: float,
        automated_opps: list[dict],
    ) -> list[dict]:
        """
        Validate LLM output against available protocols, normalize pcts to sum to 100,
        apply minimum allocation filter. Returns final allocation list.
        Raises ValueError if result is unusable.
        """
        valid_opps = {
            (o.get("protocol_config") or {}).get("id", ""): o
            for o in automated_opps
            if (o.get("protocol_config") or {}).get("id")
        }

        # Sanity check BEFORE filtering: catch garbage LLM output (e.g. all pcts = 5 or 500)
        pre_sum = sum(a.get("allocation_pct", 0) for a in llm_allocations)
        if abs(pre_sum - 100) > _PCT_SUM_TOLERANCE:
            raise ValueError(f"LLM allocation_pct sums to {pre_sum:.1f} before filtering (expected 100 ±{_PCT_SUM_TOLERANCE})")

        # Filter to only valid protocol IDs (invalid IDs silently dropped)
        filtered = [a for a in llm_allocations if a.get("protocol_id") in valid_opps]
        if not filtered:
            raise ValueError("No valid protocol IDs in LLM response")

        # Normalize after filtering so remaining entries always sum to 100%
        pct_sum = sum(a["allocation_pct"] for a in filtered)
        scale   = 100.0 / pct_sum if pct_sum > 0 else 1.0

        result = []
        for a in filtered:
            pct      = a["allocation_pct"] * scale
            amount   = round(total_usd * pct / 100, 2)
            if amount < _MIN_ALLOC_USD:
                logger.info(f"AllocationOptimizer: skipping {a['protocol_id']} (${amount:.0f} < min ${_MIN_ALLOC_USD:.0f})")
                continue
            opp = valid_opps[a["protocol_id"]]
            rs  = opp.get("risk_score") or {}
            result.append({
                "protocol_id":     a["protocol_id"],
                "protocol_config": opp.get("protocol_config"),
                "tranche":         rs.get("tranche", "yield_core"),
                "amount_usd":      amount,
                "apy":             opp.get("apy", 0),
                "risk_adjusted_apy": opp.get("risk_adjusted_apy", 0),
                "rationale":       a.get("rationale", ""),
            })

        if not result:
            raise ValueError("All allocations below minimum after filtering")

        # Ensure amounts sum to total_usd (fix rounding)
        total_allocated = sum(r["amount_usd"] for r in result)
        if result and abs(total_allocated - total_usd) > 1.0:
            # Adjust largest entry
            diff = total_usd - total_allocated
            largest_idx = max(range(len(result)), key=lambda i: result[i]["amount_usd"])
            result[largest_idx]["amount_usd"] = round(result[largest_idx]["amount_usd"] + diff, 2)

        return result

    # ── Rule-based fallback ───────────────────────────────────────────────────

    def _rule_based_fallback(
        self,
        total_usd: float,
        automated_opps: list[dict],
    ) -> list[dict]:
        """Single-protocol allocation to highest risk-adjusted APY. Always succeeds."""
        if not automated_opps:
            return []

        best = max(automated_opps, key=lambda o: o.get("risk_adjusted_apy") or o.get("apy", 0))
        pid  = (best.get("protocol_config") or {}).get("id", "")
        rs   = best.get("risk_score") or {}

        logger.info(
            f"AllocationOptimizer: rule-based fallback → {pid} "
            f"(risk_adj_APY={best.get('risk_adjusted_apy', best.get('apy', 0)):.2f}%)"
        )
        return [{
            "protocol_id":       pid,
            "protocol_config":   best.get("protocol_config"),
            "tranche":           rs.get("tranche", "yield_core"),
            "amount_usd":        total_usd,
            "apy":               best.get("apy", 0),
            "risk_adjusted_apy": best.get("risk_adjusted_apy", 0),
            "rationale":         f"Rule-based: best risk-adjusted APY among automated Arbitrum protocols.",
        }]

    # ── Main entry point ──────────────────────────────────────────────────────

    def optimize(
        self,
        total_usd: float,
        opportunities: list[dict],
        current_allocation: dict | None = None,
    ) -> list[dict]:
        """
        Compute optimal capital allocation across protocols.

        Args:
            total_usd:          USDC to allocate (from treasury wallet, post HL top-up)
            opportunities:      enriched list from get_yield_opportunities() (has risk_score, risk_adjusted_apy)
            current_allocation: {protocol_id: amount_usd} already deployed

        Returns:
            List of allocation dicts with protocol_id, amount_usd, tranche, rationale.
            Empty list means nothing to deploy (total_usd below thresholds).
        """
        if total_usd < _MIN_ALLOC_USD:
            return []

        # Liquidity guard (mirrors _pick_best_protocol): never allocate into
        # epoch-based vaults (immediate_withdraw=false, e.g. Gains gUSDC) — once
        # deposited the capital cannot be auto-withdrawn, so diversification and
        # HL rebalancing stall on a manual epoch request.
        automated_arb = [
            o for o in opportunities
            if o.get("automated") and (o.get("chain") or "").lower() == "arbitrum"
            and bool((o.get("protocol_config") or {}).get("immediate_withdraw", True))
        ]
        if not automated_arb:
            logger.warning("AllocationOptimizer: no automated Arbitrum protocols available")
            return []

        # Below split threshold: no LLM call, all to best single protocol (gas efficiency)
        if total_usd < _SPLIT_THRESHOLD or len(automated_arb) < 2:
            return self._rule_based_fallback(total_usd, automated_arb)

        # Try LLM allocation
        try:
            prompt       = self._build_prompt(total_usd, automated_arb, current_allocation or {})
            llm_result   = self._call_llm(prompt)
            allocations  = self._validate_and_build(llm_result, total_usd, automated_arb)
            logger.info(
                f"AllocationOptimizer: LLM allocation — "
                + ", ".join(f"{a['protocol_id'].split('-')[0]} ${a['amount_usd']:.0f}" for a in allocations)
            )
            return allocations
        except Exception as e:
            logger.warning(f"AllocationOptimizer: LLM failed ({e}) — rule-based fallback")
            return self._rule_based_fallback(total_usd, automated_arb)
