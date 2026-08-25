"""
thematic_exposure_lab.py — EXP-008: Thematic Exposure Sleeve.

Continu draaiende crash-scanner over het volledige XYZ-synthetics-universum op
Hyperliquid. Classificeert tickers in thema's (LLM-voorgesteld). Sinds
2026-07-16 (Bart's verzoek): "high confidence"-voorstellen worden automatisch
CONFIRMED, geen menselijke review nodig — alleen "low confidence"/mislukte
classificaties blijven in de review-wachtrij (config/thematic_exposure_themes.json,
via Telegram-commando's of het /thematic-exposure dashboard). Scoort sectorbrede pullbacks
(vol-genormaliseerde drawdown vanaf 252d-high + crash-snelheid + thema-breedte),
en opent kleine, volledig gedekte (1x, isolated margin) T1-starterposities op
de hardst geraakte, meest liquide namen binnen een vast budget. T2-T4 (verdere
DCA-opbouw) worden alleen ECHT uitgevoerd als thematic_exposure_state.json
t2_t4_enabled=true bevat — tot die tijd berekent en rapporteert de engine wel
wat T2-T4 zou doen (zichtbaar in daily_status_text()).

Doel is niet tech/AI-specifiek: elk thema dat de LLM classificeert en dat een
sectorbrede, bevestigde pullback laat zien kan een positie triggeren — het
huidige tech/AI-thema is de eerste, handmatig geverifieerde seed.

Deze module plaatst ECHTE orders — buiten de council/ProjectLead-pipeline om,
zelfde patroon als TreasuryAgent._open_harvest_position/_close_harvest_position
(agents/treasury_agent.py:1224-1358). Trades worden getagd met
"thematic_exposure": True in trade_log.json zodat de auditor/weight-learning-loop
ze negeert (zelfde isolatie-patroon als "harvest": True).

Files:
  config/thematic_exposure_themes.json — thema-registry + classificatie (bewerkbaar)
  thematic_exposure_state.json         — scan-cache, prijs-historie-cache, funding-historie, t2_t4_enabled-vlag
  thematic_exposure_positions.json     — cash/budget + open/gesloten posities (bron voor SleeveNAV)
  thematic_exposure_report.json        — laatste scoring-snapshot, voor dashboard/digest
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

logger = logging.getLogger("ThematicExposureLab")

THEMES_FILE = "config/thematic_exposure_themes.json"
STATE_FILE = "thematic_exposure_state.json"
POSITIONS_FILE = "thematic_exposure_positions.json"
REPORT_FILE = "thematic_exposure_report.json"

DEFAULT_BUDGET_USD = 1250.0
# Temporarily lowered from 8 to 4 (2026-07-18, wallet-split cutover): the new
# segregated wallet started with $255, and at 8 names T1 = budget/8*0.20 =
# $6.38/name — under HL's $10 min-notional, so every T1 silently skipped
# (see _open_tranche's min_notional guard). At 4 names T1 = $12.75, clears the
# floor. Raise back to 8 once the wallet is topped up past ~$440
# (min budget for T1 to clear $10+$1 at 8-way split: 10/0.20*8 = $400, +buffer).
#
# ── 2026-08-12: 4 → 6, en het tranche-plan van 4 stappen naar 2 ────────────
# Het comment hierboven redeneert correct over T1, maar de andere helft was
# niemand opgevallen: T2-T4 zijn NOOIT uitgevoerd in het hele bestaan van de
# sleeve. Twee redenen, die elkaar versterken:
#
#   1. `t2_t4_enabled` staat niet in thematic_exposure_state.json → default
#      False (zie _maybe_advance_tranches). Sinds 2026-07-17 dus dry-run.
#   2. Zelfs áán zou T2 niet vuren: de trigger is -10% ten opzichte van entry,
#      en de vier open posities staan +9% tot +29%. De 80% van het budget die
#      voor T2-T4 gereserveerd staat, is dus geconditioneerd op ONGELIJK
#      hebben. Werkt de dip-buy-edge, dan komt dat geld nooit aan het werk.
#
# Netto stond 79% van het budget stil ($201 van $255, gemeten op de keten:
# xyz-dex accountValue $263,04 / withdrawable $202,34) terwijl het INGEZETTE
# deel +22,4% deed. Niet de edge was klein, de inzet was klein.
#
# Waarom 2 tranches en niet 4: het 4-stappenplan is getekend voor
# DEFAULT_BUDGET_USD ($1.250), waar elke stap ruim boven HL's $10-minimum
# uitkomt. Op $255 past het niet — 6 namen × 4 stappen vraagt 24 orders van
# >=$11 = $264 aan minimum-notional alleen al. Dus: minder stappen, grotere
# stappen. De binding is `budget / N * T1_pct >= 11`; bij N=6 en T1=0,60 wordt
# dat $25,50 (T2 $17,00) — beide ruim boven de vloer.
#
# Bij een groter budget kunnen de stappen terug: op $1.250 met 8 namen is
# {1:0,20 2:0,30 3:0,30 4:0,20} weer helemaal uitvoerbaar ($31/$47/$47/$31).
MAX_CONCURRENT_NAMES = 6
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
    # Overige indices (H100 = GPU-huurprijs-index, geen bedrijf)
    "H100",
})

# Crash-scoring drempels (tunable)
# Risico-guards (F0-gevalideerd 2026-07-24, zie feedback_sleeve_validation):
# de dip-buy-edge is echt maar regime-conditioneel + zonder downside-stop (46% van
# de posities ging >20% onder water). Twee guards: (1) sector-circuit-breaker
# pauzeert nieuwe dip-buys bij een STRUCTURELE sector-daling (>15% onder 60d-high;
# NIET de equity-uptrend-gate — die schaadt de mean-reversion-edge); (2) een
# per-positie downside-stop capt de tail. LET OP: de bear-bescherming is by-design,
# niet gebacktest (de ~10mnd data was volledig bull).
SLEEVE_CIRCUIT_BREAKER_DD_PCT = 15.0   # XYZ100 >dit% onder 60d-high -> pauzeer entries
SLEEVE_MAX_DRAWDOWN_STOP_PCT = 25.0    # sluit positie bij -dit% verlies (falling-knife cap)
SLEEVE_MIN_TRIM_NOTIONAL_USD = 10.0    # HL weigert orders <$10; daaronder tranche BEWAREN, niet verbranden

# ── winstbescherming bij kleine posities (2026-08-24) ──────────────────────
# De winstladder (25% afromen bij +30/+60/+100%) is bij dit budget onuitvoerbaar.
# HL weigert orders onder $10, dus 25% afromen vergt een positie van >=$40 bij
# +30% ($40 x 1,30 x 0,25 = $13). De posities zijn hier $16-28. Gemeten op
# 2026-08-24: CRCL stond +41% en NOW +34% en er was nog nooit een cent afgeroomd
# -- de +30%-sport had in het hele bestaan van de sleeve niet één keer gevuurd.
#
# Wat wél altijd kan is de trailing-stop aantrekken: dat vergt geen order en
# kent dus geen minimum. Hoe verder een winnaar liep, hoe minder hij van zijn
# piek mag teruggeven. Dezelfde vorm als de sl_stage-bevinding op de
# hoofd-swarm (stage 0 = 3,4% WR / -$236, stage 2 = profit-lock = 100% WR /
# +$246): alle P&L komt uit post-entry-beheer, niet uit de instap.
#
# De trims blijven staan en gaan vanzelf werken zodra het budget groeit; deze
# ladder is de bodem eronder, niet de vervanging.
SLEEVE_TRAIL_LADDER = ((100.0, 0.92), (60.0, 0.88), (30.0, 0.85))
SLEEVE_TRAIL_BASE = 0.80   # onder +30%: ongewijzigd t.o.v. de oude vaste regel

# ── meelopende winstbescherming (2026-08-25) ──────────────────────────────
# Vanaf +10% winst schuift de uitstap mee op 3 procentPUNT onder de hoogste
# stand die de positie ooit had. Op +14% ligt hij dus op +11%; loopt hij door
# naar +20%, dan schuift hij mee naar +17%.
#
# NIET te verwarren met SLEEVE_TRAIL_LADDER hierboven, die in PROCENT VAN DE
# PIEKWAARDE rekent (-20% van de piek). Deze rekent in procentPUNTEN winst en
# is dus veel strakker: bij +14% winst staat hij op +11%, niet op +11,2% van de
# waarde. Beide blijven staan; deze komt er eerder in de keten uit.
#
# Gemeten met scripts/sleeve_harness.py over 12 verschoven vensters, 180 dagen,
# uurresolutie (23,9 controles per dag -- de live-sleeve kijkt elke ~5 min, de
# oude naspeling keek eens per dag naar de slotkoers en dat gaf het TEGENGESTELDE
# antwoord):
#
#   huidige regels      mediaan $ -4,88   slechtste $-43,45    2/12 positief
#   vast uit op +6%     mediaan $+26,60   slechtste $ -2,05   10/12
#   meelopend 6% / 1pp  mediaan $+27,36   slechtste $ -8,63   11/12
#   meelopend 10% / 3pp mediaan $+62,76   slechtste $+16,82   12/12  <-- gekozen
#
# Waarom 3pp en niet 1pp: een krap gat wordt door gewone ruis uitgeschud, ook
# per uur. Waarom vanaf +10%: daaronder vuurt hij te vroeg op posities die nog
# niets bewezen hebben.
#
# BEPERKING VAN HET BEWIJS: 180 dagen, overlappende vensters, één universum, een
# grotendeels stijgende markt. En uur is nog steeds grover dan de ~5 minuten van
# productie. Beter onderbouwd dan de regels die het vervangt, geen zekerheid.
SLEEVE_PROFIT_TRAIL_START_PCT = 10.0   # vanaf deze winst loopt de bescherming mee
SLEEVE_PROFIT_TRAIL_GAP_PP = 3.0       # zoveel procentPUNT onder de hoogste stand

# Hoeveel er per winst-sport wordt afgeroomd. Stond drie keer los in de code;
# de regel hieronder rekent ermee, dus hij moet op één plek staan.
SLEEVE_PROFIT_TRIM_FRACTION = 0.25

# ── te kleine winnaar: helemaal dicht i.p.v. niets doen (2026-08-24) ───────
# De backtest die de edge onderbouwt (+5,66%/positie, 73 instappen) neemt aan
# dat de winstladder VUURT: `gain >= 30 -> 25% eraf`. Er zit geen
# minimum-notional in dat model. In productie is dat nog nooit gebeurd, dus de
# live sleeve draaide een ANDERE strategie dan de gevalideerde: alles
# vasthouden tot de trailing-stop.
#
# Voor nieuwe posities is dat opgelost met $42,50 per naam (25% bij +30% =
# $13,81, ruim boven de vloer). Blijven over: de posities die onder het oude,
# kleinere plan zijn geopend. Die kunnen hun sport per constructie niet halen
# en zouden hem eeuwig blijven overslaan.
#
# Regel: raakt zo'n positie zijn eerste winst-sport en is de afroming niet
# uitvoerbaar, dan gaat hij in zijn GEHEEL dicht. Het kapitaal komt terug op
# volle grootte en de volgende instap kan wél beheerd worden.
#
# Wat het kost, expliciet: het gevalideerde model laat 75% doorlopen na de
# sport. Deze regel kapt zo'n positie af op zijn sport, dus op een grote
# winnaar laat je geld liggen. Dat is bewust en begrensd — de regel raakt
# alleen ondermaatse posities en dooft zichzelf uit zodra die vervangen zijn.
#
# Bewust GEEN aan/uit-vlag: `t2_t4_enabled` stond op default False en heeft
# daardoor in het hele bestaan van de sleeve nooit gedraaid. Een schakelaar die
# niemand omzet is functioneel hetzelfde als geen code.

PULLBACK_VOL_THRESHOLD = 1.5   # vol-genormaliseerde "eenheden onder het 252d-high"
BREADTH_THRESHOLD = 0.30       # aandeel tickers in thema dat ook >= pullback-drempel scoort
STABILIZATION_LOOKBACK = 5     # dagen — laatste close mag niet op het 5d-low liggen

# Tranche-plan (fractie van het per-naam-budget). Moet optellen tot 1,0 en elke
# stap moet `budget / MAX_CONCURRENT_NAMES * pct >= min_notional + 1` halen,
# anders slaat _open_tranche hem stil over. Zie het blok bij
# MAX_CONCURRENT_NAMES voor waarom dit van 4 naar 2 stappen ging.
# ── 2026-08-24: 2 stappen -> 1. Alles in T1 ────────────────────────────────
# De vorige ronde (2026-08-12) verkleinde het plan van 4 naar 2 stappen omdat
# 79% van het budget stilstond. Dat hielp, maar loste de kern niet op: T2 vuurt
# op -10% t.o.v. entry, dus de reserve is geconditioneerd op ONGELIJK hebben.
# Werkt de dip-buy-edge, dan komt dat geld nooit aan het werk.
#
# En het was nog erger dan "geconditioneerd": `t2_t4_enabled` staat NIET in
# thematic_exposure_state.json en defaultt dus op False (zie
# _maybe_advance_tranches). T2 is sinds 2026-07-17 dry-run en heeft in het hele
# bestaan van de sleeve GEEN ENKELE keer gevuurd. De 40% was daarmee niet
# gereserveerd maar onbereikbaar — dood kapitaal in een reserve-jasje.
#
# Tweede gevolg, en dat is wat het echt brak: bij 6 namen en T1=60% is een
# positie $25,50, en 25% daarvan bij +30% is $8,29 — onder HL's $10-minimum.
# De winstladder kon dus per constructie niet vuren (CRCL stond +41% en NOW
# +34% zonder ooit een cent af te romen). Kleine posities zijn niet alleen
# zonde van het rendement, ze zijn ONBEHEERBAAR.
#
# Nu: 6 namen x $42,50, alles in T1. De afroming bij +30% wordt $13,81 en zit
# daarmee ruim boven de vloer; bij +60% en +100% helemaal. Volledige inzet,
# geen dode reserve, diversificatie ongewijzigd.
#
# Let op bij het terugzetten van meerdere stappen (kan prima bij een groter
# budget, zie het blok bij MAX_CONCURRENT_NAMES): T1 moet dan nog steeds
# `budget/N*T1_pct * 1,30 * 0,25 >= $10` halen, anders is de ladder weer stil.
# Bij $1.250 en 8 namen is dat geen enkel probleem.
TRANCHE_PCTS = {1: 1.0}
# Hoogste stap — nergens hardcoderen, anders loopt TRANCHE_PCTS[stage] op een
# KeyError zodra het plan korter wordt.
MAX_TRANCHE_STAGE = max(TRANCHE_PCTS)

# Executie-guards
# Prijs-sanity: primair vergelijken we de xyz-perp-mark met een VERSE intraday-
# referentie (strakke band). De daily yfinance-close loopt een sessie achter —
# een live-rally zet de perp legitiem 5-8% erboven, wat de oude 2%-vs-daily-close
# gate elke entry deed weigeren (sleeve ~3d flat, 2026-07-21). De daily-close
# blijft als fallback (verse intraday niet beschikbaar / FX-genoteerd) met een
# ruime glitch-band: alleen een echt kapotte mark (ordes van grootte) weren.
PRICE_SANITY_MAX_DEV_PCT = 2.0        # (legacy) niet meer gebruikt in de guard
PRICE_SANITY_INTRADAY_DEV_PCT = 3.0  # strakke band vs verse intraday-prijs
PRICE_SANITY_DAILY_DEV_PCT = 12.0    # ruime glitch-band vs stale daily-close (fallback)
PRICE_INTRADAY_TTL_S = 300           # verse intraday-referentie TTL (5 min)
FUNDING_ALERT_ANNUALIZED_PCT = 8.0

LEVERAGE = 1
MARGIN_MODE = "isolated"

# ── G0 meta-allocator: idle USDC -> xyz perp-dex sweep ──
# XYZ-synthetics handelen op de aparte "xyz" builder perp-dex met eigen collateral.
# USDC dat via HL "Send Tokens" of een treasury FUND_SLEEVE-transfer binnenkomt landt
# in spot (of de main-perp), niet op de xyz-dex. Deze sweep verplaatst dat idle geld
# met een sendAsset (HIP-3) automatisch naar de xyz-dex zodat het inzetbaar wordt.
# Werkt alleen op een SELF-CUSTODY wallet (de sleeve's eigen key = het account);
# op de gedeelde main-wallet (agent-key) verbiedt HL user-signed actions -> skip.
MIN_SWEEP_USD = 10.0                   # onder HL min-notional heeft sweepen geen zin
_SEND_ASSET_MAINNET_CHAINID = 42161    # Arbitrum One (EIP-712 domain chainId)
_SEND_ASSET_SIG_CHAIN_ID = "0xa4b1"    # matcht domain-chainId; HL mainnet
_SEND_ASSET_TYPES = {
    "HyperliquidTransaction:SendAsset": [
        {"name": "hyperliquidChain", "type": "string"},
        {"name": "destination", "type": "string"},
        {"name": "sourceDex", "type": "string"},
        {"name": "destinationDex", "type": "string"},
        {"name": "token", "type": "string"},
        {"name": "amount", "type": "string"},
        {"name": "fromSubAccount", "type": "string"},
        {"name": "nonce", "type": "uint64"},
    ],
}


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _finite(x, default=0.0):
    try:
        x = float(x)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _trail_fraction(peak_gain_pct: float) -> float:
    """Welk deel van de piekwaarde een winnaar mag behouden voor hij dichtgaat.

    Naar gelang hoe ver de positie ooit liep — niet hoe ver hij NU staat, want
    dan zou de bescherming weer losser worden zodra de koers terugzakt, precies
    op het moment dat je hem nodig hebt.
    """
    for drempel, frac in SLEEVE_TRAIL_LADDER:
        if peak_gain_pct >= drempel:
            return frac
    return SLEEVE_TRAIL_BASE


class ThematicExposureLab:
    def __init__(self, exchange_client=None):
        self.exchange_client = exchange_client
        self._llm = None
        self._self_custody = None      # cache: True/False of de sleeve-key == het account
        self._usdc_token = None        # cache: "USDC:0x..." token-id voor sendAsset

    # ── LLM ──────────────────────────────────────────────────────────────
    def _get_llm(self):
        if self._llm is None:
            try:
                from utils.llm_client import LLMClient
                self._llm = LLMClient()
            except Exception as e:
                logger.warning(f"ThematicExposureLab: LLM init mislukt ({e})")
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
            logger.debug(f"ThematicExposureLab: universe-scan mislukt: {e}")
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
                f"[ThematicExposureLab] Eerste scan: {len(new_tickers_raw)} tickers als baseline "
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

    @staticmethod
    def _yf_has_history(real_symbol: str) -> bool:
        """Check of Yahoo bruikbare daily-historie heeft voor dit symbool.
        De HL-tickercode is lang niet altijd een geldig Yahoo-symbool
        (SOFTBANK/KIOXIA/SMSN/… — Aziatische noteringen, of indices als
        H100): zonder deze check werd zo'n naam auto-CONFIRMED en bleef hij
        daarna onscoorbaar. Fail-open bij lib-/netwerkfouten: een kapotte
        check mag classificatie niet blokkeren."""
        yf_logger = logging.getLogger("yfinance")
        prev_level = yf_logger.level
        try:
            import yfinance as yf
            yf_logger.setLevel(logging.CRITICAL)
            df = yf.download(real_symbol, period="3mo", interval="1d", progress=False)
        except Exception:
            return True  # lib-/netwerkfout: fail-open
        finally:
            yf_logger.setLevel(prev_level)
        if df is None or getattr(df, "empty", True):
            return False  # onbekend symbool: yfinance geeft een lege frame terug
        try:
            return len(df["Close"].dropna()) >= 20
        except Exception:
            return False

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
                raw = llm.analyze_text(prompt, agent_name="ThematicExposureLab", thinking=False)
                cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
                m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if m:
                    parsed = json.loads(m.group())
                    if isinstance(parsed.get("themes"), dict):
                        proposal = parsed
            except Exception as e:
                logger.warning(f"ThematicExposureLab: classificatie van {ticker} mislukt: {e}")

        if proposal and proposal["themes"]:
            # Zonder Yahoo-prijshistorie kan een naam nooit scoren (en tot
            # 2026-07-17 verwaterde hij ook de thema-breadth) — dan heeft
            # CONFIRMED/PENDING_REVIEW geen zin. Voorstel bewaren zodat een
            # mens alleen real_symbol (+ evt. fx_symbol) hoeft te mappen.
            if not self._yf_has_history(real_symbol):
                themes.setdefault("tickers", {})[ticker] = {
                    "real_symbol": real_symbol, "themes": proposal["themes"], "status": "PENDING_MANUAL",
                    "note": ("LLM-voorstel bewaard, maar geen yfinance-historie voor dit symbool — "
                             "map real_symbol (+ evt. fx_symbol, bv. 'JPY=X') handmatig en zet daarna op CONFIRMED."),
                }
                logger.info(f"[ThematicExposureLab] {ticker}: geen yfinance-historie voor '{real_symbol}' — PENDING_MANUAL")
                return (ticker, "PENDING_MANUAL", {})
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
            logger.info(f"[ThematicExposureLab] {ticker}: {status} ({proposal['themes']})")
            return (ticker, status, proposal["themes"])
        else:
            themes.setdefault("tickers", {})[ticker] = {
                "real_symbol": real_symbol, "themes": {}, "status": "PENDING_MANUAL",
            }
            logger.info(f"[ThematicExposureLab] {ticker}: classificatie mislukt/leeg — PENDING_MANUAL")
            return (ticker, "PENDING_MANUAL", {})

    def _notify_classification_batch(self, results: list) -> None:
        """Eén samengevoegd bericht per cyclus i.p.v. één per ticker (bug
        2026-07-16: universum-classificatie stuurde tientallen losse pushes).
        PENDING_MANUAL (geen voorstel, niets om op te reageren) wordt alleen
        geteld, niet uitgeschreven — zichtbaar via /themelist, niet elke keer
        gepusht. CONFIRMED (auto, high confidence) wordt gemeld ter info, geen
        actie nodig. Plain text (geen parse_mode) — theme-ID's als 'ai_native'
        breken Telegram's Markdown-onderstrepingsparsing anders willekeurig."""
        auto_confirmed = [(t, th) for t, status, th in results if status == "CONFIRMED"]
        reviewable = [(t, th) for t, status, th in results if status == "PENDING_REVIEW"]
        manual_count = sum(1 for _, status, _ in results if status == "PENDING_MANUAL")
        if not auto_confirmed and not reviewable and not manual_count:
            return

        lines = [f"Thematic Exposure Sleeve — {len(results)} nieuwe ticker(s) gescand"]
        if auto_confirmed:
            lines.append("  Auto-CONFIRMED (high confidence, telt al mee):")
            for ticker, theme_weights in auto_confirmed:
                themes_str = ", ".join(f"{k} {v:.2f}" for k, v in theme_weights.items())
                lines.append(f"    {ticker} -> {themes_str}  (/themeignore {ticker} om terug te draaien)")
        for ticker, theme_weights in reviewable:
            themes_str = ", ".join(f"{k} {v:.2f}" for k, v in theme_weights.items())
            lines.append(f"  {ticker} -> {themes_str} (low confidence, review gewenst)")
            lines.append(f"    /themeapprove {ticker}  |  /themeedit {ticker} thema:gewicht  |  /themeignore {ticker}")
        if manual_count:
            lines.append(f"  + {manual_count} zonder voorstel (PENDING_MANUAL) — zie /themelist")
        self._notify_telegram("\n".join(lines), plain=True)

    # ── prijs-historie (yfinance) ────────────────────────────────────────
    def _fetch_price_history(self, symbol_specs: dict) -> dict:
        """Batched yfinance daily OHLC, ~24h TTL-cache.

        symbol_specs: {yf_symbol: fx_symbol_of_None}. Voor buitenlandse
        noteringen (bv. 9984.T + "JPY=X") worden de closes per dag naar USD
        omgerekend — HL's xyz-marks zijn de lokale koers gedeeld door de
        FX-koers (empirisch geverifieerd 2026-07-17), dus alleen USD-closes
        geven een kloppende drawdown-score én een werkende prijs-sanity-guard.

        Symbolen zonder bruikbare Yahoo-data gaan een TTL lang de NEGATIEVE
        cache in (price_cache_failed) — zonder die cache bleef `missing`
        permanent gevuld en werd de volledige 1y-batch elke run opnieuw
        opgehaald, met identieke yfinance-ERRORs (→ Telegram-spam) elke ~5 min.

        Returns {yf_symbol: {'closes': [USD-closes]}}."""
        state = self._load_state()
        cache = state.get("price_cache", {})
        now = time.time()
        ttl_s = PRICE_HISTORY_TTL_H * 3600
        failed = {s: ts for s, ts in state.get("price_cache_failed", {}).items() if now - ts < ttl_s}
        fresh = now - state.get("price_cache_ts", 0) < ttl_s
        missing = [s for s in symbol_specs if s not in cache and s not in failed]
        if fresh and not missing:
            return cache

        to_fetch = {s: fx for s, fx in symbol_specs.items() if s not in failed}
        if not to_fetch:
            return cache
        batch = sorted(set(to_fetch) | {fx for fx in to_fetch.values() if fx})

        # yfinance logt zelf op ERROR voor elk onbekend symbool; dat is hier
        # een verwachte, zelf-afgehandelde uitkomst (negatieve cache + eigen
        # WARNING) — geen ERROR-spam naar het Telegram-logkanaal.
        yf_logger = logging.getLogger("yfinance")
        prev_level = yf_logger.level
        try:
            import yfinance as yf
            yf_logger.setLevel(logging.CRITICAL)
            data = yf.download(
                tickers=" ".join(batch), period=PRICE_HISTORY_PERIOD, interval="1d",
                group_by="ticker", progress=False, threads=True,
            )
        except Exception as e:
            logger.warning(f"ThematicExposureLab: yfinance batch-fetch mislukt: {e}")
            return cache
        finally:
            yf_logger.setLevel(prev_level)

        def _close_series(sym):
            try:
                col = data[sym] if len(batch) > 1 else data
                series = col["Close"].dropna()
                return series if len(series) else None
            except Exception:
                return None

        new_cache = {}
        newly_failed = []
        for sym, fx_sym in to_fetch.items():
            series = _close_series(sym)
            if series is not None and fx_sym:
                fx = _close_series(fx_sym)
                # per-dag delen; pandas lijnt de datums uit, gaten vallen weg
                series = (series / fx).dropna() if fx is not None else None
            closes = [c for c in (series.tolist() if series is not None else [])
                      if math.isfinite(c) and c > 0]
            if len(closes) < 20:
                newly_failed.append(sym)
                failed[sym] = now
                continue
            new_cache[sym] = {"closes": closes[-260:]}

        if newly_failed:
            logger.warning(
                f"ThematicExposureLab: geen bruikbare Yahoo-historie voor {sorted(newly_failed)} — "
                f"{PRICE_HISTORY_TTL_H:.0f}h op de negatieve cache; fix real_symbol/fx_symbol in {THEMES_FILE}"
            )
        state["price_cache_failed"] = failed
        if new_cache:
            state["price_cache"] = new_cache
            state["price_cache_ts"] = now
        self._save_state(state)  # ook een louter-negatief resultaat persist maken
        return new_cache or cache  # fetch mislukt/leeg — val terug op oude cache i.p.v. alles te wissen

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
        """Per thema: aandeel MEETBARE tickers dat >= PULLBACK_VOL_THRESHOLD scoort.

        Noemer = alleen leden mét een score (dus met prijshistorie én
        voldoende volume). CONFIRMED leden zonder yfinance-historie telden
        eerst wel mee in de noemer maar konden nooit een hit worden — juist
        memory_storage (Samsung/SK Hynix/Kioxia) werd daardoor structureel
        onder de BREADTH_THRESHOLD gedrukt (bug 2026-07-17)."""
        breadth = {}
        for theme_id in themes_cfg.get("themes", {}):
            members = [
                t for t, cfg in themes_cfg.get("tickers", {}).items()
                if cfg.get("status") == "CONFIRMED" and theme_id in (cfg.get("themes") or {})
                and t in scores
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
            logger.debug(f"ThematicExposureLab: scoring-snapshot mislukt: {e}")
            return {}

        symbol_specs = {cfg["real_symbol"]: cfg.get("fx_symbol") for cfg in confirmed.values()}
        history = self._fetch_price_history(symbol_specs)

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

            # Divergentie-screen (PLAN_2026-08 par. 4): koopt de sleeve een dip
            # waarbij de fundamentals NIET meezakten, of een vallend mes? Tot nu
            # toe was de entry puur prijs (pullback_z), zonder enige toets op het
            # bedrijf erachter. Staat standaard in OBSERVATIEMODUS: de uitslag komt
            # in het rapport, maar blokkeert nog geen order — eerst bewijs, dan
            # handhaven (zelfde patroon als revalidation_autopause_enabled).
            if s["qualifies"]:
                try:
                    from utils.divergence_filter import beoordeel, handhaven
                    _ok, _reden, _ = beoordeel(ticker)
                    s["divergence_ok"] = _ok
                    s["divergence_reason"] = _reden
                    if not _ok:
                        if handhaven():
                            s["qualifies"] = False
                            logger.info(f"[SLEEVE] {ticker} GEBLOKKEERD door divergentie-screen: {_reden}")
                        else:
                            logger.info(f"[SLEEVE] {ticker} zou geblokkeerd zijn (observatiemodus): {_reden}")
                except Exception as e:
                    # Nooit de sleeve stilzetten op een storing in een extra screen.
                    s["divergence_ok"] = None
                    s["divergence_reason"] = f"filter faalde: {e}"
                    logger.debug(f"divergentie-screen faalde voor {ticker}: {e}")

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
        if stage not in TRANCHE_PCTS:
            return False  # stap bestaat niet in het huidige (kortere) plan
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
    @staticmethod
    def _sleeve_entries_enabled() -> bool:
        """Master-schakelaar voor nieuwe sleeve-entries (default True). De
        sleeve-re-validatie zet dit op False bij edge-verval (de-risk). Bestaande
        posities blijven altijd beheerd (exits/stops draaien door)."""
        try:
            with open("config/auto_params.json") as f:
                v = json.load(f).get("sleeve_entries_enabled", True)
                return bool(v) if v is not None else True
        except Exception:
            return True

    def _maybe_advance_tranches(self, report: dict) -> None:
        if self.exchange_client is None:
            logger.warning("ThematicExposureLab: exchange_client is None — T1 execution disabled")
            return
        positions = self._load_positions()
        themes_cfg = self._load_themes()
        t2_t4_enabled = self._load_state().get("t2_t4_enabled", False)

        open_tickers = {t for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}

        # Nieuwe T1's — altijd live vanaf dag 1, ongeacht t2_t4_enabled.
        qualifying = [t for t in report.get("qualifying", []) if t not in open_tickers]
        n_slots = max(0, MAX_CONCURRENT_NAMES - len(open_tickers))
        if qualifying:
            logger.info(f"ThematicExposureLab: qualifying={qualifying} n_slots={n_slots} open_tickers={sorted(open_tickers)}")

        # Sleeve-re-validatie kan entries autonoom pauzeren bij edge-verval (de-risk).
        if n_slots > 0 and not self._sleeve_entries_enabled():
            if qualifying:
                logger.warning("ThematicExposureLab: sleeve_entries_enabled=False (re-validatie de-risk) → nieuwe dip-buys gepauzeerd")
            n_slots = 0

        # Sector-circuit-breaker: pauzeer NIEUWE dip-buys bij een structurele sector-
        # daling. Bestaande posities blijven gewoon beheerd (exits/stops draaien door).
        try:
            from core.equity_regime import sector_drawdown_pct
            _dd = sector_drawdown_pct()
            if n_slots > 0 and _dd >= SLEEVE_CIRCUIT_BREAKER_DD_PCT:
                if qualifying:
                    logger.warning(f"ThematicExposureLab: SECTOR-CIRCUIT-BREAKER — XYZ100 {_dd:.1f}% "
                                   f"onder 60d-high (>= {SLEEVE_CIRCUIT_BREAKER_DD_PCT:.0f}%) → nieuwe dip-buys gepauzeerd")
                n_slots = 0
        except Exception as e:
            logger.debug(f"ThematicExposureLab: circuit-breaker-check overgeslagen: {e}")

        for ticker in qualifying[:n_slots]:
            self._open_tranche(ticker, 1, themes_cfg, positions, report)

        if not t2_t4_enabled:
            return  # T2-T4 blijft dry-run — zie _t2_t4_preview() in daily_status_text()

        for ticker in list(open_tickers):
            pos = positions.get("positions", {}).get(ticker)
            if not pos or pos.get("tranche_stage", 1) >= MAX_TRANCHE_STAGE:
                continue
            s = report.get("scores", {}).get(ticker)
            if not s:
                continue
            next_stage = pos["tranche_stage"] + 1
            if self._tranche_trigger(next_stage, s, pos):
                self._open_tranche(ticker, next_stage, themes_cfg, positions, report)

    @staticmethod
    def _hl_symbol(ticker: str) -> str:
        """Ticker keys in this module are bare (e.g. 'XYZ-NVDA'); exchange_client's
        _normalize_symbol() expects ccxt-style 'XYZ-NVDA/USDC' — without the quote
        suffix every lookup misses and get_market_price()/create_order() report the
        ticker as "not listed", even though it trades fine (2026-07-17: silently
        blocked every T1 execution since the sleeve launched 2026-07-16)."""
        return ticker if "/" in ticker else f"{ticker}/USDC"

    def _sanity_reference(self, real_symbol: str, fx_symbol: str | None):
        """Referentieprijs voor de mark-sanity-guard.

        Retourneert (price, kind, tolerance_pct):
          - ('intraday', strakke band) — verse yfinance last_price (5min TTL-cache,
            FX-genoteerde namen naar USD omgerekend via de FX last_price).
          - ('yf-close', ruime band) — laatste daily-close uit price_cache; puur
            een glitch-vangnet als de intraday-fetch faalt.
          - (None, ...) als geen enkele referentie beschikbaar is → guard slaat over.
        """
        state = self._load_state()
        cache = state.get("intraday_ref", {})
        now = time.time()
        cached = cache.get(real_symbol)
        if cached and now - cached.get("ts", 0) < PRICE_INTRADAY_TTL_S:
            px = _finite(cached.get("px"))
            if px > 0:
                return px, "intraday", PRICE_SANITY_INTRADAY_DEV_PCT

        px = self._fetch_intraday_price(real_symbol, fx_symbol)
        if px and px > 0:
            cache[real_symbol] = {"px": px, "ts": now}
            state["intraday_ref"] = cache
            self._save_state(state)
            return px, "intraday", PRICE_SANITY_INTRADAY_DEV_PCT

        # Fallback: stale daily-close, ruime glitch-band.
        hist = state.get("price_cache", {}).get(real_symbol)
        if hist and hist.get("closes"):
            last_close = _finite(hist["closes"][-1])
            if last_close > 0:
                return last_close, "yf-close", PRICE_SANITY_DAILY_DEV_PCT
        return None, "", PRICE_SANITY_DAILY_DEV_PCT

    @staticmethod
    def _fetch_intraday_price(real_symbol: str, fx_symbol: str | None) -> float:
        """Verse last_price via yfinance fast_info; FX-genoteerd naar USD gedeeld.
        Faalt stil (0.0) — de caller valt dan terug op de daily-close."""
        yf_logger = logging.getLogger("yfinance")
        prev_level = yf_logger.level
        try:
            import yfinance as yf
            yf_logger.setLevel(logging.CRITICAL)

            def _last(sym: str) -> float:
                try:
                    fi = yf.Ticker(sym).fast_info
                    return _finite(fi.get("last_price") or fi.get("lastPrice"))
                except Exception:
                    return 0.0

            px = _last(real_symbol)
            if px <= 0:
                return 0.0
            if fx_symbol:
                fx = _last(fx_symbol)
                if fx <= 0:
                    return 0.0  # geen verse FX → laat fallback het overnemen
                px = px / fx
            return px if px > 0 else 0.0
        except Exception as e:
            logger.debug(f"ThematicExposureLab: intraday-prijs mislukt voor {real_symbol}: {e}")
            return 0.0
        finally:
            yf_logger.setLevel(prev_level)

    @staticmethod
    def _divergence_stempel(ticker: str) -> dict:
        """Het oordeel van de divergentie-screen op het moment van aankoop.

        Waarom vastleggen en niet later opnieuw berekenen: de kwartaalcijfers
        veranderen. Wie over een half jaar wil weten of de filter had moeten
        handhaven, heeft het verdict NAAST de uitkomst nodig — achteraf opnieuw
        meten geeft het oordeel van vandaag over een aankoop van toen.

        Faalt de filter, dan blijft de positie gewoon doorgaan; dit is een
        meetstempel, geen poort.
        """
        try:
            from utils.divergence_filter import beoordeel
            ok, reden, meting = beoordeel(ticker)
            return {"divergence_at_entry": {"ok": ok, "reden": reden, "meting": meting}}
        except Exception as e:
            return {"divergence_at_entry": {"ok": None, "reden": f"filter faalde: {e}",
                                            "meting": None}}

    def _open_tranche(self, ticker: str, stage: int, themes_cfg: dict, positions: dict, report: dict) -> None:
        from core.strategy_logic import detect_asset_class
        from agents.xyz_technical_analyst import _market_is_open

        # Guard (a): markt-uren — XYZ-synthetics drijven buiten beurstijd zonder
        # verse prijsontdekking (zie shadow_xyz_lab's open-gap-tracker).
        asset_class = detect_asset_class(ticker)
        if not _market_is_open(asset_class, datetime.now(timezone.utc)):
            logger.debug(f"ThematicExposureLab: {ticker} markt gesloten (asset_class={asset_class}) — T{stage} uitgesteld")
            return

        if stage not in TRANCHE_PCTS:
            logger.warning(f"ThematicExposureLab: T{stage} bestaat niet in het tranche-plan "
                           f"{sorted(TRANCHE_PCTS)} — {ticker} overgeslagen")
            return

        budget = _finite(positions.get("budget_usd"), DEFAULT_BUDGET_USD)
        cash = _finite(positions.get("cash_usd"), budget)
        per_name_budget = budget / MAX_CONCURRENT_NAMES
        tranche_usd = per_name_budget * TRANCHE_PCTS[stage]
        if tranche_usd > cash:
            logger.info(f"ThematicExposureLab: onvoldoende cash voor T{stage} {ticker} (${tranche_usd:.2f} > ${cash:.2f})")
            return

        try:
            mark_price = self.exchange_client.get_market_price(self._hl_symbol(ticker))
        except Exception as e:
            logger.warning(f"ThematicExposureLab: prijs ophalen mislukt voor {ticker}: {e}")
            return
        mark_price = _finite(mark_price)
        if mark_price <= 0:
            return

        # Guard (b): prijs-sanity — verse intraday-referentie (strak), met
        # daily-close als ruime glitch-fallback (zie constants-blok).
        tcfg = themes_cfg.get("tickers", {}).get(ticker, {})
        real_symbol = tcfg.get("real_symbol", ticker.split("-", 1)[-1])
        fx_symbol = tcfg.get("fx_symbol")
        ref_price, ref_kind, ref_tol = self._sanity_reference(real_symbol, fx_symbol)
        if ref_price and ref_price > 0:
            dev = abs(mark_price - ref_price) / ref_price * 100
            if dev > ref_tol:
                logger.warning(
                    f"ThematicExposureLab: prijs-sanity-check faalt voor {ticker} "
                    f"(mark={mark_price:.2f} vs {ref_kind}={ref_price:.2f}, "
                    f"dev={dev:.1f}% > {ref_tol:.0f}%) — order overgeslagen"
                )
                return

        # Guard: min-notional — bewuste skip i.p.v. structurele basket-wijziging
        try:
            min_notional = self.exchange_client.get_min_notional(self._hl_symbol(ticker)) or 10.0
        except Exception:
            min_notional = 10.0
        if tranche_usd < min_notional + 1.0:
            logger.info(f"ThematicExposureLab: T{stage} voor {ticker} (${tranche_usd:.2f}) onder min-notional — overgeslagen")
            return

        precision = 0.0
        try:
            precision = self.exchange_client.get_amount_precision(self._hl_symbol(ticker)) or 0.0
        except Exception:
            pass
        quantity = tranche_usd / mark_price
        if precision > 0:
            quantity = math.floor(quantity / precision) * precision
        if quantity <= 0:
            return

        order = self.exchange_client.create_order(
            self._hl_symbol(ticker), "BUY", quantity, order_type="market",
            leverage=LEVERAGE, margin_mode=MARGIN_MODE,
        )
        if order is None:
            logger.warning(f"ThematicExposureLab: T{stage}-order voor {ticker} mislukt (exchange gaf None terug)")
            return

        notional_usd = quantity * mark_price
        self._record_open_or_add(positions, ticker, stage, themes_cfg, quantity, mark_price, notional_usd)
        self._append_trade_log(ticker, quantity, mark_price, notional_usd)
        self._notify_telegram(
            f"🟢 *Thematic Exposure Sleeve — T{stage} {'geopend' if stage == 1 else 'bijgekocht'}*\n"
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
                # Wat vond de divergentie-screen hiervan bij AANKOOP? Vastleggen op
                # het moment zelf, want over drie maanden zijn de kwartaalcijfers
                # anders en is niet meer te reconstrueren wat hij toen zag.
                # Dit is de meting die beslist of de filter ooit mag handhaven:
                # zonder verdict-bij-entry naast de uitkomst is dat een gok.
                **self._divergence_stempel(ticker),
            }
        positions["cash_usd"] = _finite(positions.get("cash_usd"), positions.get("budget_usd", DEFAULT_BUDGET_USD)) - notional_usd
        positions.setdefault("budget_usd", DEFAULT_BUDGET_USD)
        self._save_positions(positions)

    def _append_trade_log(self, ticker: str, quantity: float, price: float, notional_usd: float) -> None:
        """Schrijft een OPEN-record in trade_log.json, getagd 'thematic_exposure': True
        zodat de auditor/weight-learning-loop deze trade negeert (zelfde patroon
        als 'harvest': True — zie agents/execution_agent.py + strategy_manager.py guards).

        ticker field uses _hl_symbol() (ccxt "XYZ-NVDA/USDC" form), not this module's
        bare internal format — ProjectLead's duplicate-position guard
        (project_lead.py ~1097-1110) string-matches trade_log.json's ticker field
        against its own "TICKER/USDC" tickers to skip trading an asset it's already
        in. Before this, that guard silently never matched thematic-exposure
        positions, so the council could open a conflicting/stacking order on the
        same Hyperliquid market — and since leverage/margin-mode is a per-market
        account setting (not per-order), that could silently flip this sleeve's
        fixed 1x isolated position to whatever the council's order used (2026-07-17)."""
        try:
            with open("trade_log.json") as f:
                log = json.load(f)
        except Exception:
            log = []
        log.append({
            "id": f"THEMATIC_EXPOSURE_{ticker}_{int(time.time())}",
            "ticker": self._hl_symbol(ticker),
            "action": "BUY",
            "quantity": quantity,
            "entry_price": price,
            "size_usd": notional_usd,
            "entry_time": time.time(),
            "status": "OPEN",
            "pnl": 0.0,
            "analyst_signals": {},
            "thematic_exposure": True,
        })
        try:
            with open("trade_log.json", "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"trade_log.json schrijven mislukt (thematic_exposure open): {e}")

    def _close_trade_log(self, ticker: str, price: float, pnl: float) -> None:
        try:
            with open("trade_log.json") as f:
                log = json.load(f)
        except Exception:
            return
        hl_ticker = self._hl_symbol(ticker)
        for t in log:
            if t.get("ticker") == hl_ticker and t.get("status") == "OPEN" and t.get("thematic_exposure"):
                t["status"] = "CLOSED"
                t["exit_price"] = price
                t["pnl"] = pnl
                t["exit_time"] = _now_iso()
                break
        try:
            with open("trade_log.json", "w") as f:
                json.dump(log, f, indent=1)
        except Exception as e:
            logger.error(f"trade_log.json schrijven mislukt (thematic_exposure close): {e}")

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
                mark = self.exchange_client.get_market_price(self._hl_symbol(ticker))
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

            # Piekwinst in PROCENTEN, prijs-gebaseerd. Bewust niet elke keer
            # afgeleid uit peak_value/cost_basis: die twee verschuiven allebei
            # bij een bijkoop of een deelexit, de prijsverhouding niet.
            if pos.get("peak_gain_pct") is None and _finite(pos.get("cost_basis_usd")) > 0:
                # Eerste keer: leid hem af uit de bestaande piekwaarde. Dat is
                # exact zolang er niet is bijgekocht of getrimd — en dat is bij
                # geen enkele positie gebeurd (gemeten 2026-08-24).
                pos["peak_gain_pct"] = (_finite(pos.get("peak_value_usd"))
                                        / pos["cost_basis_usd"] - 1) * 100
            pos["peak_gain_pct"] = max(_finite(pos.get("peak_gain_pct")), gain_pct)
            trail = _trail_fraction(pos["peak_gain_pct"])

            exit_reason, exit_fraction, tranche_vlag = None, 0.0, None
            # Downside-stop (falling-knife cap): sluit volledig bij een groot verlies.
            # De sleeve had voorheen GEEN downside-stop → posities konden oneindig
            # zakken (46% ging >20% onder water, ergste −44%). Capt de single-position
            # tail; backtest: minimale edge-kost, worst −44%→−33%.
            if gain_pct <= -SLEEVE_MAX_DRAWDOWN_STOP_PCT:
                exit_reason, exit_fraction = f"downside-stop {SLEEVE_MAX_DRAWDOWN_STOP_PCT:.0f}%", 1.0
            elif (pos["peak_gain_pct"] >= SLEEVE_PROFIT_TRAIL_START_PCT
                  and gain_pct <= (pos["peak_gain_pct"]
                                   - SLEEVE_PROFIT_TRAIL_GAP_PP + 1e-9)):
                # Meelopende winstbescherming — zie het constants-blok. Staat
                # bewust VOOR de winst-sporten: hij vervangt ze functioneel,
                # want een positie haalt +30% zelden nog als hij al 3pp is
                # teruggevallen vanaf een piek boven +10%.
                #
                # De 1e-9 is geen slordigheid maar een drijvende-komma-rand: bij
                # een piek van 10,0% en een koers op exact +7,0% komt gain_pct
                # uit op 7.000000000000001, en dan is `<= 7.0` onwaar. In
                # productie vuurt hij vijf minuten later alsnog, maar een grens
                # die niet doet wat de documentatie zegt is precies het soort
                # stille afwijking dat hier vaker geld heeft gekost.
                exit_reason, exit_fraction = (
                    "meelopende winstbescherming: piek stond op +%.1f%%, nu +%.1f%% "
                    "(%.1fpp terugval)"
                    % (pos["peak_gain_pct"], gain_pct,
                       pos["peak_gain_pct"] - gain_pct), 1.0)
            elif gain_pct >= 100 and not pos.get("profit_tranche_3_done"):
                exit_reason = "winst-tranche +100%"
                exit_fraction = SLEEVE_PROFIT_TRIM_FRACTION
                tranche_vlag = "profit_tranche_3_done"
            elif gain_pct >= 60 and not pos.get("profit_tranche_2_done"):
                exit_reason = "winst-tranche +60%"
                exit_fraction = SLEEVE_PROFIT_TRIM_FRACTION
                tranche_vlag = "profit_tranche_2_done"
            elif gain_pct >= 30 and not pos.get("profit_tranche_1_done"):
                exit_reason = "winst-tranche +30%"
                exit_fraction = SLEEVE_PROFIT_TRIM_FRACTION
                tranche_vlag = "profit_tranche_1_done"
            elif gain_pct > 0 and pos["current_value_usd"] < pos["peak_value_usd"] * trail:
                exit_reason, exit_fraction = (
                    "NAV-trailing-stop -%.0f%% (piek stond op +%.0f%%)"
                    % ((1 - trail) * 100, pos["peak_gain_pct"]), 1.0)

            # Te kleine winnaar -> helemaal dicht in plaats van eeuwig overslaan.
            # Zie het constants-blok bij SLEEVE_PROFIT_TRIM_FRACTION voor het
            # waarom. Alleen op winst-sporten (tranche_vlag gezet): een
            # downside-stop en een trailing-stop sluiten al volledig.
            if tranche_vlag and (pos["current_value_usd"] * exit_fraction
                                 < SLEEVE_MIN_TRIM_NOTIONAL_USD):
                exit_reason = (
                    "%s — positie te klein om %.0f%% af te romen ($%.2f < $%.0f), "
                    "dus volledig gesloten"
                    % (exit_reason, exit_fraction * 100,
                       pos["current_value_usd"] * exit_fraction,
                       SLEEVE_MIN_TRIM_NOTIONAL_USD))
                exit_fraction, tranche_vlag = 1.0, None

            if exit_reason:
                # De vlag wordt pas gezet als de verkoop ECHT is gelukt. Stond hij
                # eerder vóór de order, dan verbrandde een mislukte order de tranche
                # permanent: XYZ-CRCL en XYZ-NOW stonden allebei op +30% met
                # profit_tranche_1_done=true en een onaangeroerde positie, omdat 25%
                # van ~$16 onder HL's $10-minimum lag (gevonden 2026-08-20).
                if self._close_or_trim(positions, ticker, pos, mark,
                                       exit_fraction, exit_reason) and tranche_vlag:
                    pos[tranche_vlag] = True

        if changed:
            self._save_positions(positions)

    def _close_or_trim(self, positions: dict, ticker: str, pos: dict, mark: float,
                        fraction: float, reason: str) -> bool:
        """Verkoopt (een deel van) een positie. True = er is echt verkocht.

        De aanroeper mag een winst-tranche pas afvinken op True. Een deelexit die
        onder Hyperliquid's $10-minimum uitkomt is namelijk geen fout maar een te
        kleine positie — die tranche hoort BEWAARD te blijven tot de positie groot
        genoeg is, niet verbrand te worden.
        """
        qty_to_sell = pos["quantity"] * fraction
        precision = 0.0
        try:
            precision = self.exchange_client.get_amount_precision(self._hl_symbol(ticker)) or 0.0
        except Exception:
            pass
        if precision > 0:
            qty_to_sell = math.floor(qty_to_sell / precision) * precision
        if qty_to_sell <= 0:
            return False

        # HL weigert alles onder $10. Bij een DEELexit is doorzetten zinloos: de
        # order faalt gegarandeerd. Sla hem over zodat de tranche behouden blijft.
        # Een VOLLEDIGE sluiting (fraction 1.0) proberen we wel altijd — daar is
        # niets te bewaren en een dust-positie moet hoe dan ook weg.
        notional = qty_to_sell * mark
        if fraction < 1.0 and notional < SLEEVE_MIN_TRIM_NOTIONAL_USD:
            logger.info(
                "ThematicExposureLab: %s overgeslagen voor %s — $%.2f onder het "
                "$%.0f-minimum van Hyperliquid; tranche blijft staan tot de positie "
                "groot genoeg is.", reason, ticker, notional, SLEEVE_MIN_TRIM_NOTIONAL_USD)
            return False

        order = self.exchange_client.create_order(
            self._hl_symbol(ticker), "SELL", qty_to_sell, order_type="market",
            leverage=LEVERAGE, margin_mode=MARGIN_MODE,
        )
        if order is None:
            logger.warning(f"ThematicExposureLab: exit-order voor {ticker} mislukt ({reason})")
            return False

        proceeds = qty_to_sell * mark
        cost_basis_sold = pos["avg_entry_price"] * qty_to_sell
        realized_pnl = proceeds - cost_basis_sold

        qty_voor = pos["quantity"]
        pos["quantity"] -= qty_to_sell
        pos["cost_basis_usd"] = pos["avg_entry_price"] * pos["quantity"]
        pos["current_value_usd"] = pos["quantity"] * mark

        # De piekwaarde hoort bij de positie die er WAS; schaal hem mee met wat
        # er verkocht is. Zonder dit staat de trailing-stop na elke deelexit
        # gegarandeerd onder water — niet soms, altijd: na een trim van 25% is
        # de waarde 0,75 x de waarde van dat moment, en die was per definitie
        # hoogstens de piek, dus 0,75 x waarde < 0,80 x piek klopt zonder
        # uitzondering. De eerstvolgende cyclus zou dan de hele winnaar
        # liquideren onder de noemer "trailing-stop". Gevonden 2026-08-24 en
        # nooit opgemerkt, juist omdat de winst-tranches door het $10-minimum
        # nog geen enkele keer gevuurd hadden. Deel op de FEITELIJK verkochte
        # hoeveelheid, niet op de gevraagde fractie: precision-afronding
        # hierboven verandert die.
        if qty_voor > 0:
            pos["peak_value_usd"] = (_finite(pos.get("peak_value_usd"))
                                     * (1.0 - qty_to_sell / qty_voor))
        positions["cash_usd"] = _finite(positions.get("cash_usd")) + proceeds
        positions["realized_pnl_usd"] = _finite(positions.get("realized_pnl_usd")) + realized_pnl

        # Ook PER POSITIE bijhouden, niet alleen in de totaalpost. Zonder dit is
        # een gesloten positie na afloop niet meer te beoordelen: quantity en
        # cost_basis gaan naar 0 en het resultaat verdwijnt in één som. Daarmee
        # was geen enkele evaluatie per naam mogelijk — ook niet of de
        # divergentie-screen had moeten handhaven.
        pos["realized_pnl_usd"] = _finite(pos.get("realized_pnl_usd")) + realized_pnl
        pos["entry_cost_basis_usd"] = _finite(pos.get("entry_cost_basis_usd")) + cost_basis_sold

        full_close = pos["quantity"] <= max(precision, 1e-6)
        if full_close:
            pos["status"] = "CLOSED"
            pos["closed_at"] = _now_iso()
            self._close_trade_log(ticker, mark, realized_pnl)
        # bij een gedeeltelijke exit blijft de OPEN trade_log-entry staan — de
        # oorspronkelijke BUY-entry_price/quantity representeren dan de resterende
        # kernpositie niet meer exact, maar trade_log wordt hier uitsluitend voor
        # de auditor-isolatie gebruikt (zie guards), niet voor P&L-rapportage —
        # die leest thematic_exposure_positions.json.

        self._save_positions(positions)
        self._notify_telegram(
            f"🔴 *Thematic Exposure Sleeve — exit*\n{ticker} — {reason}\n"
            f"{qty_to_sell:.4f} @ ${mark:.2f} — gerealiseerd: ${realized_pnl:+.2f}"
            f"{' (volledig gesloten)' if full_close else ''}"
        )
        return True

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

    # ── Vervolgtranche dry-run preview (zolang t2_t4_enabled=false) ──────────
    # LET OP: deze preview heeft in het hele bestaan van de sleeve nooit een
    # regel opgeleverd, en dat is géén bewijs dat de tranches goed staan — de
    # trigger vraagt -10% t.o.v. entry en alle posities stonden in de plus. Een
    # lege preview betekent hier "niet van toepassing", niet "gecontroleerd".
    def _t2_t4_preview(self, report: dict, positions: dict) -> list:
        preview = []
        if self._load_state().get("t2_t4_enabled", False):
            return preview  # dan is het geen preview meer — het gebeurt al echt
        for ticker, pos in positions.get("positions", {}).items():
            if pos.get("status") != "OPEN" or pos.get("tranche_stage", 1) >= MAX_TRANCHE_STAGE:
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
            logger.info(f"ThematicExposureLab (geen Telegram):\n{text}")
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
                logger.warning(f"ThematicExposureLab: Telegram send mislukt (mode={parse_mode}): {e}")

    # ── dagelijkse status (aangehaakt in de sleeve_nav-digest) ──────────────
    def daily_status_text(self) -> str:
        try:
            with open(REPORT_FILE) as f:
                report = json.load(f)
        except Exception:
            report = {}
        positions = self._load_positions()
        open_positions = {t: p for t, p in positions.get("positions", {}).items() if p.get("status") == "OPEN"}

        lines = ["", "🧠 *Thematic Exposure Sleeve (EXP-008)*"]
        active_themes = [t for t, b in (report.get("breadth_by_theme") or {}).items() if b >= BREADTH_THRESHOLD]
        lines.append(f"  Actieve thema's: {', '.join(active_themes) if active_themes else 'geen'}")
        lines.append(f"  Open T1-posities: {len(open_positions)}/{MAX_CONCURRENT_NAMES}")
        if open_positions:
            total_value = sum(_finite(p.get("current_value_usd")) for p in open_positions.values())
            total_cost = sum(_finite(p.get("cost_basis_usd")) for p in open_positions.values())
            lines.append(f"  Waarde: ${total_value:,.2f} | ongerealiseerd: ${total_value - total_cost:+,.2f}")
        lines.append(f"  Vrij budget: ${_finite(positions.get('cash_usd')):,.2f}")

        # Winnaars: welke bescherming staat er, en is de winstladder bruikbaar?
        # Die laatste vraag stond drie maanden onbeantwoord omdat een overgeslagen
        # tranche alleen een INFO-regel in de logs achterliet.
        winnaars, inert = [], []
        for t, p in open_positions.items():
            piek = _finite(p.get("peak_gain_pct"))
            if piek < SLEEVE_TRAIL_LADDER[-1][0]:
                continue
            trail = _trail_fraction(piek)
            winnaars.append("%s piek +%.0f%% → stop -%.0f%%" % (t, piek, (1 - trail) * 100))
            # 25% van de huidige waarde: haalt die het HL-minimum?
            if _finite(p.get("current_value_usd")) * 0.25 < SLEEVE_MIN_TRIM_NOTIONAL_USD:
                inert.append(t)
        if winnaars:
            lines.append(f"  Winstbescherming: {'; '.join(winnaars)}")
        if inert:
            lines.append(
                f"  ℹ️ Winstladder nog onbruikbaar bij {', '.join(inert)} — 25% blijft "
                f"onder HL's ${SLEEVE_MIN_TRIM_NOTIONAL_USD:.0f}; de trailing-stop doet het werk")
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
        # Idle USDC (spot/main-perp) naar de xyz-dex zodat gestort/toegewezen
        # kapitaal inzetbaar wordt, VÓÓR de entry-poging in _maybe_advance_tranches.
        self._sweep_idle_to_xyz()
        if report:
            self._maybe_advance_tranches(report)

    # ── G0 meta-allocator: idle USDC -> xyz-dex ──────────────────────────
    def _is_self_custody(self, client, address: str) -> bool:
        """True als de signing-key naar het account zelf derivt (geen agent-wallet).
        Alleen dan mag HL user-signed actions (sendAsset). Resultaat gecachet."""
        if self._self_custody is not None:
            return self._self_custody
        self._self_custody = False
        try:
            from eth_account import Account
            pk = getattr(client, "privateKey", None)
            if pk:
                signer = Account.from_key(pk).address
                self._self_custody = signer.lower() == address.lower()
        except Exception as e:
            logger.debug(f"ThematicExposureLab: self-custody-check faalde: {e}")
        return self._self_custody

    def _usdc_token_id(self, client) -> str | None:
        if self._usdc_token:
            return self._usdc_token
        try:
            meta = client.publicPostInfo({"type": "spotMeta"})
            for tok in meta.get("tokens", []) or []:
                if (tok.get("name") or "").upper() == "USDC":
                    tid = tok.get("tokenId")
                    if tid:
                        self._usdc_token = f"USDC:{tid}"
                        return self._usdc_token
        except Exception as e:
            logger.debug(f"ThematicExposureLab: USDC token-id resolve faalde: {e}")
        return None

    @staticmethod
    def _idle_usdc(client, address: str, src: str) -> float:
        """Beschikbaar USDC op een bron: 'spot' = spot-USDC totaal, '' = main-perp
        withdrawable (de sleeve opent nooit main-dex-posities, dus dit is idle)."""
        try:
            if src == "spot":
                s = client.publicPostInfo({"type": "spotClearinghouseState", "user": address})
                for b in s.get("balances", []) or []:
                    if b.get("coin") == "USDC":
                        return _finite(b.get("total"))
                return 0.0
            r = client.publicPostInfo({"type": "clearinghouseState", "user": address})
            return _finite(r.get("withdrawable"))
        except Exception:
            return 0.0

    def _send_asset_to_xyz(self, client, address: str, amount: float, src: str) -> bool:
        token = self._usdc_token_id(client)
        if not token:
            return False
        nonce = client.milliseconds()
        str_amount = client.number_to_string(amount)
        message = {
            "hyperliquidChain": "Mainnet", "destination": address,
            "sourceDex": src, "destinationDex": "xyz", "token": token,
            "amount": str_amount, "fromSubAccount": "", "nonce": nonce,
        }
        # Zelf signen: ccxt's sign_user_signed_action hardcodet de testnet-chainId
        # (421614) -> HL weigert met "Mainnet and testnet require different signature".
        domain = {
            "chainId": _SEND_ASSET_MAINNET_CHAINID, "name": "HyperliquidSignTransaction",
            "verifyingContract": "0x0000000000000000000000000000000000000000", "version": "1",
        }
        enc = client.eth_encode_structured_data(domain, _SEND_ASSET_TYPES, message)
        signature = client.sign_message(enc, client.privateKey)
        request = {
            "action": {
                "type": "sendAsset", "signatureChainId": _SEND_ASSET_SIG_CHAIN_ID,
                "hyperliquidChain": "Mainnet", "destination": address,
                "sourceDex": src, "destinationDex": "xyz", "token": token,
                "amount": str_amount, "fromSubAccount": "", "nonce": nonce,
            },
            "nonce": nonce, "signature": signature,
        }
        resp = client.private_post_exchange(request)
        return isinstance(resp, dict) and resp.get("status") == "ok"

    def _sweep_idle_to_xyz(self) -> None:
        ex = self.exchange_client
        client = getattr(ex, "signing_client", None)
        if client is None:
            return
        address = getattr(client, "walletAddress", None) or getattr(ex, "wallet_address", None)
        if not address or not self._is_self_custody(client, address):
            return
        # Alleen vanuit spot: de wallet is een unified account, en HL staat sends
        # enkel "through spot" toe (sendAsset vanuit de perp-dex → "only supports
        # sending assets through spot"). Gestort/toegewezen kapitaal landt sowieso
        # in spot, dus dat dekt alle funding-paden.
        try:
            raw = self._idle_usdc(client, address, "spot")
            amount = math.floor(raw * 100) / 100  # 2 decimalen, niet overschrijden
            if amount < MIN_SWEEP_USD:
                return
            if self._send_asset_to_xyz(client, address, amount, "spot"):
                logger.info(f"ThematicExposureLab: ${amount:.2f} spot -> xyz-dex geswept")
            else:
                logger.warning(f"ThematicExposureLab: xyz-sweep ${amount:.2f} geweigerd")
        except Exception as e:
            logger.warning(f"ThematicExposureLab: xyz-sweep mislukt: {e}")


# ── Review-acties (goedkeuren/corrigeren/negeren van nieuwe tickers) ──────
# Module-level, geen ThematicExposureLab-instantie nodig — enige bron van waarheid
# voor deze drie acties, hergebruikt door zowel de Telegram-commando's
# (agents/swarm_monitor.py: /themeapprove /themeedit /themeignore) als de
# dashboard-API (/api/thematic-exposure/*, utils/dashboard_server.py). Eerder
# stond deze logica alleen in swarm_monitor.py; nu op één plek zodat beide
# interfaces gegarandeerd hetzelfde gedrag hebben.

def approve_ticker(ticker: str) -> tuple:
    """Accepteert het bestaande LLM-voorstel zoals het is. Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicExposureLab._load_themes()
    except Exception as e:
        return False, f"Kan {THEMES_FILE} niet laden: {e}"
    entry = data.get("tickers", {}).get(ticker)
    if not entry:
        return False, f"{ticker} niet gevonden in de thema-registry."
    if not entry.get("themes"):
        return False, f"{ticker} heeft geen thema-voorstel (classificatie mislukt) — gebruik edit om er zelf een te geven."
    entry["status"] = "CONFIRMED"
    ThematicExposureLab._save_themes(data)
    themes_str = ", ".join(f"{k} ({v:.2f})" for k, v in entry["themes"].items())
    return True, f"{ticker} CONFIRMED — {themes_str}"


def edit_ticker(ticker: str, theme_spec: str) -> tuple:
    """theme_spec: 'semiconductors:0.6,memory_storage:0.2'. Overschrijft het
    voorstel en accepteert in één stap. Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicExposureLab._load_themes()
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
    ThematicExposureLab._save_themes(data)
    themes_str = ", ".join(f"{k} ({v:.2f})" for k, v in new_themes.items())
    return True, f"{ticker} CONFIRMED (handmatig) — {themes_str}"


def ignore_ticker(ticker: str) -> tuple:
    """Returns (success, message)."""
    ticker = ticker.upper()
    try:
        data = ThematicExposureLab._load_themes()
    except Exception as e:
        return False, f"Kan {THEMES_FILE} niet laden: {e}"
    entry = data.get("tickers", {}).get(ticker)
    if not entry:
        return False, f"{ticker} niet gevonden in de thema-registry."
    entry["status"] = "IGNORED"
    ThematicExposureLab._save_themes(data)
    return True, f"{ticker} IGNORED — telt niet meer mee in scoring/executie."
