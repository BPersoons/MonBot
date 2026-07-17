"""
shadow_xyz_lab.py — Masterplan Fase 3: XYZ-lab shadow-recorders (EXP-007).

Zero-capital, zero-order measurement of specific XYZ-synthetic-market
hypotheses (docs/MASTERPLAN.md sectie 3, Bron D). Same philosophy as
shadow_book.py / shadow_basis.py: log what we observe, resolve later,
before ever risking capital.

Sub-tracker 1: weekend-funding. XYZ-equity tickers have no real underlying
market open on weekends, so funding can drift without the usual
price-discovery pressure. We snapshot funding through the weekend and
compare each ticker's peak against its own weekday baseline (captured
Friday evening, before the underlying closes).

Sub-tracker 2: open-gap convergence. Right before the real underlying
opens, the XYZ synthetic has been trading all night with no fresh
price-discovery; does it converge toward the real opening print, and
how fast? We snapshot XYZ mark price pre-open and at two checkpoints
after, and compare against the real first 1-minute print (yfinance).
Checkpoint clock (14:30 UTC open) matches the existing codebase
convention (xyz_technical_analyst.py _market_is_open) — not DST-adjusted,
consistent with the rest of the pipeline rather than independently
"more correct" but inconsistent with it.

Sub-tracker 3: new-listing behavior. HL adds markets weekly; the first days
have the thinnest books and (per the masterplan hypothesis) the largest
inefficiencies. We diff the current universe (both dexes) against a
persisted known-tickers set to spot brand-new listings, then follow each
for 7 days (price range, drift, average daily volume) before resolving.

v1 scope: all three trackers measure the raw PHENOMENON (funding extremity /
price convergence / listing volatility), not yet a net-of-costs virtual
trade. That's a deliberate first step — confirm the phenomenon is real
before layering a PnL simulation on top (same order EXP-004/shadow_basis
followed: measure first, simulate second). Poort F3 ("na-kosten-positieve
edge") needs that PnL layer before it can be evaluated; track separately.

Files:
  shadow_xyz_funding_state.json   — in-progress weekend snapshots + weekday baseline
  shadow_xyz_funding_log.json     — resolved weekend-windows per ticker (bounded)
  shadow_xyz_funding_report.json  — aggregate, rewritten after each resolve
  shadow_xyz_gap_state.json       — in-progress open-gap checkpoints for today
  shadow_xyz_gap_log.json         — resolved open-gap events per ticker (bounded)
  shadow_xyz_gap_report.json      — aggregate, rewritten after each resolve
  shadow_xyz_listings_state.json  — known-tickers set + in-progress trackings
  shadow_xyz_listings_log.json    — resolved 7-day listing trackings (bounded)
  shadow_xyz_listings_report.json — aggregate, rewritten after each resolve
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("ShadowXyzLab")

_STATE_FILE  = "shadow_xyz_funding_state.json"
_LOG_FILE    = "shadow_xyz_funding_log.json"
_REPORT_FILE = "shadow_xyz_funding_report.json"

_GAP_STATE_FILE  = "shadow_xyz_gap_state.json"
_GAP_LOG_FILE    = "shadow_xyz_gap_log.json"
_GAP_REPORT_FILE = "shadow_xyz_gap_report.json"

_LISTINGS_STATE_FILE  = "shadow_xyz_listings_state.json"
_LISTINGS_LOG_FILE    = "shadow_xyz_listings_log.json"
_LISTINGS_REPORT_FILE = "shadow_xyz_listings_report.json"

_SNAPSHOT_MIN_GAP_H = 3.0   # min hours between snapshots within one weekend window
_MAX_LOG = 500

_LISTINGS_TRACK_DAYS = 7           # how long to follow a new listing
_LISTINGS_SNAPSHOT_MIN_GAP_H = 4.0  # min hours between tracking snapshots
_LISTINGS_SCAN_MIN_GAP_H = 12.0    # min hours between new-listing scans

# Commodity XYZ tickers (raw, no 'XYZ-' prefix) and the synthetic index —
# neither has a single real-market "opening print" to converge toward.
_COMMODITY_XYZ = {"CL", "BRENTOIL", "GOLD", "SILVER", "NATGAS", "COPPER", "PLATINUM", "PALLADIUM"}
_NON_EQUITY_XYZ = _COMMODITY_XYZ | {"XYZ100"}

# (hour, minute, label) UTC — pre-open, +5min, +60min. Matches the existing
# codebase's hardcoded 14:30 UTC equity-open convention.
_GAP_CHECKPOINTS = [(14, 25, "pre_open"), (14, 35, "open_5m"), (15, 30, "open_60m")]
_GAP_CHECKPOINT_TOLERANCE_MIN = 4


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


class ShadowXyzLab:
    def __init__(self):
        pass

    # ── public HL data ───────────────────────────────────────────────
    def _xyz_funding_snapshot(self) -> dict:
        """Returns {ticker: {'funding': pct_8h, 'mark_px': float}} for all XYZ- perps.

        XYZ-synthetics live on their own Hyperliquid perp-dex ("xyz"), not the
        default metaAndAssetCtxs call — that only covers the main dex (BTC/ETH/
        alts). Raw asset names come back as 'xyz:TICKER'; normalized here to
        this codebase's 'XYZ-TICKER' convention (core/xyz_tokens.py, detect_asset_class).
        """
        data = _http_post({"type": "metaAndAssetCtxs", "dex": "xyz"})
        assets = [a["name"] for a in data[0]["universe"]]
        out = {}
        for name, ctx in zip(assets, data[1]):
            if not name.startswith("xyz:"):
                continue
            if ctx.get("funding") is None:
                continue
            display = "XYZ-" + name.split(":", 1)[1]
            out[display] = {
                "funding": float(ctx["funding"]) * 100,  # %/8h
                "mark_px": float(ctx.get("markPx") or 0.0),
                "day_volume_usd": float(ctx.get("dayNtlVlm") or 0.0),
            }
        return out

    def _main_dex_snapshot(self) -> dict:
        """Returns {ticker: {'mark_px': float, 'day_volume_usd': float}} for
        the default HL perp-dex (BTC/ETH/alts — no 'dex' param)."""
        data = _http_post({"type": "metaAndAssetCtxs"})
        assets = [a["name"] for a in data[0]["universe"]]
        out = {}
        for name, ctx in zip(assets, data[1]):
            px = float(ctx.get("markPx") or 0.0)
            if px <= 0:
                continue
            out[name] = {
                "mark_px": px,
                "day_volume_usd": float(ctx.get("dayNtlVlm") or 0.0),
            }
        return out

    # ── state ────────────────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            with open(_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        try:
            with open(_STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_funding_state.json schrijven mislukt: {e}")

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
            logger.error(f"shadow_xyz_funding_log.json schrijven mislukt: {e}")

    # ── weekend window helpers ──────────────────────────────────────
    @staticmethod
    def _weekend_id(now: datetime):
        """Returns 'YYYY-Www' if `now` falls in the weekend measurement window
        (Sat 00:00 UTC through Mon 15:00 UTC — closed-market period plus the
        US reopen), else None."""
        wd = now.weekday()  # Mon=0 .. Sun=6
        if wd in (5, 6):  # Sat, Sun
            iso_year, iso_week, _ = now.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        if wd == 0 and now.hour < 15:  # Monday before ~US open
            prev = now - timedelta(days=2)
            iso_year, iso_week, _ = prev.isocalendar()
            return f"{iso_year}-W{iso_week:02d}"
        return None

    # ── core cycle ───────────────────────────────────────────────────
    def run_cycle(self) -> None:
        """Called periodically (fail-open). Dispatches to all sub-trackers;
        each is a cheap no-op outside its own relevant time window."""
        now = datetime.now(timezone.utc)
        self._run_weekend_funding_cycle(now)
        self._run_open_gap_cycle(now)
        self._run_listing_scan_cycle(now)

    def _run_weekend_funding_cycle(self, now: datetime) -> None:
        """Captures a weekday funding baseline Friday evening, snapshots
        through the weekend window, and resolves once the window closes."""
        state = self._load_state()
        wd = now.weekday()

        if wd == 4 and now.hour >= 20:  # Friday evening — refresh baseline
            self._capture_baseline(state)
            return

        wid = self._weekend_id(now)
        if wid is None:
            # Not in a weekend window — if one just closed, resolve it.
            if state.get("weekend_id") and state.get("snapshots"):
                self._resolve(state)
            return

        if state.get("weekend_id") != wid:
            if not state.get("baseline"):
                logger.debug("ShadowXyzLab: geen weekday-baseline beschikbaar, sla weekend over")
                return
            state = {"weekend_id": wid, "baseline": state.get("baseline"), "snapshots": []}

        last_ts = state["snapshots"][-1]["ts"] if state["snapshots"] else 0
        if time.time() - last_ts < _SNAPSHOT_MIN_GAP_H * 3600:
            self._save_state(state)
            return

        try:
            snap = self._xyz_funding_snapshot()
        except Exception as e:
            logger.debug(f"ShadowXyzLab: funding snapshot mislukt: {e}")
            return
        if not snap:
            return
        state["snapshots"].append({"ts": time.time(), "iso": _now_iso(), "data": snap})
        self._save_state(state)
        logger.info(f"[ShadowXyzLab] Weekend-funding snapshot {wid}: {len(snap)} XYZ-tickers")

    def _capture_baseline(self, state: dict) -> None:
        try:
            snap = self._xyz_funding_snapshot()
        except Exception as e:
            logger.debug(f"ShadowXyzLab: baseline snapshot mislukt: {e}")
            return
        if not snap:
            return
        state["baseline"] = {"ts": time.time(), "iso": _now_iso(), "data": snap}
        state.setdefault("weekend_id", None)
        state.setdefault("snapshots", [])
        self._save_state(state)
        logger.info(f"[ShadowXyzLab] Weekday-baseline vastgelegd: {len(snap)} XYZ-tickers")

    def _resolve(self, state: dict) -> None:
        baseline = (state.get("baseline") or {}).get("data", {})
        snapshots = state.get("snapshots", [])
        if not snapshots or not baseline:
            self._save_state({"baseline": state.get("baseline")})
            return

        n_logged = 0
        for ticker, base in baseline.items():
            fundings = [s["data"][ticker]["funding"] for s in snapshots if ticker in s["data"]]
            if not fundings:
                continue
            max_abs = max(abs(f) for f in fundings)
            avg = sum(fundings) / len(fundings)
            record = {
                "ticker": ticker,
                "weekend_id": state["weekend_id"],
                "resolved_at": _now_iso(),
                "n_snapshots": len(fundings),
                "baseline_funding_pct_8h": round(base["funding"], 4),
                "weekend_avg_funding_pct_8h": round(avg, 4),
                "weekend_max_abs_funding_pct_8h": round(max_abs, 4),
                "extremity_ratio": round(max_abs / max(abs(base["funding"]), 0.001), 2),
            }
            self._append_log(record)
            n_logged += 1

        logger.info(f"[ShadowXyzLab] Weekend {state['weekend_id']} resolved — {n_logged} tickers gelogd")
        if n_logged:
            self._send_telegram(
                f"🧪 *Shadow XYZ-lab (Fase 3, virtueel — geen echt kapitaal)*\n"
                f"Weekend {state['weekend_id']} afgesloten — {n_logged} XYZ-tickers gelogd.\n"
                f"Zie shadow_xyz_funding_report.json voor de extremiteits-analyse."
            )
        self.build_report()
        self._save_state({"baseline": state.get("baseline")})

    # ── open-gap convergence ────────────────────────────────────────
    def _load_gap_state(self) -> dict:
        try:
            with open(_GAP_STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_gap_state(self, state: dict) -> None:
        try:
            with open(_GAP_STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_gap_state.json schrijven mislukt: {e}")

    def _append_gap_log(self, record: dict) -> None:
        try:
            with open(_GAP_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append(record)
        log = log[-_MAX_LOG:]
        try:
            with open(_GAP_LOG_FILE, "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_gap_log.json schrijven mislukt: {e}")

    def _run_open_gap_cycle(self, now: datetime) -> None:
        """Snapshots XYZ-equity mark price pre-open and at two checkpoints
        after, fetches the real opening print once (right after open), and
        resolves the day once the last checkpoint lands. No-op on weekends
        and outside the checkpoint windows — cheap to call every cycle."""
        if now.weekday() >= 5:
            return

        today = now.strftime("%Y-%m-%d")
        state = self._load_gap_state()
        if state.get("date") != today:
            state = {"date": today, "checkpoints": {}}

        minutes_now = now.hour * 60 + now.minute
        for hh, mm, label in _GAP_CHECKPOINTS:
            if label in state["checkpoints"]:
                continue
            if abs(minutes_now - (hh * 60 + mm)) > _GAP_CHECKPOINT_TOLERANCE_MIN:
                continue
            self._capture_gap_checkpoint(state, label)
            self._save_gap_state(state)
            break  # at most one checkpoint per call

        last_label = _GAP_CHECKPOINTS[-1][2]
        if last_label in state["checkpoints"] and not state.get("resolved"):
            self._resolve_gap(state)

    def _capture_gap_checkpoint(self, state: dict, label: str) -> None:
        try:
            snap = self._xyz_funding_snapshot()
        except Exception as e:
            logger.debug(f"ShadowXyzLab: gap-checkpoint '{label}' snapshot mislukt: {e}")
            return
        equities = {
            t: v["mark_px"] for t, v in snap.items()
            if t.split("-", 1)[1] not in _NON_EQUITY_XYZ and v["mark_px"] > 0
        }
        if not equities:
            return
        state["checkpoints"][label] = {"ts": time.time(), "iso": _now_iso(), "prices": equities}
        logger.info(f"[ShadowXyzLab] Open-gap checkpoint '{label}': {len(equities)} XYZ-equities")

        if label == "open_5m":
            self._capture_real_opens(state, list(equities.keys()))

    def _capture_real_opens(self, state: dict, xyz_tickers: list) -> None:
        """Fetches today's real first 1-minute print per underlying via a
        single batched yfinance call — one request for ~90 tickers instead
        of ~90 sequential ones."""
        real_symbols = [t.split("-", 1)[1] for t in xyz_tickers]
        try:
            import yfinance as yf
            data = yf.download(
                tickers=" ".join(real_symbols), period="1d", interval="1m",
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            logger.warning(f"ShadowXyzLab: yfinance open-fetch mislukt: {e}")
            return
        opens: dict[str, float] = {}
        for sym in real_symbols:
            try:
                col = data[sym] if len(real_symbols) > 1 else data
                first_valid = col["Open"].dropna()
                if not first_valid.empty:
                    opens["XYZ-" + sym] = float(first_valid.iloc[0])
            except Exception:
                continue
        state["real_opens"] = opens
        logger.info(f"[ShadowXyzLab] Real opens vastgelegd: {len(opens)}/{len(real_symbols)} tickers")

    def _resolve_gap(self, state: dict) -> None:
        real_opens = state.get("real_opens") or {}
        checkpoints = state.get("checkpoints") or {}
        pre = (checkpoints.get("pre_open") or {}).get("prices", {})
        state["resolved"] = True
        if not real_opens or not pre:
            self._save_gap_state(state)
            return

        n_logged = 0
        for ticker, real_open in real_opens.items():
            if real_open <= 0 or ticker not in pre:
                continue
            gap_at_open_bps = (pre[ticker] - real_open) / real_open * 10_000
            checkpoint_gaps = {}
            for label in ("open_5m", "open_60m"):
                px = (checkpoints.get(label) or {}).get("prices", {}).get(ticker)
                if px:
                    checkpoint_gaps[label] = round((px - real_open) / real_open * 10_000, 1)
            record = {
                "ticker": ticker,
                "date": state["date"],
                "resolved_at": _now_iso(),
                "xyz_pre_open_px": pre[ticker],
                "real_open_px": real_open,
                "gap_at_open_bps": round(gap_at_open_bps, 1),
                "gap_bps_by_checkpoint": checkpoint_gaps,
                "converged": bool(
                    checkpoint_gaps.get("open_60m") is not None
                    and abs(checkpoint_gaps["open_60m"]) < abs(gap_at_open_bps) * 0.5
                ),
            }
            self._append_gap_log(record)
            n_logged += 1

        self._save_gap_state(state)
        logger.info(f"[ShadowXyzLab] Open-gap {state['date']} resolved — {n_logged} tickers gelogd")
        report = self.build_gap_report()
        if n_logged:
            self._send_telegram(
                f"🧪 *Shadow XYZ-lab — open-gap (Fase 3, virtueel)*\n"
                f"{state['date']} afgesloten — {n_logged} tickers.\n"
                f"Gem. |gap| bij open: {report.get('avg_abs_gap_at_open_bps', 0):.0f}bps | "
                f"convergentie na 60m: {report.get('convergence_rate_pct', 0):.0f}%"
            )

    def build_gap_report(self) -> dict:
        try:
            with open(_GAP_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        if not log:
            report = {"generated_at": _now_iso(), "n_events": 0, "note": "nog geen afgesloten open-gap-events"}
        else:
            n = len(log)
            avg_gap_open = sum(abs(r["gap_at_open_bps"]) for r in log) / n
            n_converged = sum(1 for r in log if r.get("converged"))
            report = {
                "generated_at": _now_iso(),
                "n_events": n,
                "avg_abs_gap_at_open_bps": round(avg_gap_open, 1),
                "convergence_rate_pct": round(n_converged / n * 100, 1),
                "n_tickers_observed": len({r["ticker"] for r in log}),
                "poort_f3_n_gehaald": n >= 30,
            }
        try:
            with open(_GAP_REPORT_FILE, "w") as f:
                json.dump(report, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_gap_report.json schrijven mislukt: {e}")
        return report

    # ── new-listing detector ────────────────────────────────────────
    def _load_listings_state(self) -> dict:
        try:
            with open(_LISTINGS_STATE_FILE) as f:
                state = json.load(f)
        except Exception:
            state = {}
        state.setdefault("known", {"main": [], "xyz": []})
        state.setdefault("tracking", {})
        state.setdefault("last_scan_ts", 0)
        return state

    def _save_listings_state(self, state: dict) -> None:
        try:
            with open(_LISTINGS_STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_listings_state.json schrijven mislukt: {e}")

    def _append_listings_log(self, record: dict) -> None:
        try:
            with open(_LISTINGS_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append(record)
        log = log[-_MAX_LOG:]
        try:
            with open(_LISTINGS_LOG_FILE, "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_listings_log.json schrijven mislukt: {e}")

    def _run_listing_scan_cycle(self, now: datetime) -> None:
        """Diffs the current HL universe (both dexes) against a persisted
        known-tickers set to spot brand-new listings, tracks each for
        _LISTINGS_TRACK_DAYS, then resolves. Cheap no-op most cycles."""
        state = self._load_listings_state()

        if time.time() - state.get("last_scan_ts", 0) >= _LISTINGS_SCAN_MIN_GAP_H * 3600:
            self._scan_for_new_listings(state)
            state["last_scan_ts"] = time.time()

        self._update_listing_tracking(state)
        self._save_listings_state(state)

    def _scan_for_new_listings(self, state: dict) -> None:
        try:
            main_snap = self._main_dex_snapshot()
        except Exception as e:
            logger.debug(f"ShadowXyzLab: listings main-dex scan mislukt: {e}")
            main_snap = {}
        try:
            xyz_snap = self._xyz_funding_snapshot()
        except Exception as e:
            logger.debug(f"ShadowXyzLab: listings xyz-dex scan mislukt: {e}")
            xyz_snap = {}
        if not main_snap and not xyz_snap:
            return

        known_main = set(state["known"]["main"])
        known_xyz = set(state["known"]["xyz"])
        # First-ever scan: seed the known set without treating the whole
        # existing universe (~330 tickers) as "new listings".
        first_scan = not known_main and not known_xyz

        for name, data in main_snap.items():
            if name not in known_main:
                if not first_scan:
                    self._start_tracking(state, name, "main", data["mark_px"])
                known_main.add(name)
        for name, data in xyz_snap.items():
            if name not in known_xyz:
                if not first_scan:
                    self._start_tracking(state, name, "xyz", data["mark_px"])
                known_xyz.add(name)

        state["known"]["main"] = sorted(known_main)
        state["known"]["xyz"] = sorted(known_xyz)
        if first_scan:
            logger.info(
                f"[ShadowXyzLab] Listing-detector eerste scan: {len(known_main)} main + "
                f"{len(known_xyz)} xyz tickers als baseline vastgelegd"
            )

    def _start_tracking(self, state: dict, ticker: str, dex: str, px: float) -> None:
        state["tracking"][ticker] = {
            "dex": dex,
            "first_seen_iso": _now_iso(),
            "first_seen_ts": time.time(),
            "first_seen_px": px,
            "snapshots": [],
        }
        logger.info(f"[ShadowXyzLab] Nieuwe listing gedetecteerd: {ticker} ({dex}) @ {px}")
        self._send_telegram(
            f"🆕 *Shadow XYZ-lab — nieuwe listing gedetecteerd*\n"
            f"{ticker} ({dex}-dex) @ {px:g} — volg {_LISTINGS_TRACK_DAYS} dagen (virtueel)"
        )

    @staticmethod
    def _listing_snapshot_due(rec: dict) -> bool:
        last_ts = rec["snapshots"][-1]["ts"] if rec["snapshots"] else 0
        return time.time() - last_ts >= _LISTINGS_SNAPSHOT_MIN_GAP_H * 3600

    def _update_listing_tracking(self, state: dict) -> None:
        tracking = state["tracking"]
        if not tracking:
            return

        need_main = any(r["dex"] == "main" and self._listing_snapshot_due(r) for r in tracking.values())
        need_xyz = any(r["dex"] == "xyz" and self._listing_snapshot_due(r) for r in tracking.values())
        main_snap = self._main_dex_snapshot() if need_main else {}
        xyz_snap = self._xyz_funding_snapshot() if need_xyz else {}

        to_resolve = []
        for ticker, rec in tracking.items():
            age_h = (time.time() - rec["first_seen_ts"]) / 3600
            if age_h >= _LISTINGS_TRACK_DAYS * 24:
                to_resolve.append(ticker)
                continue
            if not self._listing_snapshot_due(rec):
                continue
            snap = main_snap if rec["dex"] == "main" else xyz_snap
            data = snap.get(ticker)
            if not data:
                continue
            rec["snapshots"].append({
                "ts": time.time(), "iso": _now_iso(),
                "mark_px": data["mark_px"],
                "day_volume_usd": data.get("day_volume_usd", 0.0),
            })

        for ticker in to_resolve:
            self._resolve_listing(state, ticker)

    def _resolve_listing(self, state: dict, ticker: str) -> None:
        rec = state["tracking"].pop(ticker)
        snapshots = rec["snapshots"]
        if not snapshots:
            return

        first_px = rec["first_seen_px"]
        last_px = snapshots[-1]["mark_px"]
        prices = [first_px] + [s["mark_px"] for s in snapshots]
        max_px, min_px = max(prices), min(prices)
        range_pct = (max_px - min_px) / first_px * 100 if first_px else 0.0
        drift_pct = (last_px - first_px) / first_px * 100 if first_px else 0.0
        avg_volume = sum(s.get("day_volume_usd", 0.0) for s in snapshots) / len(snapshots)

        record = {
            "ticker": ticker,
            "dex": rec["dex"],
            "first_seen": rec["first_seen_iso"],
            "resolved_at": _now_iso(),
            "n_snapshots": len(snapshots),
            "first_seen_px": first_px,
            "final_px": last_px,
            "range_pct": round(range_pct, 2),
            "drift_pct_over_7d": round(drift_pct, 2),
            "avg_day_volume_usd": round(avg_volume, 2),
        }
        self._append_listings_log(record)
        logger.info(
            f"[ShadowXyzLab] Listing {ticker} resolved na {_LISTINGS_TRACK_DAYS}d — "
            f"range {range_pct:.1f}%, drift {drift_pct:+.1f}%"
        )
        report = self.build_listings_report()
        self._send_telegram(
            f"🧪 *Shadow XYZ-lab — listing afgerond (Fase 3, virtueel)*\n"
            f"{ticker} ({rec['dex']}) — {_LISTINGS_TRACK_DAYS}d gevolgd\n"
            f"Range {range_pct:.1f}% | drift {drift_pct:+.1f}% | gem. volume ${avg_volume:,.0f}/dag\n"
            f"Totaal gelogd: {report.get('n_events', 0)} (poort: n≥30)"
        )

    def build_listings_report(self) -> dict:
        try:
            with open(_LISTINGS_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        if not log:
            report = {"generated_at": _now_iso(), "n_events": 0, "note": "nog geen afgesloten listing-trackingen"}
        else:
            n = len(log)
            report = {
                "generated_at": _now_iso(),
                "n_events": n,
                "avg_range_pct": round(sum(r["range_pct"] for r in log) / n, 2),
                "avg_drift_pct": round(sum(r["drift_pct_over_7d"] for r in log) / n, 2),
                "poort_f3_n_gehaald": n >= 30,
            }
        try:
            with open(_LISTINGS_REPORT_FILE, "w") as f:
                json.dump(report, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_listings_report.json schrijven mislukt: {e}")
        return report

    # ── telegram ─────────────────────────────────────────────────────
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
                logger.warning(f"ShadowXyzLab: Telegram send mislukt (mode={parse_mode}): {e}")

    # ── daily heartbeat ──────────────────────────────────────────────
    def daily_status_text(self) -> str:
        """Compact status blurb for the daily sleeve-NAV digest — same
        pattern as ShadowBasis.daily_status_text(). Read-only, no live calls."""
        try:
            with open(_REPORT_FILE) as f:
                report = json.load(f)
        except Exception:
            report = {}
        try:
            with open(_GAP_REPORT_FILE) as f:
                gap_report = json.load(f)
        except Exception:
            gap_report = {}
        try:
            with open(_LISTINGS_REPORT_FILE) as f:
                listings_report = json.load(f)
        except Exception:
            listings_report = {}

        n = report.get("n_events", 0)
        n_gap = gap_report.get("n_events", 0)
        n_listings = listings_report.get("n_events", 0)
        lines = ["", "🧪 *Shadow XYZ-lab (Fase 3, virtueel)*"]
        if n > 0:
            lines.append(
                f"  Weekend-funding: {n} events | gem. extremiteit {report.get('avg_extremity_ratio', 0):.1f}x, "
                f"max {report.get('max_extremity_ratio', 0):.1f}x weekday-baseline (poort: n≥30)"
            )
        else:
            lines.append("  Weekend-funding: nog geen afgesloten events")
        if n_gap > 0:
            lines.append(
                f"  Open-gap: {n_gap} events | gem. |gap| {gap_report.get('avg_abs_gap_at_open_bps', 0):.0f}bps | "
                f"convergentie {gap_report.get('convergence_rate_pct', 0):.0f}% (poort: n≥30)"
            )
        else:
            lines.append("  Open-gap: nog geen afgesloten events")
        if n_listings > 0:
            lines.append(
                f"  Listings: {n_listings} events | gem. range {listings_report.get('avg_range_pct', 0):.1f}% | "
                f"gem. drift {listings_report.get('avg_drift_pct', 0):+.1f}% (poort: n≥30)"
            )
        else:
            lines.append("  Listings: nog geen afgesloten trackingen")
        return "\n".join(lines)

    # ── report ───────────────────────────────────────────────────────
    def build_report(self) -> dict:
        try:
            with open(_LOG_FILE) as f:
                log = json.load(f)
        except Exception:
            log = []
        if not log:
            report = {"generated_at": _now_iso(), "n_events": 0, "note": "nog geen afgesloten weekend-events"}
        else:
            n = len(log)
            avg_extremity = sum(r["extremity_ratio"] for r in log) / n
            max_extremity = max(r["extremity_ratio"] for r in log)
            by_ticker: dict[str, list] = {}
            for r in log:
                by_ticker.setdefault(r["ticker"], []).append(r["extremity_ratio"])
            report = {
                "generated_at": _now_iso(),
                "n_events": n,
                "avg_extremity_ratio": round(avg_extremity, 2),
                "max_extremity_ratio": round(max_extremity, 2),
                "n_tickers_observed": len(by_ticker),
                "poort_f3_n_gehaald": n >= 30,
                "note": "extremiteit t.o.v. weekday-baseline — nog GEEN net-of-costs virtuele trade (zie EXP-007)",
            }
        try:
            with open(_REPORT_FILE, "w") as f:
                json.dump(report, f, indent=1)
        except Exception as e:
            logger.error(f"shadow_xyz_funding_report.json schrijven mislukt: {e}")
        return report
