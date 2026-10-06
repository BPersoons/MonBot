"""HYPE-basis: spot-HYPE long + HYPE-perp short op een eigen Hyperliquid-wallet.

Proefpotje (akkoord Bart 06-10, experiment `basis_hype` in config/experimenten.json).
Geen koersrisico zolang de twee benen even groot zijn; de opbrengst is de funding die
HYPE-longs aan de short betalen. Papier: scripts/basis_sim.py (2025 14,9%, 2026 5,7%
netto op kapitaal).

Opzet:
- Eigen wallet (HL_BASIS_WALLET_ADDRESS / HL_BASIS_PRIVATE_KEY), self-custody, account
  in de default-modus (niet unified): spot en perp hebben elk hun eigen USDC. Verplaatsen
  tussen de twee gaat met sendAsset naar het eigen adres ("spot" <-> "" = hoofd-perp-dex).
- Waarde = perp accountValue + spot-USDC + spot-HYPE x spotprijs. Onleesbaar = None.
- Spot is het anker. De short volgt de spot; nooit een short zonder spot eronder.
- Hefboom op de short = short-notional / perp accountValue. Doel 2x, bijsturen buiten
  [1,4x, 3x]. Prijs omhoog -> marge dun -> short verkleinen (reduceOnly), spot verkopen,
  USDC naar perp. Prijs omlaag -> te veel marge -> USDC naar spot, spot bijkopen, short
  vergroten.
- Afbouwen (short sluiten reduceOnly, spot verkopen) bij: schakelaar
  `basis_hype_afbouwen`, verlies >= 50% van de inleg (proeftuinregel), of 7 dagen
  negatieve funding.

Uit te zetten met `subsystem_basis_hype_enabled=false` (dan doet hij niets, ook niet
afbouwen: open benen blijven staan, gehedged). Afbouwen is een aparte schakelaar.
"""
import json
import logging
import math
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger("BasisHype")

STATE_FILE = "data/basis_hype_state.json"
COIN = "HYPE"
SPOT_INDEX = "@107"            # HYPE/USDC spot op HL
LEV_DOEL = 2.0
LEV_MIN = 1.4
LEV_MAX = 3.0
MIN_ORDER_USD = 11.0           # HL-minimum $10, met marge
HEDGE_TOL = 0.03               # relatief verschil spot vs short voor we corrigeren
STOP_VERLIES_PCT = 50.0        # proeftuin: max 50% verlies per potje
FUNDING_STOP_DAGEN = 7
FOUTEN_MELDEN = 3
API = "https://api.hyperliquid.xyz/info"


# ── pure planning (getoetst zonder netwerk) ───────────────────────────────────

def waarde(t):
    """Totale waarde van het potje, of None als een deel onleesbaar is."""
    try:
        w = float(t["perp_av"]) + float(t["spot_usdc"]) + float(t["spot_hype"]) * float(t["px"])
    except (KeyError, TypeError, ValueError):
        return None
    return w if math.isfinite(w) else None


def hefboom(t):
    """Short-notional / perp-marge. None zonder short of zonder marge."""
    if t["short_hype"] <= 0:
        return None
    if t["perp_av"] <= 0:
        return math.inf
    return t["short_hype"] * t["px"] / t["perp_av"]


def plan(t, inleg_usd, funding_7d, afbouwen=False):
    """Geeft een lijst stappen. Elke stap is een dict met `stap` en parameters.

    t: {spot_hype, short_hype, perp_av, spot_usdc, px}; inleg_usd: netto inleg (flows);
    funding_7d: gemiddelde uurfunding over 7 dagen (None = onbekend -> niet als reden).
    """
    w = waarde(t)
    if w is None:
        return [{"stap": "niets", "reden": "waarde onleesbaar"}]
    open_ = t["spot_hype"] * t["px"] >= MIN_ORDER_USD or t["short_hype"] * t["px"] >= MIN_ORDER_USD

    reden_af = None
    if afbouwen:
        reden_af = "schakelaar basis_hype_afbouwen"
    elif inleg_usd and inleg_usd > 0 and (inleg_usd - w) / inleg_usd * 100 >= STOP_VERLIES_PCT:
        reden_af = "verlies %.0f%% van de inleg" % ((inleg_usd - w) / inleg_usd * 100)
    elif open_ and funding_7d is not None and funding_7d < 0:
        reden_af = "funding 7 dagen negatief"
    if reden_af:
        if not open_:
            return [{"stap": "niets", "reden": "afgebouwd (%s)" % reden_af}]
        stappen = []
        if t["short_hype"] > 0:
            stappen.append({"stap": "short_kleiner", "qty": t["short_hype"], "reden": reden_af})
        if t["spot_hype"] * t["px"] >= MIN_ORDER_USD:
            stappen.append({"stap": "spot_verkoop", "qty": t["spot_hype"], "reden": reden_af})
        return stappen

    if not open_:
        if w < 3 * MIN_ORDER_USD:
            return [{"stap": "niets", "reden": "te weinig kapitaal ($%.2f)" % w}]
        n = w * LEV_DOEL / (1 + LEV_DOEL)
        return [{"stap": "naar_spot", "usd": max(0.0, n - t["spot_usdc"]), "reden": "openen"},
                {"stap": "spot_koop", "usd": n, "reden": "openen"},
                {"stap": "rest_naar_perp", "reden": "openen"},
                {"stap": "short_volgt_spot", "reden": "openen"}]

    # Open: eerst de hedge, dan de hefboom.
    verschil = t["spot_hype"] - t["short_hype"]
    groot = max(t["spot_hype"], t["short_hype"])
    if abs(verschil) * t["px"] >= MIN_ORDER_USD and abs(verschil) / groot > HEDGE_TOL:
        return [{"stap": "short_volgt_spot", "reden": "hedge scheef (%+.2f HYPE)" % verschil}]

    h = hefboom(t)
    if h is not None and (h > LEV_MAX or h < LEV_MIN):
        n = w * LEV_DOEL / (1 + LEV_DOEL)
        dq = n / t["px"] - t["spot_hype"]
        if abs(dq) * t["px"] < MIN_ORDER_USD:
            return [{"stap": "niets", "reden": "hefboom %.2fx maar bijsturen < $%.0f" % (h, MIN_ORDER_USD)}]
        if dq < 0:   # koers omhoog: kleiner, marge aanvullen
            return [{"stap": "short_kleiner", "qty": -dq, "reden": "hefboom %.2fx" % h},
                    {"stap": "spot_verkoop", "qty": -dq, "reden": "hefboom %.2fx" % h},
                    {"stap": "rest_naar_perp", "reden": "hefboom %.2fx" % h}]
        return [{"stap": "naar_spot", "usd": dq * t["px"], "reden": "hefboom %.2fx" % h},
                {"stap": "spot_koop", "usd": dq * t["px"], "reden": "hefboom %.2fx" % h},
                {"stap": "short_volgt_spot", "reden": "hefboom %.2fx" % h}]
    return [{"stap": "niets", "reden": "binnen band (%.2fx)" % h if h else "binnen band"}]


# ── uitvoering ─────────────────────────────────────────────────────────────────

def _info(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


class BasisHype:
    def __init__(self, exchange_client, adres, telegram=None):
        """exchange_client: HyperliquidExchange op de EIGEN wallet (self-custody)."""
        self.ex = exchange_client
        self.adres = adres
        self._telegram = telegram or _telegram
        self.state = self._laad()

    # state
    def _laad(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {"fouten": 0, "historie": []}
        except Exception as e:
            logger.error("basis_hype_state.json onleesbaar: %s", e)
            raise

    def _bewaar(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tekst = json.dumps(self.state, indent=1, allow_nan=False)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:   # in-place (bind mount)
            fh.write(tekst)

    # lezen
    def toestand(self):
        """Lees alles van HL. Gooit bij een leesfout (de beller telt een fout)."""
        # De rekensom (perp-marge apart van spot-USDC) klopt alleen in de default-modus.
        # In een unified account staat de marge in spot en is accountValue 0: dan zou de
        # hefboom oneindig lijken en zou hij blijven bijsturen. Dus weigeren.
        modus = _info({"type": "userAbstraction", "user": self.adres})
        if modus not in ("default", None):
            raise RuntimeError("account staat in modus %r, verwacht 'default'" % (modus,))
        spot = _info({"type": "spotClearinghouseState", "user": self.adres})
        bal = {b["coin"]: float(b["total"]) for b in spot.get("balances", [])}
        perp = _info({"type": "clearinghouseState", "user": self.adres})
        short = 0.0
        for p in perp.get("assetPositions", []):
            pos = p.get("position", {})
            if pos.get("coin") == COIN:
                szi = float(pos.get("szi") or 0.0)
                short = -szi if szi < 0 else 0.0
                if szi > 0:
                    raise RuntimeError("onverwachte LONG-perp op HYPE (%s)" % szi)
        meta, ctx = _info({"type": "spotMetaAndAssetCtxs"})
        px = None
        for u, c in zip(meta["universe"], ctx):
            if u.get("name") == SPOT_INDEX:
                px = float(c.get("markPx") or c.get("midPx") or 0) or None
        if not px:
            raise RuntimeError("geen spotprijs voor HYPE")
        return {"spot_hype": bal.get(COIN, 0.0), "spot_usdc": bal.get("USDC", 0.0),
                "short_hype": short, "perp_av": float(perp["marginSummary"]["accountValue"]),
                "px": px}

    @staticmethod
    def funding_7d():
        try:
            start = int((time.time() - FUNDING_STOP_DAGEN * 86400) * 1000)
            h = _info({"type": "fundingHistory", "coin": COIN, "startTime": start})
            fr = [float(x["fundingRate"]) for x in h]
            return sum(fr) / len(fr) if len(fr) >= 24 * (FUNDING_STOP_DAGEN - 1) else None
        except Exception:
            return None

    @staticmethod
    def inleg():
        """Netto inleg in potje `basis` uit flows (één definitie, zoals H3)."""
        from utils import flows
        return flows.netto_flow(flows.laad_flows(), "basis", 0.0, time.time())

    # schrijven
    def _verplaats(self, bedrag, van, naar):
        if bedrag < 1.0:
            return True
        from agents.treasury_agent import TreasuryAgent
        ok = TreasuryAgent._send_asset(self.ex.signing_client, self.adres,
                                       math.floor(bedrag * 100) / 100, van, naar)
        if not ok:
            raise RuntimeError("sendAsset %s->%s $%.2f mislukt" % (van or "perp", naar or "perp", bedrag))
        time.sleep(2)
        return True

    def _voer_uit(self, stap, t):
        s = stap["stap"]
        prec = 0.01
        if s == "naar_spot":
            nodig = stap["usd"]
            if nodig >= 1.0:
                self._verplaats(min(nodig, max(0.0, t["perp_av"] - 0.5)), "", "spot")
        elif s == "spot_koop":
            t = self.toestand()
            usd = min(stap["usd"], t["spot_usdc"] * 0.995)
            qty = math.floor(usd / t["px"] / prec) * prec
            if qty * t["px"] < MIN_ORDER_USD:
                raise RuntimeError("spot-koop te klein ($%.2f)" % (qty * t["px"]))
            if not self.ex.create_spot_order(COIN, "buy", qty):
                raise RuntimeError("spot-koop mislukt")
        elif s == "spot_verkoop":
            t = self.toestand()
            qty = math.floor(min(stap["qty"], t["spot_hype"]) / prec) * prec
            if qty * t["px"] >= MIN_ORDER_USD and not self.ex.create_spot_order(COIN, "sell", qty):
                raise RuntimeError("spot-verkoop mislukt")
        elif s == "rest_naar_perp":
            t = self.toestand()
            self._verplaats(max(0.0, t["spot_usdc"] - 0.5), "spot", "")
        elif s == "short_kleiner":
            t = self.toestand()
            qty = round(min(stap["qty"], t["short_hype"]), 2)
            if qty > 0 and not self.ex.create_order(COIN, "buy", qty, reduce_only=True,
                                                    leverage=3, margin_mode="cross"):
                raise RuntimeError("short verkleinen mislukt")
        elif s == "short_volgt_spot":
            t = self.toestand()
            dq = round(t["spot_hype"] - t["short_hype"], 2)
            if abs(dq) * t["px"] < MIN_ORDER_USD:
                return
            if dq > 0:
                if not self.ex.create_order(COIN, "sell", dq, leverage=3, margin_mode="cross"):
                    raise RuntimeError("short vergroten mislukt")
            elif not self.ex.create_order(COIN, "buy", -dq, reduce_only=True,
                                          leverage=3, margin_mode="cross"):
                raise RuntimeError("short verkleinen mislukt")
        elif s != "niets":
            raise ValueError("onbekende stap %s" % s)

    def run_cycle(self):
        from utils.auto_params import subsysteem_aan, AutoParams
        if not subsysteem_aan("basis_hype"):
            return None
        try:
            afbouwen = str(AutoParams().get_candidate_value("basis_hype_afbouwen")).lower() in ("true", "1")
        except Exception:
            afbouwen = False
        nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            t = self.toestand()
            inleg = self.inleg()
            stappen = plan(t, inleg, self.funding_7d(), afbouwen)
            for st in stappen:
                if st["stap"] != "niets":
                    logger.info("BasisHype: %s (%s)", st["stap"], st.get("reden"))
                self._voer_uit(st, t)
            if any(st["stap"] != "niets" for st in stappen):
                t = self.toestand()
                self.state["historie"] = (self.state.get("historie", []) + [
                    {"ts": nu, "stappen": [st["stap"] for st in stappen],
                     "reden": stappen[0].get("reden")}])[-200:]
            self.state["fouten"] = 0
        except Exception as e:
            self.state["fouten"] = int(self.state.get("fouten", 0)) + 1
            logger.error("BasisHype: %s (fout %d op rij)", e, self.state["fouten"])
            if self.state["fouten"] == FOUTEN_MELDEN:
                self._telegram("BasisHype: %d cycli op rij fout. Laatste: %s. "
                               "Controleer de hedge op Hyperliquid." % (FOUTEN_MELDEN, str(e)[:200]))
            try:
                t = self.toestand()
                inleg = self.inleg()
            except Exception:
                t, inleg = None, None
        if t is not None:
            w = waarde(t)
            h = hefboom(t)
            self.state.update({
                "laatst": nu, "waarde_usd": None if w is None else round(w, 2),
                "inleg_usd": None if inleg is None else round(inleg, 2),
                "spot_hype": t["spot_hype"], "short_hype": t["short_hype"],
                "perp_av": round(t["perp_av"], 2), "spot_usdc": round(t["spot_usdc"], 2),
                "px": t["px"], "hefboom": None if h is None or not math.isfinite(h) else round(h, 2),
            })
        else:
            self.state.update({"laatst_fout": nu})
        self._bewaar()
        return self.state


def lees_state(pad=None):
    """Voor nav/sleeve_nav/verliesbewaking: (waarde, inleg, laatst) of None als er
    geen potje is. Gooit bij een onleesbaar bestand (onmeetbaar is geen nul)."""
    pad = pad or STATE_FILE
    if not os.path.lexists(pad):
        return None
    with open(pad, encoding="utf-8") as fh:
        d = json.load(fh)
    return d.get("waarde_usd"), d.get("inleg_usd"), d.get("laatst")


def _telegram(tekst):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        logger.info("BasisHype (geen Telegram): %s", tekst)
        return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": tekst}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot%s/sendMessage" % token, data=data), timeout=10)
    except Exception as e:
        logger.warning("BasisHype: Telegram mislukt: %s", e)
