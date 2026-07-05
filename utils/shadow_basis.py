"""
shadow_basis.py — virtual-outcome engine for the Fase 1 delta-neutral
basis trade (Masterplan docs/FASE1_FUNDING_HARVEST_DESIGN.md).

Same philosophy as utils/shadow_book.py: log what the strategy WOULD do,
every cycle, with zero capital at risk and zero order placement — only
public HL endpoints are touched. Runs regardless of the Fase-0 gate or
Fase-1 approval; this is pure measurement, not a live sleeve.

Simulates: open a virtual long-spot + short-perp basis position when
funding >= _MIN_RATE_8H, using virtual notional _VIRTUAL_NOTIONAL_USD.
Tracks funding accrued, spot/perp price drift (should ~cancel if the
hedge holds), a placeholder fee model (spot taker + perp taker, both
legs, both open and close — see _FEE_BPS_ASSUMPTION), and basis
(spot-perp spread) stability. Closes on rate-drop, max-hold, or a basis
blowout (hedge no longer tracking).

Files:
  shadow_basis_state.json  — currently open virtual position (or none)
  shadow_basis_log.json    — closed virtual trades (bounded)
  shadow_basis_report.json — aggregate, rewritten after each resolve
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("ShadowBasis")

_STATE_FILE  = "shadow_basis_state.json"
_LOG_FILE    = "shadow_basis_log.json"
_REPORT_FILE = "shadow_basis_report.json"

_ASSETS = {  # perp asset name -> HL spot pair API-name (verified 2026-07-05)
    "BTC": "@142",   # UBTC/USDC
    "ETH": "@151",   # UETH/USDC
}
_MIN_RATE_8H       = 0.01    # %/8h to open — mirrors FundingHarvestor
_CLOSE_RATE_8H     = 0.003   # %/8h to close
_MAX_HOLD_H        = 7 * 24  # basis trade can run longer than the naked harvest (hedged)
_VIRTUAL_NOTIONAL  = 2500.0  # matches the Fase 1 test-notional target
_MAX_BASIS_BPS     = 25.0    # spot-perp spread beyond this = hedge not tracking, close
_MAX_LOG           = 500

# PLACEHOLDER — HL's actual spot fee schedule is not yet confirmed (design
# doc open item #3). Conservative estimate: 3.5 bps taker per leg, 4 legs
# total (open spot, open perp, close spot, close perp) = 14 bps round-trip.
# Replace with real numbers before any live capital decision.
_FEE_BPS_ASSUMPTION = 3.5
_FEE_LEGS = 4


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _http_post(payload: dict) -> dict:
    req = urllib.request.Request(
        "https://api.hyperliquid.xyz/info",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


class ShadowBasis:
    def __init__(self):
        pass

    # ── public HL data ───────────────────────────────────────────────
    def _funding_rates(self) -> dict:
        data = _http_post({"type": "metaAndAssetCtxs"})
        assets = [a["name"] for a in data[0]["universe"]]
        return {
            name: float(ctx["funding"]) * 100
            for name, ctx in zip(assets, data[1])
            if ctx.get("funding") is not None
        }

    def _perp_mark_price(self, asset: str) -> float:
        data = _http_post({"type": "metaAndAssetCtxs"})
        assets = [a["name"] for a in data[0]["universe"]]
        for name, ctx in zip(assets, data[1]):
            if name == asset and ctx.get("markPx") is not None:
                return float(ctx["markPx"])
        return 0.0

    def _spot_mid_price(self, pair_name: str) -> float:
        book = _http_post({"type": "l2Book", "coin": pair_name})
        levels = book.get("levels", [[], []])
        bid = float(levels[0][0]["px"]) if levels[0] else 0.0
        ask = float(levels[1][0]["px"]) if levels[1] else 0.0
        if bid <= 0 or ask <= 0:
            return 0.0
        return (bid + ask) / 2.0

    # ── state ────────────────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {"status": "IDLE"}

    def _save_state(self, state: dict) -> None:
        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_basis_state.json schrijven mislukt: {e}")

    def _append_log(self, record: dict) -> None:
        try:
            with open(_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append(record)
        log = log[-_MAX_LOG:]
        try:
            with open(_LOG_FILE, "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_basis_log.json schrijven mislukt: {e}")

    # ── core cycle ───────────────────────────────────────────────────
    def run_cycle(self) -> None:
        """Called once per SleeveNAV-style offset cycle. Fail-open."""
        state = self._load_state()
        if state.get("status") == "ACTIVE":
            self._monitor(state)
        else:
            self._maybe_open()

    def _maybe_open(self) -> None:
        try:
            rates = self._funding_rates()
        except Exception as e:
            logger.debug(f"ShadowBasis: funding fetch mislukt: {e}")
            return
        candidates = [
            (a, rates[a]) for a in _ASSETS if rates.get(a, 0.0) >= _MIN_RATE_8H
        ]
        if not candidates:
            return
        asset, rate = max(candidates, key=lambda x: x[1])
        try:
            perp_px = self._perp_mark_price(asset)
            spot_px = self._spot_mid_price(_ASSETS[asset])
        except Exception as e:
            logger.debug(f"ShadowBasis: price fetch mislukt: {e}")
            return
        if perp_px <= 0 or spot_px <= 0:
            return
        basis_bps = abs(perp_px - spot_px) / spot_px * 10_000
        entry = {
            "status": "ACTIVE",
            "asset": asset,
            "opened_at": _now_iso(),
            "opened_ts": time.time(),
            "rate_at_open": rate,
            "perp_entry_px": perp_px,
            "spot_entry_px": spot_px,
            "basis_entry_bps": round(basis_bps, 2),
            "virtual_notional": _VIRTUAL_NOTIONAL,
            "funding_accrued_usd": 0.0,
            "last_check": _now_iso(),
        }
        self._save_state(entry)
        logger.info(
            f"[ShadowBasis] Virtueel geopend: {asset} @ rate {rate:.4f}%/8h "
            f"(perp {perp_px:.2f} / spot {spot_px:.2f}, basis {basis_bps:.1f}bps)"
        )

    def _monitor(self, state: dict) -> None:
        asset = state["asset"]
        try:
            rates = self._funding_rates()
            perp_px = self._perp_mark_price(asset)
            spot_px = self._spot_mid_price(_ASSETS[asset])
        except Exception as e:
            logger.debug(f"ShadowBasis: monitor fetch mislukt: {e}")
            return
        if perp_px <= 0 or spot_px <= 0:
            return

        current_rate = rates.get(asset, 0.0)
        now = time.time()
        hours_held = (now - state["opened_ts"]) / 3600.0

        # Funding accrues in 8h windows; approximate continuously per hour held
        # since the last check (funding rate is roughly stable within a cycle).
        last_check_ts = state.get("_last_check_ts", state["opened_ts"])
        hours_since_check = max(0.0, (now - last_check_ts) / 3600.0)
        funding_this_period = _VIRTUAL_NOTIONAL * (current_rate / 100.0) * (hours_since_check / 8.0)
        state["funding_accrued_usd"] = state.get("funding_accrued_usd", 0.0) + funding_this_period
        state["_last_check_ts"] = now
        state["last_rate"] = current_rate
        state["last_check"] = _now_iso()

        basis_bps = abs(perp_px - spot_px) / spot_px * 10_000

        close_reason = None
        if hours_held >= _MAX_HOLD_H:
            close_reason = f"max_hold_{_MAX_HOLD_H}h"
        elif current_rate < _CLOSE_RATE_8H:
            close_reason = f"rate_below_threshold ({current_rate:.4f}%/8h)"
        elif basis_bps > _MAX_BASIS_BPS:
            close_reason = f"basis_blowout ({basis_bps:.1f}bps > {_MAX_BASIS_BPS}bps)"

        if close_reason is None:
            self._save_state(state)
            return

        self._close(state, perp_px, spot_px, basis_bps, close_reason, hours_held)

    def _close(self, state, perp_exit_px, spot_exit_px, basis_exit_bps, reason, hours_held):
        notional = state["virtual_notional"]
        perp_entry, spot_entry = state["perp_entry_px"], state["spot_entry_px"]

        # Short perp: profit when perp price falls. Long spot: profit when spot rises.
        # A tracking hedge means these two roughly cancel; the residual is the
        # basis DRIFT (entry basis vs exit basis), not the raw price move.
        perp_pnl_usd = notional * (perp_entry - perp_exit_px) / perp_entry
        spot_pnl_usd = notional * (spot_exit_px - spot_entry) / spot_entry
        price_pnl_usd = perp_pnl_usd + spot_pnl_usd

        fees_usd = notional * (_FEE_BPS_ASSUMPTION / 10_000) * _FEE_LEGS
        funding_usd = state.get("funding_accrued_usd", 0.0)
        net_pnl_usd = funding_usd + price_pnl_usd - fees_usd
        net_apy_pct = (net_pnl_usd / notional) * (8760.0 / max(hours_held, 0.1)) * 100.0

        record = {
            "asset": state["asset"],
            "opened_at": state["opened_at"],
            "closed_at": _now_iso(),
            "hours_held": round(hours_held, 2),
            "rate_at_open": state["rate_at_open"],
            "basis_entry_bps": state["basis_entry_bps"],
            "basis_exit_bps": round(basis_exit_bps, 2),
            "funding_accrued_usd": round(funding_usd, 4),
            "price_pnl_usd": round(price_pnl_usd, 4),
            "fees_usd_modeled": round(fees_usd, 4),
            "net_pnl_usd": round(net_pnl_usd, 4),
            "net_apy_pct_annualized": round(net_apy_pct, 2),
            "close_reason": reason,
        }
        self._append_log(record)
        self._save_state({"status": "IDLE"})
        logger.info(
            f"[ShadowBasis] Virtueel gesloten: {state['asset']} reden={reason} "
            f"funding=${funding_usd:.2f} price_pnl=${price_pnl_usd:.2f} "
            f"fees=${fees_usd:.2f} net=${net_pnl_usd:.2f} (~{net_apy_pct:.1f}% APY)"
        )
        self._send_telegram(
            f"🧪 *Shadow Basis (virtueel, geen echt kapitaal)*\n"
            f"{state['asset']} gesloten na {hours_held:.1f}h — {reason}\n"
            f"Funding: ${funding_usd:+.2f} | Prijs-hedge: ${price_pnl_usd:+.2f} | "
            f"Fees (model): -${fees_usd:.2f}\n"
            f"*Netto: ${net_pnl_usd:+.2f}* (~{net_apy_pct:+.0f}% APY geannualiseerd — "
            f"bij korte holds domineren fees dit getal, zie report voor cumulatief)"
        )

    def _send_telegram(self, text: str) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return
        for parse_mode in ("Markdown", None):
            payload = {"chat_id": chat_id, "text": text}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            try:
                params = urllib.parse.urlencode(payload).encode()
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    data=params, method="POST",
                )
                with urllib.request.urlopen(req, timeout=10):
                    return
            except Exception as e:
                logger.warning(f"ShadowBasis: Telegram send mislukt (mode={parse_mode}): {e}")

    # ── report ───────────────────────────────────────────────────────
    def build_report(self) -> dict:
        try:
            with open(_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        if not log:
            report = {"generated_at": _now_iso(), "n_closed": 0, "note": "nog geen gesloten virtuele trades"}
        else:
            n = len(log)
            total_funding = sum(r["funding_accrued_usd"] for r in log)
            total_fees = sum(r["fees_usd_modeled"] for r in log)
            total_price_pnl = sum(r["price_pnl_usd"] for r in log)
            total_net = sum(r["net_pnl_usd"] for r in log)
            avg_apy = sum(r["net_apy_pct_annualized"] for r in log) / n
            max_basis_seen = max(max(r["basis_entry_bps"], r["basis_exit_bps"]) for r in log)
            by_reason = {}
            for r in log:
                by_reason[r["close_reason"].split(" ")[0]] = by_reason.get(r["close_reason"].split(" ")[0], 0) + 1
            report = {
                "generated_at": _now_iso(),
                "n_closed": n,
                "total_funding_usd": round(total_funding, 2),
                "total_fees_usd_modeled": round(total_fees, 2),
                "total_price_pnl_usd": round(total_price_pnl, 2),
                "total_net_pnl_usd": round(total_net, 2),
                "avg_net_apy_pct_annualized": round(avg_apy, 2),
                "max_basis_bps_observed": round(max_basis_seen, 2),
                "close_reasons": by_reason,
                "fee_assumption_note": (
                    f"fees modeled at {_FEE_BPS_ASSUMPTION}bps x {_FEE_LEGS} legs — "
                    "PLACEHOLDER, confirm real HL spot fee schedule before live capital"
                ),
            }
        try:
            with open(_REPORT_FILE, "w") as f:
                json.dump(report, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_basis_report.json schrijven mislukt: {e}")
        return report
