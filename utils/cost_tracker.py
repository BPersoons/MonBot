"""
cost_tracker.py — Daily cost and ROI aggregator.

Reads:
  - llm_usage.json  (token usage, written by LLMClient)
  - trade_log.json  (P&L and trade sizes)

Writes:
  - cost_log.json   (rolling 30-day history, keyed by date)

Exposes:
  - get_daily_summary() -> dict   (today's snapshot, upserted into history)
  - get_history()       -> dict   (all stored daily snapshots)
  - get_net_roi()       -> float  (trading P&L minus all costs for today)
  - get_llm_cost()      -> float
"""

import json
import logging
import os
from datetime import date
from typing import Dict

logger = logging.getLogger("CostTracker")

COST_LOG_FILE  = "cost_log.json"
LLM_USAGE_FILE = "llm_usage.json"
TRADE_LOG_FILE = "trade_log.json"

# Infrastructuurkosten per dag. Override via env var INFRA_COST_USD_DAILY.
#
# Stond op 1,00 met de toelichting "GCP e2-medium ~$30/month". De VM is echter
# een **e2-small** in europe-west1 en kost ~$160/jaar = ~$0,44/dag — de teller
# overdreef de kosten 2,3×. Gecorrigeerd 2026-08-12, gemeten via
# `gcloud compute instances describe` (machineType = e2-small).
#
# Dit is niet cosmetisch: dit getal is de noemer waartegen elke feature wordt
# afgewogen (zie docs/PLAN_2026-08.md par. 3, memory project_product_economics).
# Een verkeerde kostenbasis maakt elk rendement kunstmatig hopeloos.
#
# Bij een migratie naar e2-micro: ~$0,22. Verander dan ook deze waarde.
INFRA_COST_USD_DAILY = float(os.getenv("INFRA_COST_USD_DAILY", "0.44"))

# Hyperliquid taker fee (0.05%); two legs per closed trade
HL_TAKER_FEE_RATE = 0.0005

# Gemini 2.5 Flash per-type pricing (USD per token)
LLM_COST_INPUT_PER_TOKEN    = 0.15  / 1_000_000   # $0.15/M
LLM_COST_OUTPUT_PER_TOKEN   = 0.60  / 1_000_000   # $0.60/M
LLM_COST_THINKING_PER_TOKEN = 3.50  / 1_000_000   # $3.50/M (thinking tokens)


class CostTracker:
    """Computes daily cost/ROI snapshot and writes it to cost_log.json."""

    def get_daily_summary(self) -> Dict:
        """Compute today's cost summary. Writes cost_log.json. Returns full breakdown."""
        today = date.today().isoformat()

        inp, out, think, llm_cost = self._get_llm_cost_breakdown()
        fees        = self._calc_exchange_fees(today)
        pnl         = self._calc_trading_pnl(today)
        total_cost  = round(llm_cost + INFRA_COST_USD_DAILY + fees, 4)
        net_roi     = round(pnl - total_cost, 4)

        # Cost per executed trade (avoid division by zero)
        trades_today = self._count_closed_trades(today)
        cost_per_trade = round(total_cost / trades_today, 4) if trades_today else 0.0

        summary = {
            "period":                today,
            "llm_tokens_used":       inp + out + think,
            "llm_input_tokens":      inp,
            "llm_output_tokens":     out,
            "llm_thinking_tokens":   think,
            "llm_cost_usd":          llm_cost,
            "infra_cost_usd_daily":  INFRA_COST_USD_DAILY,
            "exchange_fees_usd":     fees,
            "total_cost_usd":        total_cost,
            "trading_pnl_usd":       pnl,
            "net_roi_usd":           net_roi,
            "trades_today":          trades_today,
            "cost_per_executed_trade": cost_per_trade,
        }

        self._write_log(summary)
        return summary

    def get_net_roi(self) -> float:
        """Return today's net ROI (trading P&L minus all costs). Negative = losing money."""
        try:
            return self.get_daily_summary()["net_roi_usd"]
        except Exception as e:
            logger.debug(f"CostTracker.get_net_roi failed: {e}")
            return 0.0

    def get_llm_cost(self) -> float:
        _, _, _, cost = self._get_llm_cost_breakdown()
        return cost

    def get_history(self) -> Dict:
        """Return the full stored history dict (date -> summary). Empty dict if no file yet."""
        try:
            with open(COST_LOG_FILE, "r") as f:
                data = json.load(f)
            return data.get("history", {})
        except Exception:
            return {}

    # ─────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────

    def _get_llm_cost_breakdown(self) -> tuple:
        """Returns (input_tokens, output_tokens, thinking_tokens, total_cost_usd)."""
        try:
            with open(LLM_USAGE_FILE, "r") as f:
                data = json.load(f)
            acc = data.get("accumulator", {})
            inp = out = think = 0
            for stats in acc.values():
                inp   += stats.get("today_input", 0)
                out   += stats.get("today_output", 0)
                think += stats.get("today_thinking", 0)
            cost = (
                inp   * LLM_COST_INPUT_PER_TOKEN
                + out   * LLM_COST_OUTPUT_PER_TOKEN
                + think * LLM_COST_THINKING_PER_TOKEN
            )
            return inp, out, think, round(cost, 4)
        except Exception:
            return 0, 0, 0, 0.0

    def _load_trades(self):
        try:
            with open(TRADE_LOG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _calc_exchange_fees(self, today: str) -> float:
        fees = 0.0
        for t in self._load_trades():
            if t.get("status") != "CLOSED":
                continue
            if not str(t.get("exit_time", "")).startswith(today):
                continue
            notional = float(t.get("entry_price") or 0) * float(t.get("size") or 0)
            fees += notional * HL_TAKER_FEE_RATE * 2  # entry + exit legs
        return round(fees, 4)

    def _calc_trading_pnl(self, today: str) -> float:
        pnl = 0.0
        for t in self._load_trades():
            if t.get("status") != "CLOSED":
                continue
            if not str(t.get("exit_time", "")).startswith(today):
                continue
            pnl += float(t.get("pnl") or 0)
        return round(pnl, 4)

    def _count_closed_trades(self, today: str) -> int:
        return sum(
            1 for t in self._load_trades()
            if t.get("status") == "CLOSED"
            and str(t.get("exit_time", "")).startswith(today)
        )

    def _write_log(self, summary: dict):
        """Upsert today's summary into the rolling 30-day history in cost_log.json."""
        _HISTORY_DAYS = 30
        try:
            # Load existing history, or start fresh
            try:
                with open(COST_LOG_FILE, "r") as f:
                    existing = json.load(f)
                history = existing.get("history", {})
            except Exception:
                history = {}

            # Upsert today
            history[summary["period"]] = summary

            # Trim to last 30 days (sorted descending by date string — ISO format sorts correctly)
            if len(history) > _HISTORY_DAYS:
                for old_key in sorted(history.keys())[:-_HISTORY_DAYS]:
                    del history[old_key]

            with open(COST_LOG_FILE, "w") as f:
                json.dump({"history": history}, f, indent=2)
        except Exception as e:
            logger.debug(f"CostTracker: could not write {COST_LOG_FILE}: {e}")
