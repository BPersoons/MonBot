"""
thematic_dip_lab.py — EXP-008: Thematic Dip Sleeve.

Continu draaiende crash-scanner over het volledige XYZ-synthetics-universum op
Hyperliquid. Classificeert tickers in thema's (LLM-voorgesteld). Sinds
2026-07-16 (Bart's verzoek): "high confidence"-voorstellen worden automatisch
CONFIRMED, geen menselijke review nodig — alleen "low confidence"/mislukte
classificaties blijven in de review-wachtrij (config/thematic_dip_themes.json,
via Telegram-commando's of het /thematic-dip-dashboard). Scoort sectorbrede pullbacks
(vol-genormaliseerde drawdown vanaf 252d-high + crash-snelheid + thema-breedte),
en opent kleine, volledig gedekte (1x, isolated margin) T1-starterposities op
de hardst geraakte, meest liquide namen binnen een vast budget. T2-T4 (verdere
DCA-opbouw) worden alleen ECHT uitgevoerd als thematic_dip_state.json
t2_t4_enabled=true bevat — tot die tijd berekent en rapporteert de engine wel
wat T2-T4 zou doen (zichtbaar in daily_status_text()).

Doel is niet tech/AI-specifiek: elk thema dat de LLM classificeert en dat een
sectorbrede, bevestigde pullback laat zien kan een positie triggeren — het
huidige tech/AI-thema is de eerste, handmatig geverifieerde seed.

Deze module plaatst ECHTE orders — buiten de council/ProjectLead-pipeline om,
zelfde patroon als TreasuryAgent._open_harvest_position/_close_harvest_position
(agents/treasury_agent.py:1224-1358). Trades worden getagd met
"thematic_dip": True in trade_log.json zodat de auditor/weight-learning-loop
ze negeert (zelfde isolatie-patroon als "harvest": True).

Files:
  config/thematic_dip_themes.json — thema-registry + classificatie (bewerkbaar)
  thematic_dip_state.json         — scan-cache, prijs-historie-cache, funding-historie, t2_t4_enabled-vlag
  thematic_dip_positions.json     — cash/budget + open/gesloten posities (bron voor SleeveNAV)
  thematic_dip_report.json        — laatste scoring-snapshot, voor dashboard/digest
"""

import json
import logging
import math
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("ThematicDipLab")

THEMES_FILE = "config/thematic_dip_themes.json"
STATE_FILE = "thematic_dip_state.json"
POSITIONS_FILE = "thematic_dip_positions.json"
REPORT_FILE = "thematic_dip_report.json"

DEFAULT_BUDGET_USD = 1250.0
MAX_CONCURRENT_NAMES = 8
MIN_DAY_VOLUME_USD = 5_000_000.0
PRICE_HISTORY_TTL_H = 24.0
PRICE_HISTORY_PERIOD = "1y"
MAX_NEW_CLASSIFICATIONS_PER_CYCLE = 10  # LLM-calls zijn niet gratis

# Non-equity XYZ-instrumenten (FX/indices/commodities) — nooit thematisch
# classificeren. Deze module gaat over sector-thema's van BEDRIJVEN; een
# valutapaar of landen-index heeft geen "thema" en zou de LLM alleen maar
# dwingen tot een geforceerd/onzinnig voorstel. Bewust géén automatische
# detectie (bv. "geen aandeel-achtige naam") — expliciete lijst is
# voorspelbaar en makkelijk uit te breiden. Overgenomen/uitgebreid t.o.v.
# shadow_xyz_lab.py's _COMMODITY_XYZ/_NON_EQUITY_XYZ (dat bestand blijft
# ongewijzigd, dit is een eigen kopie voor deze module).
_NON_EQUITY_REAL_SYMBOLS = frozenset({
    # FX
    "EUR", "GBP", "JPY", "KRW",
    # Macro/benchmark-indices
    "KR200", "JP225", "SP500", "NIFTY", "IBOV", "XYZ100", "DXY", "VIX", "VOL",
    # Landen-ETF's
    "EWY", "EWJ", "EWT", "EWZ",
    # Commodities
    "CL", "BRENTOIL", "GOLD", "SILVER", "NATGAS", "COPPER", "PLATINUM",
    "PALLADIUM", "ALUMINIUM", "URANIUM", "CORN", "WHEAT", "TTF",
})

# Crash-scoring drempels (tunable)
PULLBACK_VOL_THRESHOLD = 1.5   # vol-genormaliseerde "eenheden onder het 252d-high"
BREADTH_THRESHOLD = 0.30       # aandeel tickers in thema dat ook >= pullback-drempel scoort
STABILIZATION_LOOKBACK = 5     # dagen — laatste close mag niet op het 5d-low liggen

# Tranche-plan (fractie van het per-naam-budget)
TRANCHE_PCTS = {1: 0.20, 2: 0.30, 3: 0.30, 4: 0.20}

# Executie-guards
PRICE_SANITY_MAX_DEV_PCT = 2.0
FUNDING_ALERT_ANNUALIZED_PCT = 8.0

LEVERAGE = 1
MARGIN_MODE = "isolated"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _finite(x, default=0.0):
    try:
        x = float(x)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


class ThematicDipLab:
    def __init__(self, exchange_client=None):
        self.exchange_client = exchange_client
        self._llm = None

    # ── LLM ──────────────────────────────────────────────────────────────
    def _get_llm(self):
        if self._llm is None:
            try:
                from utils.llm_client import LLMClient
                self._llm = LLMClient()
            except Exception as e:
                logger.warning(f"ThematicDipLab: LLM init mislukt ({e})")
                self._llm = False  # sentinel: geprobeerd en mislukt
        return self._llm if self._llm else None

    # ── config / state I/O ──────────────────────────────────────────────
    @staticmethod
    def _load_themes() -> dict:
        try:
            with open(THEMES_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"{THEMES_FILE} niet leesbaar: {e}")
            return {"themes": {}, "tickers": {}, "pending": {}}

    @staticmethod
    def _save_themes(data: dict) -> None:
        try:
            with open(THEMES_FILE, "w") as f:
                json.dump(data, f, indent=1)
        except Exception as e:
            logger.error(f"{THEMES_FILE} schrijven mislukt: {e}")

    @staticmethod
    def _load_state() -> dict:
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def _save_state(state: dict) -> None:
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=1)
        except Exception as e:
            logger.error(f"{STATE_FILE} schrijven mislukt: {e}")

    @staticmethod
    def _load_positions() -> dict:
        try:
            with open(POSITIONS_FILE) as f:
                data = json.load(f)
                data.setdefault("budget_usd", DEFAULT_BUDGET_USD)
                data.setdefault("cash_usd", data["budget_usd"])
                data.setdefault("positions", {})
                data.setdefault("realized_pnl_usd", 0.0)
                return data
        except Exception:
            return {
                "budget_usd": DEFAULT_BUDGET_USD,
                "cash_usd": DEFAULT_BUDGET_USD,
                "positions": {},
                "realized_pnl_usd": 0.0,
            }

    @staticmethod
    def _save_positions(data: dict) -> None:
        try:
            with open(POSITIONS_FILE, "w") as f:
                json.dump(data, f, indent=1)
        except Exception as e:
            logger.error(f"{POSITIONS_FILE} schrijven mislukt: {e}")

    @staticmethod
    def _save_report(report: dict) -> None:
        try:
            with open(REPORT_FILE, "w") as f:
                json.dump(report, f, indent=1)
        except Exception as e:
            logger.error(f"{REPORT_FILE} schrijven mislukt: {e}")

    # ── HL publieke "xyz"-dex data ───────────────────────────────────────
    @staticmethod
    def _http_post(payload: dict) -> dict:
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def _xyz_snapshot(self) -> dict:
        """Returns {ticker: {mark_px, day_volume_usd, funding_pct_8h}} voor alle XYZ-perps."""
        data = self._http_post({"type": "metaAndAssetCtxs", "dex": "xyz"})
        assets = [a["name"] for a in data[0]["universe"]]
        out = {}
        for name, ctx in zip(assets, data[1]):
            if not name.startswith("xyz:"):
                continue
            px = _finite(ctx.get("markPx"))
            if px <= 0:
                continue
            display = "XYZ-" + name.split(":", 1)[1]
            out[display] = {
                "mark_px": px,
                "day_volume_usd": _finite(ctx.get("dayNtlVlm")),
                "funding_pct_8h": _finite(ctx.get("funding")) * 100,
            }
        return out

    # ── classificatie van nieuwe tickers ─────────────────────────────────
    def _scan_new_tickers(self) -> None:
        """Diff huidig XYZ-universum tegen de geregistreerde set; stel voor
        nieuwe tickers een thema-classificatie voor via LLM en meld via
        Telegram (eenrichtings — zie EXP-008 in roadmap.json)."""
        try:
            snapshot = self._xyz_snapshot()
        except Exception as e:
            logger.debug(f"ThematicDipLab: universe-scan mislukt: {e}")
            return
        if not snapshot:
            return

        themes = self._load_themes()
        known = set(themes.get("tickers", {}).keys())
        new_tickers_raw = [t for t in snapshot.keys() if t not in known]
        if not new_tickers_raw:
            return

        # Eerste-scan-guard: het hele bestaande universum niet als "nieuw"
        # behandelen. Vóór alle filtering/classificatie, en onafhankelijk van
        # hoeveel er na filtering overblijft — anders kan een cyclus waarin
        # toevallig alles wordt weggefilterd (non-equity/dun) de vlag nooit
        # zetten en blijft de guard af en toe opnieuw afgaan.
        state = self._load_state()
        if not state.get("universe_seeded"):
            state["universe_seeded"] = True
            self._save_state(state)
            logger.info(
                f"[ThematicDipLab] Eerste scan: {len(new_tickers_raw)} tickers als baseline "
                f"overgeslagen (geen classificatie-run)"
            )
            return

        # Non-equity instrumenten (FX/indices/commodities) en dunne/obscure
        # tickers meteen IGNORED — geen LLM-call, geen notificatie. Bart wil
        # bewust geen brede dekking van alles wat toevallig op HL genoteerd
        # staat, alleen de belangrijkste bedrijven — dat filtert ruis (dunne
        # namen bewegen toch al harder/willekeuriger) en houdt de review-
        # wachtrij klein.
        new_tickers = []
        for ticker in new_tickers_raw:
            real_symbol = ticker.split("-", 1)[1] if "-" in ticker else ticker
            day_volume = snapshot.get(ticker, {}).get("day_volume_usd", 0.0)
            if real_symbol in _NON_EQUITY_REAL_SYMBOLS:
                themes.setdefault("tickers", {})[ticker] = {
                    "real_symbol": real_symbol, "themes": {}, "status": "IGNORED",
                    "note": "non-equity instrument (FX/index/commodity), auto-uitgesloten",
                }
            elif day_volume < MIN_DAY_VOLUME_USD:
                themes.setdefault("tickers", {})[ticker] = {
                    "real_symbol": real_symbol, "themes": {}, "status": "IGNORED",
                    "note": f"dagvolume ${day_volume:,.0f} < ${MIN_DAY_VOLUME_USD:,.0f} drempel, auto-uitgesloten",
                }
            else:
                new_tickers.append(ticker)

        if not new_tickers:
            self._save_themes(themes)  # persist any auto-IGNORED entries even with nothing left to classify
            return

        results = []  # (ticker, status, themes_dict) — voor één samengevoegd Telegram-bericht
        for ticker in new_tickers[:MAX_NEW_CLASSIFICATIONS_PER_CYCLE]:
            results.append(self._classify_ticker(ticker, themes))
        self._save_themes(themes)
        self._notify_classification_batch(results)

    def _classify_ticker(self, ticker: str, themes: dict) -> tuple:
        real_symbol = ticker.split("-", 1)[1] if "-" in ticker else ticker
        theme_ids = list(themes.get("themes", {}).keys())
        prompt = (
            f'Classify the stock/asset ticker "{real_symbol}" into zero or more of these '
            f"investment themes: {', '.join(theme_ids)}.\n\n"
            'Respond ONLY with a JSON object, no markdown, no commentary:\n'
            '{"themes": {"theme_id": fractional_weight, ...}, "confidence": "high"|"low"}\n\n'
            "Fractional weights per theme should be between 0 and 1 and reflect how core this "
            'ticker is to that theme. If the ticker does not fit any theme, return '
            '{"themes": {}, "confidence": "low"}.\n\n'
            "SELECTIVITY: only propose a theme fit for major, systemically important, well-known "
            "companies whose price action is representative of the whole theme — the goal is to "
            "measure sector-wide crashes, not to cover every company that happens to be tangentially "
            "related. A smaller/niche/thinly-known company should get {\"themes\": {}, \"confidence\": "
            "\"low\"} even if there IS a topical connection to a theme — being loosely related is not "
            "enough. When in doubt, prefer no fit over a weak fit.\n\n"
            'IMPORTANT: "confidence": "high" auto-confirms this classification for LIVE TRADING '
            "with real capital — no human review. Only use \"high\" when you are certain of the "
            "company's identity AND its core business obviously and unambiguously fits the theme(s) "
            '(e.g. NVDA -> semiconductors). Use "low" for anything uncertain: an unfamiliar/ambiguous '
            "ticker, a conglomerate or holding company where the theme fit is indirect, or any real "
            "doubt about what this ticker actually represents."
        )

        llm = self._get_llm()
        proposal = None
        if llm:
            try:
                raw = llm.analyze_text(prompt, agent_name="ThematicDipLab", thinking=False)
                cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
                m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                    if isinstance(parsed.get("themes"), dict):
                        proposal = parsed
            except Exception as e:
                logger.warning(f"ThematicDipLab: classificatie van {ticker} mislukt: {e}")

        if proposal and proposal["themes"]:
            # Auto-confirm alleen als de LLM zelf "high" confidence rapporteert
            # (2026-07-16, op Bart's verzoek: handmatige review mag eruit voor
            # de duidelijke gevallen). Bij "low"/ontbrekend blijft een mens
            # nodig — juist wanneer de LLM zelf twijfelt is een check zinvol,
            # zeker omdat CONFIRMED meteen meetelt voor live T1-executie.
            auto_confirm = str(proposal.get("confidence", "")).lower() == "high"
            status = "CONFIRMED" if auto_confirm else "PENDING_REVIEW"
            themes.setdefault("tickers", {})[ticker] = {
                "real_symbol": real_symbol,
                "themes": proposal["themes"],
                "status": status,
            }
            logger.info(f"[ThematicDipLab] {ticker}: {status} ({proposal['themes']})")
            return (ticker, status, proposal["themes"])
        else:
            themes.setdefault("tickers", {})[ticker] = {
                "real_symbol": real_symbol, "themes": {}, "status": "PENDING_MANUAL",
            }
            logger.info(f"[ThematicDipLab] {ticker}: classificatie mislukt/leeg — PENDING_MANUAL")
            return (ticker, "PENDING_MANUAL", {})

    def _notify_classification_batch(self, results: list) -> None:
        """Eén samengevoegd bericht per cyclus i.p.v. één per ticker (bug
        2026-07-16: universum-classificatie stuurde tientallen losse pushes).
        PENDING_MANUAL (geen voorstel, niets om op te reageren) wordt alleen
        geteld, niet uitgeschreven — zichtbaar via /diplist, niet elke keer
        gepusht. CONFIRMED (auto, high confidence) wordt gemeld ter info, geen
        actie nodig. Plain text (geen parse_mode) — theme-ID's als 'ai_native'
        breken Telegram's Markdown-onderstrepingsparsing anders willekeurig."""
        auto_confirmed = [(t, th) for t, status, th in results if status == "CONFIRMED"]
        reviewable = [(t, th) for t, status, th in results if status == "PENDING_REVIEW"]
        manual_count = sum(1 for _, status, _ in results if status == "PENDING_MANUAL")
        if not auto_confirmed and not reviewable and not manual_count:
            return

        lines = [f"Thematic Dip Lab — {len(results)} nieuwe ticker(s) gescand"]
        if auto_confirmed:
            lines.append("  Auto-CONFIRMED (high confidence, telt al mee):")
            for ticker, theme_weights in auto_confirmed:
                themes_str = ", ".join(f"{k} {v:.2f}" for k, v in theme_weights.items())
                lines.append(f"    {ticker} -> {themes_str}  (/dipignore {ticker} om terug te draaien)")
        for ticker, theme_weights in reviewable:
            themes_str = ", ".join(f"{k} {v:.2f}" for k, v in theme_weights.items())
            lines.append(f"  {ticker} -> {themes_str} (low confidence, review gewenst)")
            lines.append(f"    /dipapprove {ticker}  |  /dipedit {ticker} thema:gewicht  |  /dipignore {ticker}")
        if manual_count:
            lines.append(f"  + {manual_count} zonder voorstel (PENDING_MANUAL) — zie /diplist")
        self._notify_telegram("\n".join(lines), plain=True)

    # ── prijs-historie (yfinance) ────────────────────────────────────────
    def _fetch_price_history(self, real_symbols: list) -> dict:
        """Batched yfinance daily OHLC, ~24h TTL-cache. Returns {real_symbol: {'closes': [...]}}"""
        state = self._load_state()
        cache = state.get("price_cache", {})
        cache_ts = state.get("price_cache_ts", 0)
        fresh = time.time() - cache_ts < PRICE_HISTORY_TTL_H * 3600
        missing = [s for s in real_symbols if s not in cache]
        if fresh and not missing:
            return cache

        try:
            import yfinance as yf
            data = yf.download(
                tickers=" ".join(real_symbols), period=PRICE_HISTORY_PERIOD, interval="1d",
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            logger.warning(f"ThematicDipLab: yfinance batch-fetch mislukt: {e}")
            return cache

        new_cache = {}
        for sym in real_symbols:
            try:
                col = data[sym] if len(real_symbols) > 1 else data
                closes = [c for c in col["Close"].dropna().tolist() if math.isfinite(c) and c > 0]
                if len(closes) < 20:
                    continue
                new_cache[sym] = {"closes": closes[-260:]}
            except Exception:
                continue

        if new_cache:
            state["price_cache"] = new_cache
            state["price_cache_ts"] = time.time()
            self._save_state(state)
            return new_cache
        return cache  # fetch mislukt/leeg — val terug op oude cache i.p.v. alles te wissen

    # ── crash-scoring ─────────────────────────────────────────────────────
    @staticmethod
    def _realized_vol(closes: list) -> float:
        """Dagelijkse std-dev van log-returns over de laatste 20 sessies."""
        window = closes[-21:]
        if len(window) < 10:
            return 0.0
        rets = [math.log(window[i] / window[i - 1]) for i in range(1, len(window)) if window[i - 1] > 0]
        if len(rets) < 5:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        return math.sqrt(var)

    def _pullback_score(self, closes: list, current_price: float) -> dict:
        """Vol-genormaliseerde drawdown vanaf 252d-high + crash-snelheid +
        stabilisatie- en herstel-signalen."""
        empty = {"pullback_z": 0.0, "speed_z": 0.0, "stabilized": False, "recovering": False, "drawdown_pct": 0.0}
        if not closes or current_price <= 0:
            return empty
        window = closes[-252:]
        high = max(window + [current_price])
        if high <= 0:
            return empty
        vol = self._realized_vol(closes)
        if vol <= 0:
            return empty

        drawdown = (high - current_price) / high
        pullback_z = drawdown / vol

        # Snelheid: deel van de drawdown dat in de laatste 20 sessies bijkwam
        recent_ref = window[-21] if len(window) >= 21 else window[0]
        recent_drop = max(0.0, (recent_ref - current_price) / high)
        speed_z = recent_drop / vol

        # Stabilisatie: laatste close mag niet óp het 5d-low liggen ("het mes ligt stil")
        lookback = (window + [current_price])[-STABILIZATION_LOOKBACK:]
        five_d_low = min(lookback)
        stabilized = current_price > five_d_low * 1.001

        # Herstel (voor T3): boven 20d-MA, met een hogere bodem dan het recente low
        recovering = False
        if len(window) >= 20:
            sma20 = sum(window[-20:]) / 20
            lookback_low = min(window[-10:-3]) if len(window) >= 10 else None
            recovering = bool(lookback_low and current_price > sma20 and current_price > lookback_low)

        return {
            "pullback_z": pullback_z,
            "speed_z": speed_z,
            "stabilized": stabilized,
            "recovering": recovering,
            "drawdown_pct": drawdown * 100,
        }

    def _theme_breadth(self, scores: dict, themes_cfg: dict) -> dict:
        """Per thema: aandeel geclassificeerde tickers dat >= PULLBACK_VOL_THRESHOLD scoort."""
        breadth = {}
        for theme_id in themes_cfg.get("themes", {}):
            members = [
                t for t, cfg in themes_cfg.get("tickers", {}).items()
                if cfg.get("status") == "CONFIRMED" and theme_id in (cfg.get("themes") or {})
            ]
            if not members:
                breadth[theme_id] = 0.0
                continue
            hit = sum(1 for t in members if scores.get(t, {}).get("pullback_z", 0) >= PULLBACK_VOL_THRESHOLD)
            breadth[theme_id] = hit / len(members)
        return breadth

    def _score_and_report(self) -> dict:
        themes_cfg = self._load_themes()
        confirmed = {
            t: cfg for t, cfg in themes_cfg.get("tickers", {}).items()
            if cfg.get("status") == "CONFIRMED" and cfg.get("real_symbol")
        }
        if not confirmed:
            return {}

        try:
            snapshot = self._xyz_snapshot()
        except Exception as e:
            logger.debug(f"ThematicDipLab: scoring-snapshot mislukt: {e}")
            return {}

        real_symbols = sorted({cfg["real_symbol"] for cfg in confirmed.values()})
        history = self._fetch_price_history(real_symbols)

        scores = {}
        for ticker, cfg in confirmed.items():
            live = snapshot.get(ticker)
            hist = history.get(cfg["real_symbol"])
            if not live or not hist or live.get("day_volume_usd", 0) < MIN_DAY_VOLUME_USD:
                continue
            s = self._pullback_score(hist["closes"], live["mark_px"])
            s["ticker"] = ticker
            s["day_volume_usd"] = live["day_volume_usd"]
            s["funding_pct_8h"] = live.get("funding_pct_8h", 0.0)
            s["mark_px"] = live["mark_px"]
            scores[ticker] = s

        breadth = self._theme_breadth(scores, themes_cfg)
        for ticker, s in scores.items():
            ticker_themes = confirmed[ticker].get("themes") or {}
            s["theme_breadth"] = max((breadth.get(th, 0.0) for th in ticker_themes), default=0.0)
            s["qualifies"] = (
                s["pullback_z"] >= PULLBACK_VOL_THRESHOLD
                and s["theme_breadth"] >= BREADTH_THRESHOLD
                and s["stabilized"]
            )

        report = {
            "generated_at": _now_iso(),
            "breadth_by_theme": breadth,
            "scores": scores,
            "qualifying": sorted(
                (t for t, s in scores.items() if s["qualifies"]),
                key=lambda t: -scores[t]["pullback_z"],
            )[:MAX_CONCURRENT_NAMES],
        }
        self._save_report(report)
        return report

    # ── tranche-triggers ─────────────────────────────────────────────────
    @staticmethod
    def _tranche_trigger(stage: int, score: dict, pos: dict) -> bool:
        if stage == 2:
            entry = pos.get("avg_entry_price", 0.0)
            mark = score.get("mark_px", 0.0)
            drop_from_entry_pct = max(0.0, (entry - mark) / entry * 100) if entry > 0 else 0.0
            return drop_from_entry_pct >= 10.0 and score.get("theme_breadth", 0) >= BREADTH_THRESHOLD
        if stage == 3:
            return bool(score.get("recovering", False))
        if stage == 4:
            return score.get("pullback_z", 0) >= PULLBACK_VOL_THRESHOLD * 1.5
        return False

    # ── T1-T4 executie (buiten de council-pipeline, zelfde patroon als
    # TreasuryAgent._open_harvest_position) ──────────────────────────────
    def _maybe_advance_tranches(self, report: dict) -> None:
        if self.exchange_client is None:
            return
        positions = self._load_positions()
        themes_cfg = self._load_themes()
        t2_t4_enabled = self._load_state().get("t2_t4_enabled", False)

        open_tickers = {t for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}

        # Nieuwe T1's — altijd live vanaf dag 1, ongeacht t2_t4_enabled.
        qualifying = [t for t in report.get("qualifying", []) if t not in open_tickers]
        n_slots = max(0, MAX_CONCURRENT_NAMES - len(open_tickers))
        for ticker in qualifying[:n_slots]:
            self._open_tranche(ticker, 1, themes_cfg, positions, report)

        if not t2_t4_enabled:
            return  # T2-T4 blijft dry-run — zie _t2_t4_preview() in daily_status_text()

        for ticker in list(open_tickers):
            pos = positions.get("positions", {}).get(ticker)
            if not pos or pos.get("tranche_stage", 1) >= 4:
                continue
            s = report.get("scores", {}).get(ticker)
            if not s:
                continue
            next_stage = pos["tranche_stage"] + 1
            if self._tranche_trigger(next_stage, s, pos):
                self._open_tranche(ticker, next_stage, themes_cfg, positions, report)

    def _open_tranche(self, ticker: str, stage: int, themes_cfg: dict, positions: dict, report: dict) -> None:
        from core.strategy_logic import detect_asset_class
        from agents.xyz_technical_analyst import _market_is_open

        # Guard (a): markt-uren — XYZ-synthetics drijven buiten beurstijd zonder
        # verse prijsontdekking (zie shadow_xyz_lab's open-gap-tracker).
        asset_class = detect_asset_class(ticker)
        if not _market_is_open(asset_class, datetime.now(timezone.utc)):
            logger.debug(f"ThematicDipLab: {ticker} markt gesloten — T{stage} uitgesteld")
            return

        budget = _finite(positions.get("budget_usd"), DEFAULT_BUDGET_USD)
        cash = _finite(positions.get("cash_usd"), budget)
        per_name_budget = budget / MAX_CONCURRENT_NAMES
        tranche_usd = per_name_budget * TRANCHE_PCTS[stage]
        if tranche_usd > cash:
            logger.info(f"ThematicDipLab: onvoldoende cash voor T{stage} {ticker} (${tranche_usd:.2f} > ${cash:.2f})")
            return

        try:
            mark_price = self.exchange_client.get_market_price(ticker)
        except Exception as e:
            logger.warning(f"ThematicDipLab: prijs ophalen mislukt voor {ticker}: {e}")
            return
        mark_price = _finite(mark_price)
        if mark_price <= 0:
            return

        # Guard (b): prijs-sanity vs laatste yfinance-close
        real_symbol = themes_cfg.get("tickers", {}).get(ticker, {}).get("real_symbol", ticker.split("-", 1)[-1])
        hist = self._load_state().get("price_cache", {}).get(real_symbol)
        if hist and hist.get("closes"):
            last_close = hist["closes"][-1]
            if last_close > 0 and abs(mark_price - last_close) / last_close * 100 > PRICE_SANITY_MAX_DEV_PCT:
                logger.warning(
                    f"ThematicDipLab: prijs-sanity-check faalt voor {ticker} "
                    f"(mark={mark_price:.2f} vs yfinance-close={last_close:.2f}) — order overgeslagen"
                )
                return

        # Guard: min-notional — bewuste skip i.p.v. structurele basket-wijziging
        try:
            min_notional = self.exchange_client.get_min_notional(ticker) or 10.0
        except Exception:
            min_notional = 10.0
        if tranche_usd < min_notional + 1.0:
            logger.info(f"ThematicDipLab: T{stage} voor {ticker} (${tranche_usd:.2f}) onder min-notional — overgeslagen")
            return

        precision = 0.0
        try:
            precision = self.exchange_client.get_amount_precision(ticker) or 0.0
        except Exception:
            pass
        quantity = tranche_usd / mark_price
        if precision > 0:
            quantity = math.floor(quantity / precision) * precision
        if quantity <= 0:
            return

        order = self.exchange_client.create_order(
            ticker, "BUY", quantity, order_type="market",
            leverage=LEVERAGE, margin_mode=MARGIN_MODE,
        )
        if order is None:
            logger.warning(f"ThematicDipLab: T{stage}-order voor {ticker} mislukt (exchange gaf None terug)")
            return

        notional_usd = quantity * mark_price
        self._record_open_or_add(positions, ticker, stage, themes_cfg, quantity, mark_price, notional_usd)
        self._append_trade_log(ticker, quantity, mark_price, notional_usd)
        self._notify_telegram(
            f"🟢 *Thematic Dip Lab — T{stage} {'geopend' if stage == 1 else 'bijgekocht'}*\n"
            f"{ticker} — {quantity:.4f} @ ${mark_price:.2f} (${notional_usd:.2f}, 1x isolated)"
        )

    def _record_open_or_add(self, positions: dict, ticker: str, stage: int, themes_cfg: dict,
                             quantity: float, price: float, notional_usd: float) -> None:
        positions.setdefault("positions", {})
        existing = positions["positions"].get(ticker)
        if existing and existing.get("status") == "OPEN":
            old_qty = _finite(existing.get("quantity"))
            old_cost = _finite(existing.get("cost_basis_usd"))
            new_qty = old_qty + quantity
            new_cost = old_cost + notional_usd
            existing["quantity"] = new_qty
            existing["avg_entry_price"] = new_cost / new_qty if new_qty > 0 else price
            existing["cost_basis_usd"] = new_cost
            existing["current_mark_price"] = price
            existing["current_value_usd"] = new_qty * price
            existing["tranche_stage"] = stage
            existing["last_updated"] = _now_iso()
        else:
            positions["positions"][ticker] = {
                "themes": themes_cfg.get("tickers", {}).get(ticker, {}).get("themes", {}),
                "tranche_stage": stage,
                "status": "OPEN",
                "quantity": quantity,
                "avg_entry_price": price,
                "cost_basis_usd": notional_usd,
                "current_mark_price": price,
                "current_value_usd": notional_usd,
                "opened_at": _now_iso(),
                "last_updated": _now_iso(),
            }
        positions["cash_usd"] = _finite(positions.get("cash_usd"), positions.get("budget_usd", DEFAULT_BUDGET_USD)) - notional_usd
        positions.setdefault("budget_usd", DEFAULT_BUDGET_USD)
        self._save_positions(positions)

    def _append_trade_log(self, ticker: str, quantity: float, price: float, notional_usd: float) -> None:
        """Schrijft een OPEN-record in trade_log.json, getagd 'thematic_dip': True
        zodat de auditor/weight-learning-loop deze trade negeert (zelfde patroon
        als 'harvest': True — zie agents/execution_agent.py + strategy_manager.py guards)."""
        try:
            with open("trade_log.json") as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append({
            "id": f"THEMATIC_DIP_{ticker}_{int(time.time())}",
            "ticker": ticker,
            "action": "BUY",
            "quantity": quantity,
            "entry_price": price,
            "size_usd": notional_usd,
            "entry_time": time.time(),
            "status": "OPEN",
            "pnl": 0.0,
            "analyst_signals": {},
            "thematic_dip": True,
        })
        try:
            with open("trade_log.json", "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"trade_log.json schrijven mislukt (thematic_dip open): {e}")

    def _close_trade_log(self, ticker: str, price: float, pnl: float) -> None:
        try:
            with open("trade_log.json") as f:
                log = json.load(f)
        except Exception:
            return
        for t in log:
            if t.get("ticker") == ticker and t.get("status") == "OPEN" and t.get("thematic_dip"):
                t["status"] = "CLOSED"
                t["exit_price"] = price
                t["pnl"] = pnl
                t["exit_time"] = _now_iso()
                break
        try:
            with open("trade_log.json", "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"trade_log.json schrijven mislukt (thematic_dip close): {e}")

    # ── exit-beheer (ook live vanaf dag 1 — een onbeheerde open positie is
    # onverantwoord) ───────────────────────────────────────────────────
    def _manage_exits(self) -> None:
        if self.exchange_client is None:
            return
        positions = self._load_positions()
        open_positions = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}
        if not open_positions:
            return

        changed = False
        for ticker, pos in open_positions.items():
            try:
                mark = self.exchange_client.get_market_price(ticker)
            except Exception:
                continue
            mark = _finite(mark)
            if mark <= 0:
                continue
            pos["current_mark_price"] = mark
            pos["current_value_usd"] = pos["quantity"] * mark
            pos["last_updated"] = _now_iso()
            changed = True

            entry = _finite(pos.get("avg_entry_price"))
            gain_pct = (mark - entry) / entry * 100 if entry > 0 else 0.0
            pos["peak_value_usd"] = max(_finite(pos.get("peak_value_usd")), pos["current_value_usd"])

            exit_reason, exit_fraction = None, 0.0
            if gain_pct >= 100 and not pos.get("profit_tranche_3_done"):
                exit_reason, exit_fraction = "winst-tranche +100%", 0.25
                pos["profit_tranche_3_done"] = True
            elif gain_pct >= 60 and not pos.get("profit_tranche_2_done"):
                exit_reason, exit_fraction = "winst-tranche +60%", 0.25
                pos["profit_tranche_2_done"] = True
            elif gain_pct >= 30 and not pos.get("profit_tranche_1_done"):
                exit_reason, exit_fraction = "winst-tranche +30%", 0.25
                pos["profit_tranche_1_done"] = True
            elif gain_pct > 0 and pos["current_value_usd"] < pos["peak_value_usd"] * 0.80:
                exit_reason, exit_fraction = "NAV-trailing-stop -20% (na winstgevend)", 1.0

            if exit_reason:
                self._close_or_trim(positions, ticker, pos, mark, exit_fraction, exit_reason)

        if changed:
            self._save_positions(positions)

    def _close_or_trim(self, positions: dict, ticker: str, pos: dict, mark: float,
                        fraction: float, reason: str) -> None:
        qty_to_sell = pos["quantity"] * fraction
        precision = 0.0
        try:
            precision = self.exchange_client.get_amount_precision(ticker) or 0.0
        except Exception:
            pass
        if precision > 0:
            qty_to_sell = math.floor(qty_to_sell / precision) * precision
        if qty_to_sell <= 0:
            return

        order = self.exchange_client.create_order(
            ticker, "SELL", qty_to_sell, order_type="market",
            leverage=LEVERAGE, margin_mode=MARGIN_MODE,
        )
        if order is None:
            logger.warning(f"ThematicDipLab: exit-order voor {ticker} mislukt ({reason})")
            return

        proceeds = qty_to_sell * mark
        cost_basis_sold = pos["avg_entry_price"] * qty_to_sell
        realized_pnl = proceeds - cost_basis_sold

        pos["quantity"] -= qty_to_sell
        pos["cost_basis_usd"] = pos["avg_entry_price"] * pos["quantity"]
        pos["current_value_usd"] = pos["quantity"] * mark
        positions["cash_usd"] = _finite(positions.get("cash_usd")) + proceeds
        positions["realized_pnl_usd"] = _finite(positions.get("realized_pnl_usd")) + realized_pnl

        full_close = pos["quantity"] <= max(precision, 1e-6)
        if full_close:
            pos["status"] = "CLOSED"
            pos["closed_at"] = _now_iso()
            self._close_trade_log(ticker, mark, realized_pnl)
        # bij een gedeeltelijke exit blijft de OPEN trade_log-entry staan — de
        # oorspronkelijke BUY-entry_price/quantity representeren dan de resterende
        # kernpositie niet meer exact, maar trade_log wordt hier uitsluitend voor
        # de auditor-isolatie gebruikt (zie guards), niet voor P&L-rapportage —
        # die leest thematic_dip_positions.json.

        self._save_positions(positions)
        self._notify_telegram(
            f"🔴 *Thematic Dip Lab — exit*\n{ticker} — {reason}\n"
            f"{qty_to_sell:.4f} @ ${mark:.2f} — gerealiseerd: ${realized_pnl:+.2f}"
            f"{' (volledig gesloten)' if full_close else ''}"
        )

    # ── funding-drag-monitor (guard c) ───────────────────────────────────
    def _check_funding_drag(self, positions: dict) -> list:
        alerts = []
        try:
            snapshot = self._xyz_snapshot()
        except Exception:
            return alerts
        state = self._load_state()
        fund_hist = state.setdefault("funding_history", {})
        for ticker, pos in positions.get("positions", {}).items():
            if pos.get("status") != "OPEN":
                continue
            live = snapshot.get(ticker)
            if not live:
                continue
            hist = fund_hist.setdefault(ticker, [])
            hist.append(live.get("funding_pct_8h", 0.0))
            fund_hist[ticker] = hist[-90:]  # ~30 dagen bij 3 metingen/dag (cycle-hook interval)
            avg_8h = sum(hist) / len(hist)
            annualized = avg_8h * 3 * 365
            if annualized > FUNDING_ALERT_ANNUALIZED_PCT:
                alerts.append(f"{ticker}: funding {annualized:.1f}%/jr (30d-gem.)")
        self._save_state(state)
        return alerts

    # ── T2-T4 dry-run preview (voor het dagrapport, zolang t2_t4_enabled=false) ──
    def _t2_t4_preview(self, report: dict, positions: dict) -> list:
        preview = []
        if self._load_state().get("t2_t4_enabled", False):
            return preview  # dan is het geen preview meer — het gebeurt al echt
        for ticker, pos in positions.get("positions", {}).items():
            if pos.get("status") != "OPEN" or pos.get("tranche_stage", 1) >= 4:
                continue
            s = report.get("scores", {}).get(ticker)
            if not s:
                continue
            next_stage = pos["tranche_stage"] + 1
            if self._tranche_trigger(next_stage, s, pos):
                preview.append(f"{ticker}: T{next_stage} zou nu vuren")
        return preview

    # ── telegram ──────────────────────────────────────────────────────────
    @staticmethod
    def _notify_telegram(text: str, plain: bool = False) -> None:
        """plain=True skips the Markdown attempt entirely — use for any text
        that may contain a lone underscore (e.g. theme IDs like 'ai_native'):
        Telegram's legacy Markdown parser doesn't reliably reject unbalanced
        '_' emphasis markers, it sometimes silently mangles the text instead
        (bug 2026-07-16: 'ai_native' rendered as 'ainative' mid-message)."""
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            logger.info(f"ThematicDipLab (geen Telegram):\n{text}")
            return
        modes = (None,) if plain else ("Markdown", None)
        for parse_mode in modes:
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
                logger.warning(f"ThematicDipLab: Telegram send mislukt (mode={parse_mode}): {e}")

    # ── dagelijkse status (aangehaakt in de sleeve_nav-digest) ──────────────
    def daily_status_text(self) -> str:
        try:
            with open(REPORT_FILE) as f:
                report = json.load(f)
        except Exception:
            report = {}
        positions = self._load_positions()
        open_positions = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}

        lines = ["", "🧠 *Thematic Dip Sleeve (EXP-008)*"]
        active_themes = [t for t, b in (report.get("breadth_by_theme") or {}).items() if b >= BREADTH_THRESHOLD]
        lines.append(f"  Actieve thema's: {', '.join(active_themes) if active_themes else 'geen'}")
        lines.append(f"  Open T1-posities: {len(open_positions)}/{MAX_CONCURRENT_NAMES}")
        if open_positions:
            total_value = sum(_finite(p.get("current_value_usd")) for p in open_positions.values())
            total_cost = sum(_finite(p.get("cost_basis_usd")) for p in open_positions.values())
            lines.append(f"  Waarde: ${total_value:,.2f} | ongerealiseerd: ${total_value - total_cost:+,.2f}")
        lines.append(f"  Vrij budget: ${_finite(positions.get('cash_usd')):,.2f}")
        preview = self._t2_t4_preview(report, positions)
        if preview:
            lines.append(f"  T2-T4 (nog uit, zou vuren): {'; '.join(preview[:3])}")
        funding_alerts = self._check_funding_drag(positions)
        if funding_alerts:
            lines.append(f"  ⚠️ Funding-drag: {'; '.join(funding_alerts)}")
        return "\n".join(lines)

    # ── hoofd-cycle (aangeroepen vanuit main.py, cycle_count % 5 == 1) ──────
    def run_cycle(self) -> None:
        self._scan_new_tickers()
        report = self._score_and_report()
        self._manage_exits()
        if report:
            self._maybe_advance_tranches(report)


# ── Review-acties (goedkeuren/corrigeren/negeren van nieuwe tickers) ──────
# Module-level, geen ThematicDipLab-instantie nodig — enige bron van waarheid
# voor deze drie acties, hergebruikt door zowel de Telegram-commando's
# (agents/swarm_monitor.py: /dipapprove /dipedit /dipignore) als de
# dashboard-API (/api/thematic-dip/*, utils/dashboard_server.py). Eerder
# stond deze logica alleen in swarm_monitor.py; nu op één plek zodat beide
# interfaces gegarandeerd hetzelfde gedrag hebben.

def approve_ticker(ticker: str) -> tuple:
    """Accepteert het bestaande LLM-voorstel zoals het is. Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicDipLab._load_themes()
    except Exception as e:
        return False, f"Kan {THEMES_FILE} niet laden: {e}"
    entry = data.get("tickers", {}).get(ticker)
    if not entry:
        return False, f"{ticker} niet gevonden in de thema-registry."
    if not entry.get("themes"):
        return False, f"{ticker} heeft geen thema-voorstel (classificatie mislukt) — gebruik edit om er zelf een te geven."
    entry["status"] = "CONFIRMED"
    ThematicDipLab._save_themes(data)
    themes_str = ", ".join(f"{k} ({v:.2f})" for k, v in entry["themes"].items())
    return True, f"{ticker} CONFIRMED — {themes_str}"


def edit_ticker(ticker: str, theme_spec: str) -> tuple:
    """theme_spec: 'semiconductors:0.6,memory_storage:0.2'. Overschrijft het
    voorstel en accepteert in één stap. Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicDipLab._load_themes()
    except Exception as e:
        return False, f"Kan {THEMES_FILE} niet laden: {e}"
    known_themes = set(data.get("themes", {}).keys())
    new_themes = {}
    try:
        for pair in theme_spec.split(","):
            theme_id, weight = pair.split(":")
            theme_id = theme_id.strip()
            if theme_id not in known_themes:
                return False, f"Onbekend thema '{theme_id}'. Bekend: {', '.join(sorted(known_themes))}"
            new_themes[theme_id] = float(weight)
    except (ValueError, AttributeError):
        return False, "Ongeldig formaat. Gebruik: thema:gewicht[,thema:gewicht...]"

    entry = data.setdefault("tickers", {}).get(ticker) or {
        "real_symbol": ticker.split("-", 1)[-1], "themes": {}, "status": "PENDING_MANUAL",
    }
    entry["themes"] = new_themes
    entry["status"] = "CONFIRMED"
    data["tickers"][ticker] = entry
    ThematicDipLab._save_themes(data)
    themes_str = ", ".join(f"{k} ({v:.2f})" for k, v in new_themes.items())
    return True, f"{ticker} CONFIRMED (handmatig) — {themes_str}"


def ignore_ticker(ticker: str) -> tuple:
    """Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicDipLab._load_themes()
    except Exception as e:
        return False, f"Kan {THEMES_FILE} niet laden: {e}"
    entry = data.get("tickers", {}).get(ticker)
    if not entry:
        return False, f"{ticker} niet gevonden in de thema-registry."
    entry["status"] = "IGNORED"
    ThematicDipLab._save_themes(data)
    return True, f"{ticker} IGNORED — telt niet meer mee in scoring/executie."
