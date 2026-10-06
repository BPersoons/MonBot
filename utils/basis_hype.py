"""HYPE-basis: spot-HYPE long + HYPE-perp short op een eigen Hyperliquid-wallet.

Proefpotje (akkoord Bart 06-10, experiment `basis_hype` in config/experimenten.json).
Geen koersrisico zolang de twee benen even groot zijn; de opbrengst is de funding die
HYPE-longs aan de short betalen. Papier: scripts/basis_sim.py.

Opzet:
- Eigen wallet (HL_BASIS_WALLET_ADDRESS / HL_BASIS_PRIVATE_KEY), self-custody, account
  in de default-modus (niet unified): spot en perp hebben elk hun eigen USDC. Verplaatsen
  gaat met sendAsset naar het eigen adres ("spot" <-> "" = hoofd-perp-dex).
- Waarde = perp accountValue + spot-USDC + spot-HYPE x spotprijs. Onleesbaar = None.
- Spot is het anker; de short volgt de gemeten spot. Bij openen staat de marge EERST op
  perp, dan pas de spotkoop: een mislukte overboeking gebeurt zo vóór er blootstelling is.
- Hefboom op de short = short-notional / perp-marge, binnen het kader van 2x (PLAN):
  doel 1,5x, bijsturen buiten [1,0x, 2,0x]. Liquidatie (onderhoudsmarge ~5%) ligt vanaf
  2x op ~+43% koers binnen een cyclus.
- Afbouwen (short sluiten reduceOnly, spot verkopen) bij de schakelaar
  `basis_hype_afbouwen`, bij verlies >= 50% van de inleg of bij 7 dagen negatieve funding.
  Afbouwen is BLIJVEND: de state krijgt `afgebouwd` en de module opent niet opnieuw tot
  iemand die vlag met de hand weghaalt (A1 06-10: anders opent en sluit hij om en om).
- Openen alleen als het register `live` zegt en er inleg geboekt is (flows, potje
  `basis`) — anders staat de 50%-stop uit.

`subsystem_basis_hype_enabled=false`: hij meet nog wel (waarde in de state), maar
handelt niet. Open benen blijven dan gehedged staan.
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
REGISTER_FILE = "config/experimenten.json"
COIN = "HYPE"
PERP_SYMBOL = "HYPE/USDC:USDC"   # ccxt; "HYPE" los wordt door _normalize_symbol niet gevonden
SPOT_INDEX = "@107"              # HYPE/USDC spot op HL (ctx gekoppeld op "coin", niet op positie)
LEV_DOEL = 1.5
LEV_MIN = 1.0
LEV_MAX = 2.0
LEVERAGE_INSTELLING = 2          # HL-instelling op de perp (cross)
MIN_ORDER_USD = 11.0             # HL-minimum $10, met marge
HEDGE_TOL = 0.03
STOP_VERLIES_PCT = 50.0
FUNDING_STOP_DAGEN = 7
FOUTEN_MELDEN = 3
MAX_OUDERDOM_S = 3600            # voor de meetkant: oudere waarde met open benen = onmeetbaar
SPOT_KOOP_FRACTIE = 0.97         # ruimte voor de slippage-limiet van een spot-marketorder
API = "https://api.hyperliquid.xyz/info"


# ── pure planning (getoetst zonder netwerk) ───────────────────────────────────

def waarde(t):
    try:
        w = float(t["perp_av"]) + float(t["spot_usdc"]) + float(t["spot_hype"]) * float(t["px"])
    except (KeyError, TypeError, ValueError):
        return None
    return w if math.isfinite(w) else None


def hefboom(t):
    if t["short_hype"] <= 0:
        return None
    if t["perp_av"] <= 0:
        return math.inf
    return t["short_hype"] * t["px"] / t["perp_av"]


def is_open(t):
    return (t["spot_hype"] * t["px"] >= MIN_ORDER_USD or t["short_hype"] * t["px"] >= MIN_ORDER_USD)


def _afbouw_stappen(t, reden):
    stappen = [{"stap": "markeer_afgebouwd", "reden": reden}]
    if t["short_hype"] > 0:
        stappen.append({"stap": "short_kleiner", "qty": t["short_hype"], "reden": reden})
    if t["spot_hype"] * t["px"] >= MIN_ORDER_USD:
        stappen.append({"stap": "spot_verkoop", "qty": t["spot_hype"], "reden": reden})
    return stappen


def plan(t, inleg_usd, funding_7d, afbouwen=False, afgebouwd=None, live=True):
    """Lijst stappen. t: {spot_hype, short_hype, perp_av, spot_usdc, px}.

    inleg_usd: netto inleg (flows); funding_7d: gemiddelde uurfunding over 7 dagen
    (None = onbekend); afgebouwd: reden uit de state of None; live: register zegt live.
    """
    w = waarde(t)
    if w is None:
        return [{"stap": "niets", "reden": "waarde onleesbaar"}]
    open_ = is_open(t)

    reden_af = None
    if afgebouwd:
        reden_af = "afgebouwd (%s)" % afgebouwd
    elif afbouwen:
        reden_af = "schakelaar basis_hype_afbouwen"
    elif inleg_usd and inleg_usd > 0 and (inleg_usd - w) / inleg_usd * 100 >= STOP_VERLIES_PCT:
        reden_af = "verlies %.0f%% van de inleg" % ((inleg_usd - w) / inleg_usd * 100)
    elif open_ and funding_7d is not None and funding_7d < 0:
        reden_af = "funding 7 dagen negatief"
    if reden_af:
        if not open_:
            if afgebouwd:
                return [{"stap": "niets", "reden": reden_af}]
            return [{"stap": "markeer_afgebouwd", "reden": reden_af}]
        stappen = _afbouw_stappen(t, reden_af)
        return stappen[1:] if afgebouwd else stappen

    n_doel = w * LEV_DOEL / (1 + LEV_DOEL)

    if not open_:
        if not live:
            return [{"stap": "niets", "reden": "register staat niet op live"}]
        if not inleg_usd or inleg_usd <= 0:
            return [{"stap": "niets", "reden": "geen inleg geboekt"}]
        if funding_7d is not None and funding_7d < 0:
            return [{"stap": "niets", "reden": "funding negatief, niet openen"}]
        if w < 3 * MIN_ORDER_USD:
            return [{"stap": "niets", "reden": "te weinig kapitaal ($%.2f)" % w}]
        return [{"stap": "verdeel_kas", "doel_spot": n_doel / SPOT_KOOP_FRACTIE, "reden": "openen"},
                {"stap": "spot_koop", "usd": n_doel, "reden": "openen"},
                {"stap": "short_volgt_spot", "reden": "openen"}]

    # Open: eerst de hedge.
    verschil = t["spot_hype"] - t["short_hype"]
    groot = max(t["spot_hype"], t["short_hype"])
    if abs(verschil) * t["px"] >= MIN_ORDER_USD and abs(verschil) / groot > HEDGE_TOL:
        reden = "hedge scheef (%+.2f HYPE)" % verschil
        if verschil > 0 and t["perp_av"] < t["spot_hype"] * t["px"] / LEV_MAX:
            # Te weinig marge om de spot te dekken: eerst spot terug naar het doel,
            # alle spot-USDC naar perp, dan pas de short.
            stappen = []
            if (t["spot_hype"] - n_doel / t["px"]) * t["px"] >= MIN_ORDER_USD:
                stappen.append({"stap": "spot_verkoop", "qty": t["spot_hype"] - n_doel / t["px"],
                                "reden": reden})
            return stappen + [{"stap": "verdeel_kas", "doel_spot": 0.0, "reden": reden},
                              {"stap": "short_volgt_spot", "reden": reden}]
        return [{"stap": "short_volgt_spot", "reden": reden}]

    h = hefboom(t)
    if h is not None and (h > LEV_MAX or h < LEV_MIN):
        dq = n_doel / t["px"] - t["spot_hype"]
        if h > LEV_MAX and abs(dq) * t["px"] < MIN_ORDER_USD:
            # Kader 2x gaat voor: liever iets te ver terug dan boven 2x blijven omdat
            # het bijsturen onder het HL-minimum valt (A1 06-10).
            dq = -MIN_ORDER_USD / t["px"]
        if abs(dq) * t["px"] < MIN_ORDER_USD:
            return [{"stap": "niets", "reden": "hefboom %.2fx maar bijsturen < $%.0f" % (h, MIN_ORDER_USD)}]
        reden = "hefboom %.2fx" % h
        if dq < 0:   # koers omhoog: short kleiner, spot verkopen, USDC naar marge
            return [{"stap": "short_kleiner", "qty": -dq, "reden": reden},
                    {"stap": "spot_verkoop", "qty": -dq, "reden": reden},
                    {"stap": "verdeel_kas", "doel_spot": 0.0, "reden": reden}]
        return [{"stap": "verdeel_kas", "doel_spot": t["spot_usdc"] + dq * t["px"] / SPOT_KOOP_FRACTIE,
                 "reden": reden},
                {"stap": "spot_koop", "usd": dq * t["px"], "reden": reden},
                {"stap": "short_volgt_spot", "reden": reden}]
    return [{"stap": "niets", "reden": ("binnen band (%.2fx)" % h) if h else "binnen band"}]


def spotprijs(meta, ctx, index=SPOT_INDEX):
    """Prijs van een spotmarkt uit spotMetaAndAssetCtxs. Koppelt op `coin`: universe
    (330) en ctx (1005) lopen NIET gelijk op (A1 06-10: zip gaf de prijs van @105)."""
    for c in ctx:
        if c.get("coin") == index:
            px = float(c.get("markPx") or c.get("midPx") or 0)
            return px if px > 0 and math.isfinite(px) else None
    return None


# ── uitvoering ─────────────────────────────────────────────────────────────────

def _info(body):
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def register_live(pad=None):
    try:
        with open(pad or REGISTER_FILE, encoding="utf-8") as fh:
            e = (json.load(fh).get("experimenten") or {}).get("basis_hype") or {}
        return e.get("status") == "live"
    except Exception:
        return False


class BasisHype:
    def __init__(self, exchange_client, adres, telegram=None):
        """exchange_client: HyperliquidExchange op de EIGEN wallet (self-custody)."""
        self.ex = exchange_client
        self.adres = adres
        self._telegram = telegram or _telegram
        self.state = self._laad()

    def _laad(self):
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return {"fouten": 0, "historie": []}

    def _bewaar(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tekst = json.dumps(self.state, indent=1, allow_nan=False)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:   # in-place (bind mount)
            fh.write(tekst)

    def toestand(self):
        """Lees alles van HL. Gooit bij een leesfout of een onverwachte stand."""
        # De rekensom (perp-marge apart van spot-USDC) klopt alleen in de default-modus.
        modus = _info({"type": "userAbstraction", "user": self.adres})
        if modus != "default":
            raise RuntimeError("account staat in modus %r, verwacht 'default'" % (modus,))
        spot = _info({"type": "spotClearinghouseState", "user": self.adres})
        bal = {b["coin"]: float(b["total"]) for b in spot.get("balances", [])}
        perp = _info({"type": "clearinghouseState", "user": self.adres})
        short = 0.0
        for p in perp.get("assetPositions", []):
            pos = p.get("position", {})
            if pos.get("coin") == COIN:
                szi = float(pos.get("szi") or 0.0)
                if szi > 0:
                    raise RuntimeError("onverwachte LONG-perp op HYPE (%s)" % szi)
                short = -szi
        meta, ctx = _info({"type": "spotMetaAndAssetCtxs"})
        px = spotprijs(meta, ctx)
        if not px:
            raise RuntimeError("geen spotprijs voor HYPE (%s)" % SPOT_INDEX)
        return {"spot_hype": bal.get(COIN, 0.0), "spot_usdc": bal.get("USDC", 0.0),
                "short_hype": short, "perp_av": float(perp["marginSummary"]["accountValue"]),
                "withdrawable": float(perp.get("withdrawable") or 0.0), "px": px}

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
        from utils import flows
        return flows.netto_flow(flows.laad_flows(), "basis", 0.0, time.time())

    def _verplaats(self, bedrag, van, naar):
        if bedrag < 1.0:
            return
        from agents.treasury_agent import TreasuryAgent
        ok = TreasuryAgent._send_asset(self.ex.signing_client, self.adres,
                                       math.floor(bedrag * 100) / 100, van, naar)
        if not ok:
            raise RuntimeError("sendAsset %s->%s $%.2f mislukt" % (van or "perp", naar or "perp", bedrag))
        time.sleep(2)

    def _voer_uit(self, stap):
        s = stap["stap"]
        prec = 0.01
        if s == "niets":
            return
        if s == "markeer_afgebouwd":
            self.state["afgebouwd"] = stap["reden"]
            self.state["afgebouwd_op"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._bewaar()
            self._telegram("BasisHype: afbouwen (%s). Heropenen alleen met de hand "
                           "(vlag 'afgebouwd' uit data/basis_hype_state.json)." % stap["reden"])
            return
        t = self.toestand()
        if s == "verdeel_kas":
            verschil = stap["doel_spot"] - t["spot_usdc"]
            if verschil >= 1.0:
                self._verplaats(min(verschil, max(0.0, t["withdrawable"] - 0.5)), "", "spot")
            elif verschil <= -1.0:
                self._verplaats(-verschil, "spot", "")
        elif s == "spot_koop":
            usd = min(stap["usd"], t["spot_usdc"] * SPOT_KOOP_FRACTIE)
            qty = math.floor(usd / t["px"] / prec) * prec
            if qty * t["px"] < MIN_ORDER_USD:
                raise RuntimeError("spot-koop te klein ($%.2f)" % (qty * t["px"]))
            if not self.ex.create_spot_order(COIN, "buy", qty):
                raise RuntimeError("spot-koop mislukt")
        elif s == "spot_verkoop":
            qty = math.floor(min(stap["qty"], t["spot_hype"]) / prec) * prec
            if qty * t["px"] >= MIN_ORDER_USD and not self.ex.create_spot_order(COIN, "sell", qty):
                raise RuntimeError("spot-verkoop mislukt")
        elif s == "short_kleiner":
            qty = round(min(stap["qty"], t["short_hype"]), 2)
            if qty > 0 and not self.ex.create_order(PERP_SYMBOL, "buy", qty, reduce_only=True,
                                                    leverage=LEVERAGE_INSTELLING, margin_mode="cross"):
                raise RuntimeError("short verkleinen mislukt")
        elif s == "short_volgt_spot":
            dq = round(t["spot_hype"] - t["short_hype"], 2)
            if abs(dq) * t["px"] < MIN_ORDER_USD:
                return
            if dq > 0:
                if not self.ex.create_order(PERP_SYMBOL, "sell", dq,
                                            leverage=LEVERAGE_INSTELLING, margin_mode="cross"):
                    raise RuntimeError("short vergroten mislukt")
            elif not self.ex.create_order(PERP_SYMBOL, "buy", -dq, reduce_only=True,
                                          leverage=LEVERAGE_INSTELLING, margin_mode="cross"):
                raise RuntimeError("short verkleinen mislukt")
        else:
            raise ValueError("onbekende stap %s" % s)

    def run_cycle(self):
        """Meet altijd (waarde in de state); handelt alleen als het subsysteem aan staat."""
        from utils.auto_params import subsysteem_aan, AutoParams
        handelen = subsysteem_aan("basis_hype")
        try:
            afbouwen = str(AutoParams().get_candidate_value("basis_hype_afbouwen")).lower() in ("true", "1")
        except Exception:
            afbouwen = False
        nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t = inleg = None
        try:
            t = self.toestand()
            inleg = self.inleg()
            if handelen:
                stappen = plan(t, inleg, self.funding_7d(), afbouwen,
                               self.state.get("afgebouwd"), register_live())
                for st in stappen:
                    if st["stap"] != "niets":
                        logger.info("BasisHype: %s (%s)", st["stap"], st.get("reden"))
                    self._voer_uit(st)
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
                t = None
        if t is not None:
            w = waarde(t)
            h = hefboom(t)
            self.state.update({
                "laatst": nu, "waarde_usd": None if w is None else round(w, 2),
                "inleg_usd": None if inleg is None else round(inleg, 2),
                "open": is_open(t),
                "spot_hype": t["spot_hype"], "short_hype": t["short_hype"],
                "perp_av": round(t["perp_av"], 2), "spot_usdc": round(t["spot_usdc"], 2),
                "px": t["px"], "hefboom": None if h is None or not math.isfinite(h) else round(h, 2),
            })
        else:
            self.state["laatst_fout"] = nu
        self._bewaar()
        return self.state


def lees_state(pad=None, nu=None):
    """Voor nav/sleeve_nav/verliesbewaking: (waarde, inleg, laatst) of None als er
    geen potje is. Gooit bij een onleesbaar bestand. Staan de benen open en is de
    meting ouder dan MAX_OUDERDOM_S, dan is de waarde onmeetbaar (None): een oude
    waarde zou stil als vers meetellen (A1 06-10)."""
    pad = pad or STATE_FILE
    if not os.path.lexists(pad):
        return None
    with open(pad, encoding="utf-8") as fh:
        d = json.load(fh)
    w = d.get("waarde_usd")
    if d.get("open"):
        try:
            leeftijd = (nu or time.time()) - datetime.fromisoformat(d["laatst"]).timestamp()
        except Exception:
            leeftijd = math.inf
        if leeftijd > MAX_OUDERDOM_S:
            w = None
    return w, d.get("inleg_usd"), d.get("laatst")


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
