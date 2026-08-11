"""Conviction Core — buy-and-hold BTC/ETH SPOT sleeve on HL (main wallet 0x92D4).

Part of the Conviction Barbell (docs/CONVICTION_BARBELL_PLAN.md). Holds BTC/ETH as
SPOT (UBTC/UETH — no funding drag, real Unit-backed tokens), DCA-deploys idle
earmarked USDC toward a target notional, and band-rebalances BTC vs ETH. Deliberately
separate from the active trading agents: it only ever touches spot UBTC/UETH and a
bounded USDC budget — never perps, never leverage.

SAFETY MODEL
------------
- `enabled=false`  => DRY-RUN: computes + logs the intended orders, places NOTHING.
- `target_usd`     => hard ceiling on total BTC+ETH notional; never deploys beyond it.
- `reserve_spot_usdc` => always left untouched so the trading wallet keeps its buffer.
- `max_deploy_per_run_usd` => DCA throttle: caps new capital deployed per run.
- cooldown per asset kills whipsaw (mirrors scripts/rebalance_calculator.py).

The planning logic (`plan()`) is pure — given holdings/prices/free-USDC it returns the
intended trades — so it is unit-testable without any exchange connection.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import os

logger = logging.getLogger("ConvictionCore")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG = os.path.join(_ROOT, "config", "conviction_core.json")
_STATE = os.path.join(_ROOT, "conviction_core_state.json")

# HL spot coin names for the Unit-bridged majors (spotClearinghouseState uses these).
_HL_COIN = {"BTC": "UBTC", "ETH": "UETH"}


def _round_amount(qty: float, prec: float) -> float:
    """Floor qty to the market's amount step (never round UP — avoids oversell /
    insufficient-balance). prec e.g. 1e-5 -> 5 decimals."""
    if prec and prec > 0:
        ndig = max(0, int(round(-math.log10(prec))))
        factor = 10 ** ndig
        return math.floor(qty * factor) / factor
    return qty


class ConvictionCore:
    def __init__(self, exchange_client=None):
        self.exchange_client = exchange_client

    # ---------- config / state ----------
    def _load_config(self) -> dict:
        try:
            with open(_CONFIG, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"ConvictionCore: kan config niet lezen ({e}) — sleeve uit.")
            return {"enabled": False, "target_usd": 0}

    def _load_state(self) -> dict:
        try:
            with open(_STATE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"last_action": {}, "history": []}

    def _save_state(self, state: dict) -> None:
        try:
            with open(_STATE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"ConvictionCore: kan state niet opslaan ({e}).")

    @staticmethod
    def _days_since(iso: str) -> float:
        try:
            return (_dt.date.today() - _dt.date.fromisoformat(iso)).days
        except Exception:
            return 1e9

    # ---------- pure planning ----------
    def plan(self, cfg: dict, values: dict, prices: dict, free_usdc: float,
             state: dict) -> list[dict]:
        """Return a list of intended trades: {asset, side, usd, qty, reason, cooldown}.

        values : {'BTC': usd_value_held, 'ETH': ...}
        prices : {'BTC': px, 'ETH': px}
        free_usdc : spot USDC available AFTER the reserve is subtracted.
        """
        split = cfg.get("split_pct", {"BTC": 80, "ETH": 20})
        bands = cfg.get("bands", {})
        drift_pp = float(bands.get("rebalance_drift_pp", 8))
        min_trade = float(bands.get("min_trade_usd", 11))
        cooldown_days = int(bands.get("cooldown_days", 7))
        target_usd = float(cfg.get("target_usd", 0) or 0)
        max_deploy = float(cfg.get("dca", {}).get("max_deploy_per_run_usd", 60))

        sleeve_now = sum(values.values())
        # DCA: how much NEW capital to deploy toward target this run
        under_target = max(0.0, target_usd - sleeve_now)
        deploy = min(max_deploy, max(0.0, free_usdc), under_target)
        pool = sleeve_now + deploy  # sleeve size we rebalance to this run

        last_action = state.get("last_action", {})
        trades: list[dict] = []
        for asset, tgt_pct in split.items():
            val = float(values.get(asset, 0.0))
            px = float(prices.get(asset, 0.0))
            if px <= 0:
                continue
            cur_pct = (val / sleeve_now * 100) if sleeve_now > 0 else 0.0
            tgt_usd = tgt_pct / 100.0 * pool

            # Absolute procentpunt-band (juist voor een 2-asset-sleeve; een
            # multiplicatieve band maakt de bovengrens van de 80%-leg onbereikbaar).
            if sleeve_now <= 0:
                trigger, reason = True, "eerste opbouw"
            elif deploy > 0:
                trigger, reason = True, "DCA-bijstorting"
            elif abs(cur_pct - tgt_pct) > drift_pp:
                trigger, reason = True, f"drift {cur_pct - tgt_pct:+.0f}pp"
            else:
                trigger, reason = False, "binnen band"
            if not trigger:
                continue

            trade_usd = tgt_usd - val  # + = koop, - = verkoop
            if abs(trade_usd) < min_trade:
                continue
            side = "buy" if trade_usd > 0 else "sell"
            cd_left = None
            last = last_action.get(asset)
            if last and self._days_since(last) < cooldown_days:
                cd_left = cooldown_days - self._days_since(last)
            trades.append({
                "asset": asset, "side": side, "usd": abs(trade_usd),
                "qty": abs(trade_usd) / px, "reason": reason, "cooldown": cd_left,
            })
        return trades

    # ---------- run ----------
    def run(self) -> dict:
        cfg = self._load_config()
        result = {"planned": [], "executed": [], "dry_run": not cfg.get("enabled", False)}

        target_usd = float(cfg.get("target_usd", 0) or 0)
        if target_usd <= 0:
            logger.info("ConvictionCore: target_usd=0 — nog niet gefund, niets te doen.")
            return result
        ex = self.exchange_client
        if ex is None:
            logger.warning("ConvictionCore: geen exchange_client — sleeve inactief.")
            return result

        # holdings + prijzen + vrij spot-USDC
        try:
            holdings = ex.get_spot_holdings()
            prices = {a: ex.get_spot_price(a) for a in cfg.get("split_pct", {})}
            values = {a: float(holdings.get(_HL_COIN[a], 0.0)) * prices.get(a, 0.0)
                      for a in cfg.get("split_pct", {})}
            usdc_total, usdc_hold = ex._fetch_spot_balance(
                getattr(ex, "vault_address", None) or ex.wallet_address)
            reserve = float(cfg.get("reserve_spot_usdc", 0) or 0)
            free_usdc = max(0.0, usdc_total - usdc_hold - reserve)
        except Exception as e:
            logger.error(f"ConvictionCore: kon staat niet lezen ({e}).")
            return result

        state = self._load_state()
        trades = self.plan(cfg, values, prices, free_usdc, state)
        result["planned"] = trades

        sleeve = sum(values.values())
        logger.info(f"ConvictionCore: sleeve=${sleeve:.2f}/target=${target_usd:.0f} "
                    f"(BTC=${values.get('BTC',0):.2f} ETH=${values.get('ETH',0):.2f}) "
                    f"vrij-USDC=${free_usdc:.2f} | {len(trades)} trade(s) gepland "
                    f"[{'DRY-RUN' if result['dry_run'] else 'LIVE'}]")

        today = _dt.date.today().isoformat()
        for t in trades:
            tag = f"{t['side'].upper()} ${t['usd']:.2f} {t['asset']} ({t['reason']})"
            if t["cooldown"] is not None:
                logger.info(f"  [COOLDOWN {t['cooldown']:.0f}d] {tag} — skip")
                continue
            if result["dry_run"]:
                logger.info(f"  [DRY-RUN] zou {tag}")
                continue
            # LIVE execute
            prec = ex.get_spot_meta(t["asset"])[1]
            qty = _round_amount(t["qty"], prec)
            if qty <= 0:
                continue
            order = ex.create_spot_order(t["asset"], t["side"], qty)
            if order:
                logger.info(f"  [LIVE] {tag} — order {order.get('id')}")
                state.setdefault("last_action", {})[t["asset"]] = today
                result["executed"].append({**t, "qty": qty, "order_id": order.get("id")})
            else:
                logger.warning(f"  [LIVE] {tag} — FAILED")

        if result["executed"]:
            state.setdefault("history", []).append(
                {"ts": today, "trades": result["executed"]})
            state["history"] = state["history"][-200:]
            self._save_state(state)
        return result
