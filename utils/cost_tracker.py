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
import math
import os
from datetime import date
from typing import Dict

logger = logging.getLogger("CostTracker")

COST_LOG_FILE  = "cost_log.json"
LLM_USAGE_FILE = "llm_usage.json"
TRADE_LOG_FILE = "trade_log.json"

# Infrastructuurkosten per dag = rekenkracht van de VM + vaste bijkosten.
#
# Dit getal is de noemer van H1 (netto winst) en van elke kosten-batenafweging.
# Geschiedenis: tot 2026-08-12 stond hier 1,00 ("e2-medium"), daarna een vaste
# 0,44 (alleen de e2-small). Een vast getal veroudert stil bij elke verkleining,
# daarom volgt de rekenkracht nu het machinetype dat de VM zelf opgeeft.
#
# Prijzen: Cloud Billing Catalog, listprijs europe-west1, gemeten 2026-09-17
# (docs/audits/2026-09-17-m4-kosten-herzien.md). Rekenkracht per dag (730 u/mnd):
_COMPUTE_USD_PER_DAG = {
    "e2-micro": 0.221,    # 0,25 vCPU + 1 GB
    "e2-small": 0.442,    # 0,5 vCPU + 2 GB
    "e2-medium": 0.884,   # 1 vCPU + 4 GB
}
# Onbekend of onleesbaar machinetype → de duurste bekende. Onmeetbaar is nooit
# goedkoop: een te lage kostenbasis laat H1 er beter uitzien dan hij is.
_COMPUTE_ONBEKEND = max(_COMPUTE_USD_PER_DAG.values())
# Vaste bijkosten per dag, GEMETEN op de factuur (Billing → Reports per SKU, september 2026,
# omgerekend met EUR/USD 1,15). Dit verving de conservatieve schatting van 0,232:
#   schijf 30 GB pd-standard 0,015   (€0,013 — de gratis 30 GiB geldt, maar wordt met andere
#                                     schijven van het account gedeeld)
#   secrets 0,035                    (€0,030 — 28 actieve versies, 6 gratis)
#   registry 0,009                   (€0,008 nu; met 1-2 images zakt dit naar ~0,003)
#   uitgaand verkeer 0,002           (~0,11 GB/dag; staat nauwelijks op de factuur)
#   extern IP 0,000                  (staat NIET op de factuur: de staffel van 720 u/mnd geldt,
#                                     anders dan de VPC-prijspagina zegt)
# De rekenkracht hieronder blijft de listprijs uit de catalogus; de factuur gaf €0,353/dag
# (~$0,407) voor de e2-small, dus die kant is nog licht aan de voorzichtige kant.
_BIJKOSTEN_USD_PER_DAG = 0.061

_METADATA_URL = "http://metadata.google.internal/computeMetadata/v1/instance/machine-type"
_MISLUKT_OPNIEUW_SEC = 3600
_machinetype_cache: Dict[str, object] = {}


def _machinetype() -> str:
    """Machinetype van deze VM volgens de metadataserver ('' als onleesbaar).

    Een gelezen waarde geldt voor het hele proces: verkleinen kan alleen met
    stop/start, en dan start de container opnieuw. Een mislukte lezing wordt na
    een uur opnieuw geprobeerd, zodat één hapering niet de hele looptijd telt.
    """
    import time
    if _machinetype_cache.get("waarde"):
        return _machinetype_cache["waarde"]
    if time.monotonic() - _machinetype_cache.get("mislukt_om", -1e18) < _MISLUKT_OPNIEUW_SEC:
        return ""
    try:
        import urllib.request
        req = urllib.request.Request(_METADATA_URL, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            # "projects/<nr>/zones/<zone>/machineTypes/e2-small"
            waarde = resp.read().decode("utf-8").strip().rsplit("/", 1)[-1]
        if waarde:
            _machinetype_cache["waarde"] = waarde
            return waarde
    except Exception as e:
        logger.debug(f"machinetype onleesbaar: {e}")
    _machinetype_cache["mislukt_om"] = time.monotonic()
    return ""


def infra_kosten_per_dag() -> float:
    """Infrastructuurkosten per dag in USD. Env var INFRA_COST_USD_DAILY gaat voor."""
    handmatig = os.getenv("INFRA_COST_USD_DAILY")
    if handmatig:
        try:
            waarde = float(handmatig)
            # Nul is geen geldige kostenbasis: een lege of foute instelling mag H1 niet
            # stil winstgevend maken.
            if math.isfinite(waarde) and waarde > 0:
                return waarde
        except ValueError:
            pass
        logger.warning(f"INFRA_COST_USD_DAILY={handmatig!r} ongeldig — genegeerd")
    mt = _machinetype()
    compute = _COMPUTE_USD_PER_DAG.get(mt)
    if compute is None:
        logger.warning("machinetype %s onbekend — reken de duurste (%s)", mt or "onleesbaar", _COMPUTE_ONBEKEND)
        compute = _COMPUTE_ONBEKEND
    return round(compute + _BIJKOSTEN_USD_PER_DAG, 3)

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
        infra       = infra_kosten_per_dag()
        # Beursfees horen NIET in total_cost: H1 rekent met de potjes-NAV, en daar zijn fees al
        # afgetrokken. Meetellen is dubbel tellen. `exchange_fees_usd` blijft ter informatie
        # (A1-audit r2 2026-09-17: fees stonden 30/30 dagen op 0 doordat `size` niet bestaat —
        # toevallig juist; wie dat naar `quantity` repareert, mag H1 niet raken).
        total_cost  = round(llm_cost + infra, 4)
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
            "infra_cost_usd_daily":  infra,
            "machine_type":          _machinetype() or None,
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
