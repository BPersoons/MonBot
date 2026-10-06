import json
import math

import pytest

from utils import basis_hype as bh
from utils.basis_hype import plan, waarde, hefboom


def T(spot=0.0, short=0.0, perp=0.0, usdc=0.0, px=40.0):
    return {"spot_hype": spot, "short_hype": short, "perp_av": perp, "spot_usdc": usdc, "px": px}


def stappen(p):
    return [s["stap"] for s in p]


# ── waarde en hefboom ─────────────────────────────────────────────────────────

def test_waarde_telt_drie_delen():
    assert waarde(T(spot=2, perp=50, usdc=10, px=40)) == 140


def test_waarde_onleesbaar_is_none():
    t = T()
    t["perp_av"] = None
    assert waarde(t) is None


def test_hefboom_zonder_marge_is_oneindig():
    assert hefboom(T(short=1, perp=0)) == math.inf


# ── openen ────────────────────────────────────────────────────────────────────

def test_openen_koopt_eerst_spot_en_short_daarna():
    p = stappen(plan(T(usdc=150), 150, 0.00001))
    assert p.index("spot_koop") < p.index("short_volgt_spot")
    assert p[0] == "naar_spot" and "rest_naar_perp" in p


def test_openen_zet_twee_derde_in_spot():
    st = plan(T(usdc=150), 150, 0.00001)
    koop = [s for s in st if s["stap"] == "spot_koop"][0]
    assert koop["usd"] == pytest.approx(100.0)


def test_te_weinig_kapitaal_doet_niets():
    assert stappen(plan(T(usdc=20), 20, 0.0001)) == ["niets"]


def test_onleesbaar_doet_niets():
    t = T(usdc=150)
    t["px"] = None
    assert stappen(plan(t, 150, 0.0001)) == ["niets"]


# ── hedge ─────────────────────────────────────────────────────────────────────

def test_scheve_hedge_wordt_eerst_rechtgezet():
    # spot 2,5 HYPE, short 2,0: $20 verschil, 20% -> short volgt spot
    assert stappen(plan(T(spot=2.5, short=2.0, perp=50, px=40), 150, 0.0001)) == ["short_volgt_spot"]


def test_kleine_scheefheid_onder_minimum_blijft_staan():
    assert stappen(plan(T(spot=2.5, short=2.45, perp=50, px=40), 150, 0.0001)) == ["niets"]


# ── bijsturen ─────────────────────────────────────────────────────────────────

def test_binnen_band_niets():
    # notional 100, marge 50 -> 2x
    assert stappen(plan(T(spot=2.5, short=2.5, perp=50, px=40), 150, 0.0001)) == ["niets"]


def test_koers_omhoog_eerst_short_kleiner_dan_spot_verkopen():
    # koers 40 -> 60: notional 150, marge 50-50=0 ... neem marge 40 -> 3,75x
    p = stappen(plan(T(spot=2.5, short=2.5, perp=40, px=60), 150, 0.0001))
    assert p == ["short_kleiner", "spot_verkoop", "rest_naar_perp"]


def test_koers_omlaag_eerst_spot_kopen_dan_short_groter():
    # notional 2,5*25=62,5, marge 75 -> 0,83x
    p = stappen(plan(T(spot=2.5, short=2.5, perp=75, px=25), 150, 0.0001))
    assert p == ["naar_spot", "spot_koop", "short_volgt_spot"]


def test_bijsturen_brengt_terug_naar_twee_x():
    st = plan(T(spot=2.5, short=2.5, perp=40, px=60), 150, 0.0001)
    w = waarde(T(spot=2.5, short=2.5, perp=40, px=60))
    doel_q = w * 2 / 3 / 60
    assert st[0]["qty"] == pytest.approx(2.5 - doel_q)


# ── afbouwen ──────────────────────────────────────────────────────────────────

def test_verlies_van_50_procent_bouwt_af_short_eerst():
    p = stappen(plan(T(spot=1.0, short=1.0, perp=20, px=40), 160, 0.0001))   # waarde 60 < 80
    assert p == ["short_kleiner", "spot_verkoop"]


def test_verlies_net_onder_50_procent_blijft():
    p = stappen(plan(T(spot=2.0, short=2.0, perp=40, px=40), 239, 0.0001))   # waarde 120, 49,8%
    assert "short_kleiner" not in p


def test_negatieve_funding_bouwt_af():
    assert stappen(plan(T(spot=2.5, short=2.5, perp=50, px=40), 150, -0.00001))[0] == "short_kleiner"


def test_onbekende_funding_is_geen_reden_om_af_te_bouwen():
    assert stappen(plan(T(spot=2.5, short=2.5, perp=50, px=40), 150, None)) == ["niets"]


def test_schakelaar_bouwt_af():
    assert stappen(plan(T(spot=2.5, short=2.5, perp=50, px=40), 150, 0.0001, afbouwen=True))[0] == "short_kleiner"


def test_afgebouwd_doet_niets_meer():
    assert stappen(plan(T(usdc=150), 150, -0.0001, afbouwen=True)) == ["niets"]


# ── uitvoering: volgorde en reduceOnly ────────────────────────────────────────

class FakeEx:
    def __init__(self, state):
        self.s = state
        self.orders = []
        self.signing_client = object()

    def create_spot_order(self, coin, side, qty):
        self.orders.append(("spot", side, qty))
        px = self.s["px"]
        if side == "buy":
            self.s["spot_usdc"] -= qty * px
            self.s["spot_hype"] += qty
        else:
            self.s["spot_usdc"] += qty * px
            self.s["spot_hype"] -= qty
        return {"id": "x"}

    def create_order(self, coin, side, qty, reduce_only=False, leverage=None, margin_mode=None):
        self.orders.append(("perp", side, qty, reduce_only))
        self.s["short_hype"] += qty if side == "sell" else -qty
        return {"id": "y"}


@pytest.fixture
def omgeving(monkeypatch, tmp_path):
    monkeypatch.setattr(bh, "STATE_FILE", str(tmp_path / "data" / "basis_hype_state.json"))
    st = T(usdc=150.0, px=40.0)

    def verplaats(self, bedrag, van, naar):
        if van == "spot":
            st["spot_usdc"] -= bedrag
            st["perp_av"] += bedrag
        else:
            st["perp_av"] -= bedrag
            st["spot_usdc"] += bedrag
        return True

    monkeypatch.setattr(bh.BasisHype, "_verplaats", verplaats)
    monkeypatch.setattr(bh.BasisHype, "toestand", lambda self: dict(st))
    monkeypatch.setattr(bh.BasisHype, "funding_7d", staticmethod(lambda: 0.00001))
    monkeypatch.setattr(bh.BasisHype, "inleg", staticmethod(lambda: 150.0))
    import utils.auto_params as ap
    monkeypatch.setattr(ap, "subsysteem_aan", lambda naam, standaard=True: True)
    monkeypatch.setattr(ap.AutoParams, "get_candidate_value", lambda self, k: None)
    ex = FakeEx(st)
    meldingen = []
    return bh.BasisHype(ex, "0xabc", telegram=meldingen.append), ex, st, meldingen


def test_cyclus_opent_gehedged(omgeving):
    b, ex, st, _ = omgeving
    b.run_cycle()
    assert ex.orders[0][:2] == ("spot", "buy")
    assert ex.orders[1][:2] == ("perp", "sell") and ex.orders[1][3] is False
    assert st["short_hype"] == pytest.approx(st["spot_hype"])
    assert st["short_hype"] * 40 / st["perp_av"] == pytest.approx(2.0, rel=0.05)


def test_cyclus_schrijft_waarde_weg(omgeving):
    b, _, _, _ = omgeving
    b.run_cycle()
    d = json.load(open(bh.STATE_FILE, encoding="utf-8"))
    assert d["waarde_usd"] == pytest.approx(150.0, abs=0.5) and d["inleg_usd"] == 150.0
    assert bh.lees_state()[0] == d["waarde_usd"]


def test_short_kleiner_is_altijd_reduce_only(omgeving):
    b, ex, st, _ = omgeving
    b.run_cycle()
    st["px"] = 60.0                       # koers omhoog -> marge dun
    st["perp_av"] -= st["short_hype"] * 20
    ex.orders.clear()
    b.run_cycle()
    perp = [o for o in ex.orders if o[0] == "perp"]
    assert perp and all(o[1] == "buy" and o[3] is True for o in perp)


def test_afbouwen_sluit_short_reduce_only_en_verkoopt_spot(omgeving, monkeypatch):
    b, ex, st, _ = omgeving
    b.run_cycle()
    monkeypatch.setattr(bh.BasisHype, "funding_7d", staticmethod(lambda: -0.00001))
    ex.orders.clear()
    b.run_cycle()
    assert ex.orders[0][0] == "perp" and ex.orders[0][3] is True
    assert ex.orders[1][:2] == ("spot", "sell")
    assert st["short_hype"] == pytest.approx(0, abs=0.01)


def test_mislukte_short_telt_fouten_en_meldt_een_keer(omgeving):
    b, ex, st, meldingen = omgeving
    ex.create_order = lambda *a, **k: None
    for _ in range(4):
        b.run_cycle()
    assert b.state["fouten"] == 4 and len(meldingen) == 1


def test_uit_doet_niets(omgeving, monkeypatch):
    b, ex, _, _ = omgeving
    import utils.auto_params as ap
    monkeypatch.setattr(ap, "subsysteem_aan", lambda naam, standaard=True: False)
    assert b.run_cycle() is None and not ex.orders


def test_lees_state_zonder_bestand_is_none(tmp_path):
    assert bh.lees_state(str(tmp_path / "nee.json")) is None


def test_lees_state_kapot_bestand_gooit(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{kapot")
    with pytest.raises(Exception):
        bh.lees_state(str(p))


def test_short_groter_dan_spot_wordt_reduce_only_verkleind(omgeving):
    b, ex, st, _ = omgeving
    b.run_cycle()
    st["spot_hype"] -= 1.0                # spot kwijt (bv. handmatig verkocht)
    st["spot_usdc"] += 40.0
    ex.orders.clear()
    b.run_cycle()
    assert ex.orders == [("perp", "buy", pytest.approx(1.0, abs=0.01), True)]


def test_unified_account_wordt_geweigerd(monkeypatch):
    antwoorden = {"userAbstraction": "unifiedAccount"}
    monkeypatch.setattr(bh, "_info", lambda body: antwoorden[body["type"]])
    b = bh.BasisHype.__new__(bh.BasisHype)
    b.adres = "0xabc"
    with pytest.raises(RuntimeError, match="unified"):
        bh.BasisHype.toestand(b)
