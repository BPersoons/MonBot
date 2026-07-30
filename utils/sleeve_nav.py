"""
sleeve_nav.py — Masterplan Fase 0: sleeve-NAV boekhouding.

Elke euro krijgt een sleeve-label (config/sleeves.json). Eén keer per dag wordt
een NAV-snapshot per sleeve weggeschreven naar data/sleeve_nav.json
(volume-mounted → overleeft rebuilds) en een Telegram-digest verstuurd met
1d/7d/30d rendement, drawdown vs peak, venue-concentratie en limiet-checks.

Bron van de balansen is treasury_state.json (geschreven door TreasuryAgent,
elke 60 cycli + startup). Is die ouder dan STALE_HOURS, dan wordt de snapshot
uitgesteld tot een verse run — liever een gat in de reeks dan een verzonnen
getal.

F0-beperking (bewust): NAV-rendement is nog niet flow-adjusted — een storting
of onttrekking telt als "rendement" tot de meta-allocator (F5) kapitaalstromen
per sleeve gaat boeken. Bij de huidige lage flow-frequentie is dat acceptabel;
grote treasury-verplaatsingen zijn zichtbaar in de venue-regel van het rapport.
"""

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("SleeveNAV")

CONFIG_FILE = "config/sleeves.json"
STATE_FILE = "data/sleeve_nav.json"
TREASURY_STATE_FILE = "treasury_state.json"
THEMATIC_EXPOSURE_FILE = "thematic_exposure_positions.json"
STALE_HOURS = 3.0          # treasury_state ouder dan dit → snapshot uitstellen
MAX_HISTORY = 400          # ~13 maanden dagelijkse entries
FALLBACK_EURUSD = 1.08     # alleen gebruikt als er nog nooit een rate gefetcht is

_DEFAULT_CONFIG = {
    "sleeves": ["tradfi", "yield_core", "basis", "house", "swarm", "lab"],
    "source_map": {"hl_snapshot.balance": "swarm"},
    "default_yield_sleeve": "yield_core",
    "venue_map": {},
    "limits": {"max_venue_pct": {}, "max_sleeve_drawdown_pct": {}},
}


class SleeveNAV:
    def __init__(self):
        self.config = dict(_DEFAULT_CONFIG)
        try:
            with open(CONFIG_FILE) as f:
                self.config.update(json.load(f))
        except Exception as e:
            logger.warning(f"sleeves.json niet leesbaar ({e}) — defaults actief")

    # ── state ────────────────────────────────────────────────────────────
    def _load_state(self) -> dict:
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("history"), list):
                    return data
        except Exception:
            pass
        return {"history": []}

    def _save_state(self, state: dict) -> None:
        state["history"] = state["history"][-MAX_HISTORY:]
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"sleeve_nav.json schrijven mislukt: {e}")

    # ── inputs ───────────────────────────────────────────────────────────
    @staticmethod
    def _dig(obj: dict, dotted: str):
        cur = obj
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def compute_sleeves(self):
        """Lees treasury_state en verdeel kapitaal over sleeves + venues.
        Returns (sleeves, venues) of None wanneer de bron ontbreekt/staal is."""
        try:
            st = os.stat(TREASURY_STATE_FILE)
            import time as _t
            if (_t.time() - st.st_mtime) > STALE_HOURS * 3600:
                logger.warning("treasury_state.json is staal — snapshot uitgesteld")
                return None
            with open(TREASURY_STATE_FILE) as f:
                ts = json.load(f)
        except Exception as e:
            logger.warning(f"treasury_state.json niet leesbaar: {e}")
            return None

        sleeves = {s: 0.0 for s in self.config["sleeves"]}
        venues: dict = {}
        src_map = self.config.get("source_map", {})
        venue_map = self.config.get("venue_map", {})

        def add(dotted: str, sleeve: str):
            val = self._dig(ts, dotted)
            try:
                usd = float(val)
            except (TypeError, ValueError):
                return
            if usd <= 0:
                return
            sleeves[sleeve] = sleeves.get(sleeve, 0.0) + usd
            venue = venue_map.get(dotted, dotted.split(".")[0])
            venues[venue] = venues.get(venue, 0.0) + usd

        for dotted, sleeve in src_map.items():
            add(dotted, sleeve)

        # Onbekende (nieuwe) yield-protocollen → default sleeve, nooit onzichtbaar
        for pid, bal in (ts.get("yield_balances") or {}).items():
            dotted = f"yield_balances.{pid}"
            if dotted not in src_map:
                add(dotted, self.config.get("default_yield_sleeve", "yield_core"))

        # Thematic Exposure sleeve (EXP-008): SLEEVE-labeling for its capital.
        # Since 2026-07-18 the sleeve can run on its OWN Hyperliquid wallet
        # (HL_THEMATIC_WALLET_ADDRESS, see main.py's split). In that case this
        # capital was NEVER counted via hl_snapshot.balance -> "hyperliquid"
        # (that source only reflects the main swarm wallet) — it gets its own
        # sleeve AND its own venue, no correction needed. While that secret is
        # still unset (pre-split, or before Bart funds/wires the new wallet),
        # the sleeve shares the swarm's HL account, so the original
        # double-count correction still applies: relabel the capital from
        # 'swarm' to 'thematic_exposure' without adding a new venue line
        # (it's already counted once under "hyperliquid").
        thematic_exposure_usd = self._thematic_exposure_value()
        if thematic_exposure_usd > 0:
            sleeves["thematic_exposure"] = sleeves.get("thematic_exposure", 0.0) + thematic_exposure_usd
            if self._thematic_wallet_is_segregated():
                venues["hyperliquid_thematic"] = venues.get("hyperliquid_thematic", 0.0) + thematic_exposure_usd
            else:
                sleeves["swarm"] = max(0.0, sleeves.get("swarm", 0.0) - thematic_exposure_usd)

        return sleeves, venues

    @staticmethod
    def _thematic_wallet_is_segregated() -> bool:
        """True once the Thematic Exposure Sleeve has its own HL wallet
        (HL_THEMATIC_WALLET_ADDRESS secret populated — see main.py's split,
        2026-07-18) instead of sharing the main swarm account."""
        try:
            from utils.gcp_secrets import get_secret
            return bool(get_secret("HL_THEMATIC_WALLET_ADDRESS"))
        except Exception:
            return False

    @staticmethod
    def _thematic_exposure_value() -> float:
        """NAV van de thematic_exposure-sleeve: vrij budget (cash) + huidige
        marktwaarde van open posities, uit thematic_exposure_positions.json (door
        ThematicExposureLab bijgehouden). Bestand ontbreekt/leeg -> 0.0 (sleeve
        bestaat dan simpelweg nog niet, geen fout)."""
        try:
            with open(THEMATIC_EXPOSURE_FILE) as f:
                data = json.load(f)
        except Exception:
            return 0.0
        try:
            cash = float(data.get("cash_usd", 0.0) or 0.0)
            positions_value = sum(
                float(p.get("current_value_usd", 0.0) or 0.0)
                for p in (data.get("positions") or {}).values()
                if p.get("status") == "OPEN"
            )
            return max(0.0, cash + positions_value)
        except Exception as e:
            logger.warning(f"thematic_exposure_positions.json niet leesbaar: {e}")
            return 0.0

    _FX_SOURCES = (
        # (url, pad naar USD→EUR rate in de JSON)
        ("https://open.er-api.com/v6/latest/USD", ("rates", "EUR")),
        ("https://api.frankfurter.app/latest?from=USD&to=EUR", ("rates", "EUR")),
    )

    def _eur_rate(self, state: dict) -> float:
        prev = None
        if state["history"]:
            prev = state["history"][-1].get("eurusd")
        for url, path in self._FX_SOURCES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "agent-trader/1.0"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    data = json.load(r)
                for key in path:
                    data = data[key]
                usd_to_eur = float(data)
                if 0.5 < usd_to_eur < 1.5:  # sanity
                    return round(1.0 / usd_to_eur, 4)  # opslaan als EURUSD
            except Exception as e:
                logger.warning(f"FX-bron {url.split('/')[2]} mislukt: {e}")
        logger.warning("Alle FX-bronnen mislukt — vorige/fallback rate")
        return prev or FALLBACK_EURUSD

    # ── snapshot ─────────────────────────────────────────────────────────
    def snapshot_if_new_day(self):
        """Neem max één snapshot per UTC-dag. Returns rapport-tekst of None."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        state = self._load_state()
        if state["history"] and state["history"][-1].get("date") == today:
            return None
        computed = self.compute_sleeves()
        if computed is None:
            return None
        sleeves, venues = computed
        total = round(sum(sleeves.values()), 2)
        if total <= 0:
            logger.warning("Totaal-NAV 0 — snapshot overgeslagen")
            return None
        eurusd = self._eur_rate(state)
        entry = {
            "date": today,
            "ts": datetime.now(timezone.utc).isoformat(),
            "sleeves": {k: round(v, 2) for k, v in sleeves.items()},
            "venues": {k: round(v, 2) for k, v in venues.items()},
            "total_usd": total,
            "eurusd": eurusd,
            "total_eur": round(total / eurusd, 2),
        }
        state["history"].append(entry)
        self._save_state(state)
        logger.info(f"[SleeveNAV] Snapshot {today}: ${total:,.2f} over {sum(1 for v in sleeves.values() if v > 0)} sleeves")
        return self._build_report(state["history"])

    # ── rapport ──────────────────────────────────────────────────────────
    @staticmethod
    def _ret(hist, sleeve, days):
        """% verandering van sleeve-NAV over `days` snapshots terug (None = n/a)."""
        if len(hist) <= days:
            return None
        old = hist[-1 - days]["sleeves"].get(sleeve, 0.0)
        new = hist[-1]["sleeves"].get(sleeve, 0.0)
        if old <= 0:
            return None
        return (new - old) / old * 100.0

    def _build_report(self, hist) -> str:
        cur = hist[-1]
        lines = [f"📒 *Sleeve NAV* — {cur['date']}"]
        for sleeve, nav in sorted(cur["sleeves"].items(), key=lambda kv: -kv[1]):
            if nav <= 0:
                continue
            parts = [f"${nav:,.0f}"]
            for label, days in (("1d", 1), ("7d", 7), ("30d", 30)):
                r = self._ret(hist, sleeve, days)
                if r is not None:
                    parts.append(f"{label} {r:+.2f}%")
            # drawdown vs peak binnen de historie
            peak = max(h["sleeves"].get(sleeve, 0.0) for h in hist)
            dd = (peak - nav) / peak * 100.0 if peak > 0 else 0.0
            if dd > 0.5:
                parts.append(f"DD {dd:.1f}%")
            lines.append(f"  • `{sleeve}`: " + " | ".join(parts))
        lines.append(
            f"*Totaal*: ${cur['total_usd']:,.2f} / €{cur['total_eur']:,.2f} (EURUSD {cur['eurusd']})"
        )
        # venue-concentratie + limieten
        warn = self.check_limits(hist)
        vparts = [
            f"{v} {nav / cur['total_usd'] * 100:.0f}%"
            for v, nav in sorted(cur["venues"].items(), key=lambda kv: -kv[1])
            if nav > 0
        ]
        if vparts:
            lines.append("Venues: " + ", ".join(vparts))
        if warn:
            lines.append("⚠️ *Limieten*: " + "; ".join(warn))
        return "\n".join(lines)

    def check_limits(self, hist) -> list:
        """Venue-concentratie en sleeve-drawdown tegen config-limieten."""
        warnings = []
        if not hist:
            return warnings
        cur = hist[-1]
        total = cur.get("total_usd") or 0.0
        if total <= 0:
            return warnings
        for venue, cap in (self.config["limits"].get("max_venue_pct") or {}).items():
            pct = cur["venues"].get(venue, 0.0) / total * 100.0
            if pct > cap:
                warnings.append(f"{venue} {pct:.0f}% > {cap:.0f}% cap")
        for sleeve, cap in (self.config["limits"].get("max_sleeve_drawdown_pct") or {}).items():
            peak = max(h["sleeves"].get(sleeve, 0.0) for h in hist)
            nav = cur["sleeves"].get(sleeve, 0.0)
            if peak > 0 and nav > 0:
                dd = (peak - nav) / peak * 100.0
                if dd > cap:
                    warnings.append(f"{sleeve} DD {dd:.1f}% > {cap:.0f}%")
        return warnings

    # ── telegram ─────────────────────────────────────────────────────────
    def send_telegram(self, text: str) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            logger.info(f"SleeveNAV (geen Telegram):\n{text}")
            return
        # Eerst Markdown; bij een parse-fout (bv. underscore in een naam buiten
        # backticks → 400 can't parse entities) opnieuw als plain text zodat het
        # rapport ALTIJD aankomt.
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
                body = ""
                try:
                    body = e.read().decode()[:200]  # HTTPError heeft een body
                except Exception:
                    pass
                logger.warning(
                    f"SleeveNAV: Telegram send mislukt (mode={parse_mode}): {e} {body}"
                )
