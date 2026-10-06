import json
import math
import os

import pytest

from utils import basis_hype as bh
from utils.basis_hype import plan, waarde, hefboom

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def T(spot=0.0, short=0.0, perp=0.0, usdc=0.0, px=40.0):
    return {"spot_hype": spot, "short_hype": short, "perp_av": perp, "spot_usdc": usdc, "px": px}


def stappen(p):
    return [s["stap"] for s in p]


# ── echte HL-gegevens (A1 06-10: nep-objecten verborgen twee blokkerende fouten) ──

def test_perp_symbool_bestaat_via_de_echte_lookup():
    from utils.exchange_client import HyperliquidExchange
    ex = HyperliquidExchange.__new__(HyperliquidExchange)
    with open(os.path.join(FIX, "hl_markets_hype.json"), encoding="utf-8") as fh:
        ex.markets = json.load(fh)
    assert ex._lookup_symbol(bh.PERP_SYMBOL) == "HYPE/USDC:USDC"
    assert ex._lookup_symbol("HYPE") is None          # de oude, foute aanroep
    assert ex._spot_symbol(bh.COIN) == "HYPE/USDC"     # spot via create_spot_order


def test_spotprijs_koppelt_op_coin_niet_op_positie():
    with open(os.path.join(FIX, "hl_spot_ctx.json"), encoding="utf-8") as fh:
        d = json.load(fh)
    echt = [float(c["markPx"]) for c in d["ctx"] if c["coin"] == "@107"][0]
    ctx = list(reversed(d["ctx"])) + [{"coin": "@999", "markPx": "0.01"}]
    assert bh.spotprijs(d["universe"], ctx) == echt
    # de oude zip-koppeling gaf een andere munt
    zip_px = [float(c["markPx"]) for u, c in zip(d["universe"], ctx) if u["name"] == "@107"]
    assert zip_px and zip_px[0] != echt


def test_spotprijs_ontbreekt_is_none():
    assert bh.spotprijs([], [{"coin": "@1", "markPx": "2"}]) is None


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

def test_openen_zet_eerst_marge_dan_spot_dan_short():
    assert stappen(plan(T(usdc=150), 150, 0.00001)) == ["verdeel_kas", "spot_koop", "short_volgt_spot"]


def test_openen_blijft_binnen_2x_kader():
    st = plan(T(usdc=150), 150, 0.00001)
    koop = [s for s in st if s["stap"] == "spot_koop"][0]["usd"]
    assert koop == pytest.approx(90.0)                       # 150 * 1,5 / 2,5
    assert koop / (150 - koop) == pytest.approx(bh.LEV_DOEL)
    assert bh.LEV_MAX <= 2.0 and bh.LEVERAGE_INSTELLING <= 2


def test_niet_openen_zonder_live_register():
    assert stappen(plan(T(usdc=150), 150, 0.0001, live=False)) == ["niets"]


def test_niet_openen_zonder_geboekte_inleg():
    assert stappen(plan(T(usdc=150), 0.0, 0.0001)) == ["niets"]


def test_niet_openen_bij_negatieve_funding():
    assert stappen(plan(T(usdc=150), 150, -0.00001)) == ["niets"]


def test_te_weinig_kapitaal_doet_niets():
    assert stappen(plan(T(usdc=20), 20, 0.0001)) == ["niets"]


def test_onleesbaar_doet_niets():
    t = T(usdc=150)
    t["px"] = None
    assert stappen(plan(t, 150, 0.0001)) == ["niets"]


# ── hedge ─────────────────────────────────────────────────────────────────────

def test_scheve_hedge_met_marge_short_volgt_spot():
    assert stappen(plan(T(spot=2.5, short=2.0, perp=60, px=40), 160, 0.0001)) == ["short_volgt_spot"]


def test_scheve_hedge_zonder_marge_eerst_marge_aanvullen():
    # spot 2,25 HYPE ($90), geen short, marge 0, spot-USDC 60 -> marge eerst
    p = stappen(plan(T(spot=2.25, short=0.0, perp=0, usdc=60, px=40), 150, 0.0001))
    assert p[-2:] == ["verdeel_kas", "short_volgt_spot"]


def test_scheve_hedge_zonder_kas_verkoopt_eerst_spot():
    # alles in spot (marge-overboeking mislukt na de koop): spot terug naar doel
    p = stappen(plan(T(spot=3.75, short=0.0, perp=0, usdc=0, px=40), 150, 0.0001))
    assert p == ["spot_verkoop", "verdeel_kas", "short_volgt_spot"]


def test_kleine_scheefheid_onder_minimum_blijft_staan():
    assert stappen(plan(T(spot=2.25, short=2.2, perp=60, px=40), 150, 0.0001)) == ["niets"]


# ── bijsturen ─────────────────────────────────────────────────────────────────

def test_binnen_band_niets():
    # notional 90, marge 60 -> 1,5x
    assert stappen(plan(T(spot=2.25, short=2.25, perp=60, px=40), 150, 0.0001)) == ["niets"]


def test_koers_omhoog_eerst_short_kleiner_dan_spot_verkopen():
    # px 40 -> 56: notional 126, marge 60-36=24 -> 5,25x
    p = stappen(plan(T(spot=2.25, short=2.25, perp=24, px=56), 150, 0.0001))
    assert p == ["short_kleiner", "spot_verkoop", "verdeel_kas"]


def test_net_boven_2x_stuurt_bij():
    # notional 2,25*40=90, marge 44 -> 2,05x
    assert stappen(plan(T(spot=2.25, short=2.25, perp=44, px=40), 134, 0.0001))[0] == "short_kleiner"


def test_koers_omlaag_eerst_kas_dan_spot_dan_short():
    # px 40 -> 25: notional 56, marge 60+34=94 -> 0,6x
    p = stappen(plan(T(spot=2.25, short=2.25, perp=94, px=25), 150, 0.0001))
    assert p == ["verdeel_kas", "spot_koop", "short_volgt_spot"]


def test_bijsturen_brengt_terug_naar_doel():
    t = T(spot=2.25, short=2.25, perp=24, px=56)
    st = plan(t, 150, 0.0001)
    doel_q = waarde(t) * bh.LEV_DOEL / (1 + bh.LEV_DOEL) / 56
    assert st[0]["qty"] == pytest.approx(2.25 - doel_q)


# ── afbouwen ──────────────────────────────────────────────────────────────────

def test_verlies_van_50_procent_bouwt_af_short_eerst():
    p = stappen(plan(T(spot=1.0, short=1.0, perp=20, px=40), 160, 0.0001))   # waarde 60 < 80
    assert p == ["markeer_afgebouwd", "short_kleiner", "spot_verkoop"]


def test_verlies_net_onder_50_procent_blijft():
    p = stappen(plan(T(spot=2.0, short=2.0, perp=40, px=40), 239, 0.0001))   # waarde 120, 49,8%
    assert "short_kleiner" not in p


def test_negatieve_funding_bouwt_af():
    assert stappen(plan(T(spot=2.25, short=2.25, perp=60, px=40), 150, -0.00001))[:2] == \
        ["markeer_afgebouwd", "short_kleiner"]


def test_onbekende_funding_is_geen_reden_om_af_te_bouwen():
    assert stappen(plan(T(spot=2.25, short=2.25, perp=60, px=40), 150, None)) == ["niets"]


def test_schakelaar_bouwt_af():
    assert stappen(plan(T(spot=2.25, short=2.25, perp=60, px=40), 150, 0.0001, afbouwen=True))[1] == "short_kleiner"


def test_afgebouwd_opent_nooit_meer_ook_niet_bij_goede_funding():
    assert stappen(plan(T(usdc=150), 150, 0.001, afgebouwd="funding 7 dagen negatief")) == ["niets"]


def test_afgebouwd_met_restant_bouwt_verder_af_zonder_opnieuw_te_markeren():
    p = stappen(plan(T(spot=2.0, perp=10, px=40), 150, 0.001, afgebouwd="x"))
    assert p == ["spot_verkoop"]


# ── uitvoering: volgorde en reduceOnly ────────────────────────────────────────

class FakeEx:
    def __init__(self, state):
        self.s = state
        self.orders = []
        self.signing_client = object()

    def create_spot_order(self, coin, side, qty):
        assert coin == bh.COIN
        self.orders.append(("spot", side, qty))
        px = self.s["px"]
        if side == "buy":
            self.s["spot_usdc"] -= qty * px
            self.s["spot_hype"] += qty
        else:
            self.s["spot_usdc"] += qty * px
            self.s["spot_hype"] -= qty
        return {"id": "x"}

    def create_order(self, symbol, side, qty, reduce_only=False, leverage=None, margin_mode=None):
        assert symbol == bh.PERP_SYMBOL and leverage <= 2
        self.orders.append(("perp", side, qty, reduce_only))
        self.s["short_hype"] += qty if side == "sell" else -qty
        return {"id": "y"}


@pytest.fixture
def omgeving(monkeypatch, tmp_path):
    monkeypatch.setattr(bh, "STATE_FILE", str(tmp_path / "data" / "basis_hype_state.json"))
    st = T(usdc=150.0, px=40.0)
    st["withdrawable"] = 0.0
    verplaatst = []

    def verplaats(self, bedrag, van, naar):
        verplaatst.append((round(bedrag, 2), van, naar))
        if van == "spot":
            st["spot_usdc"] -= bedrag
            st["perp_av"] += bedrag
        else:
            st["perp_av"] -= bedrag
            st["spot_usdc"] += bedrag

    def toestand(self):
        st["withdrawable"] = max(0.0, st["perp_av"] - st["short_hype"] * st["px"] / 2)
        return dict(st)

    monkeypatch.setattr(bh.BasisHype, "_verplaats", verplaats)
    monkeypatch.setattr(bh.BasisHype, "toestand", toestand)
    funding = {"v": 0.00001}
    monkeypatch.setattr(bh.BasisHype, "funding_7d", staticmethod(lambda: funding["v"]))
    monkeypatch.setattr(bh.BasisHype, "inleg", staticmethod(lambda: 150.0))
    monkeypatch.setattr(bh, "register_live", lambda pad=None: True)
    import utils.auto_params as ap
    monkeypatch.setattr(ap, "subsysteem_aan", lambda naam, standaard=True: True)
    monkeypatch.setattr(ap.AutoParams, "get_candidate_value", lambda self, k: None)
    ex = FakeEx(st)
    meldingen = []
    b = bh.BasisHype(ex, "0xabc", telegram=meldingen.append)
    return b, ex, st, meldingen, funding, verplaatst


def test_cyclus_opent_gehedged_marge_eerst(omgeving):
    b, ex, st, _, _, verplaatst = omgeving
    b.run_cycle()
    assert verplaatst[0][1:] == ("spot", "")              # marge naar perp vóór de koop
    assert ex.orders[0][:2] == ("spot", "buy")
    assert ex.orders[1][:2] == ("perp", "sell") and ex.orders[1][3] is False
    assert st["short_hype"] == pytest.approx(st["spot_hype"])
    assert st["short_hype"] * 40 / st["perp_av"] == pytest.approx(bh.LEV_DOEL, rel=0.05)


def test_cyclus_schrijft_waarde_weg(omgeving):
    b = omgeving[0]
    b.run_cycle()
    with open(bh.STATE_FILE, encoding="utf-8") as fh:
        d = json.load(fh)
    assert d["waarde_usd"] == pytest.approx(150.0, abs=0.5) and d["inleg_usd"] == 150.0 and d["open"]
    assert bh.lees_state()[0] == d["waarde_usd"]


def test_short_kleiner_is_altijd_reduce_only(omgeving):
    b, ex, st = omgeving[:3]
    b.run_cycle()
    st["px"] = 56.0
    st["perp_av"] -= st["short_hype"] * 16
    ex.orders.clear()
    b.run_cycle()
    perp = [o for o in ex.orders if o[0] == "perp"]
    assert perp and all(o[1] == "buy" and o[3] is True for o in perp)


def test_short_groter_dan_spot_wordt_reduce_only_verkleind(omgeving):
    b, ex, st = omgeving[:3]
    b.run_cycle()
    st["spot_hype"] -= 1.0
    st["spot_usdc"] += 40.0
    ex.orders.clear()
    b.run_cycle()
    assert ex.orders == [("perp", "buy", pytest.approx(1.0, abs=0.01), True)]


def test_afbouwen_is_blijvend_over_drie_cycli(omgeving):
    b, ex, st, meldingen, funding, _ = omgeving
    b.run_cycle()
    funding["v"] = -0.00001
    ex.orders.clear()
    b.run_cycle()                                         # afbouwen
    assert ex.orders[0][0] == "perp" and ex.orders[0][3] is True
    assert ex.orders[1][:2] == ("spot", "sell")
    funding["v"] = 0.001                                  # funding weer positief
    ex.orders.clear()
    b.run_cycle()
    b.run_cycle()
    assert ex.orders == [] and b.state["afgebouwd"] and len(meldingen) == 1


def test_mislukte_short_telt_fouten_en_meldt_een_keer(omgeving):
    b, ex, _, meldingen = omgeving[:4]
    ex.create_order = lambda *a, **k: None
    for _ in range(4):
        b.run_cycle()
    assert b.state["fouten"] == 4 and len(meldingen) == 1


def test_uit_meet_wel_maar_handelt_niet(omgeving, monkeypatch):
    b, ex = omgeving[:2]
    import utils.auto_params as ap
    monkeypatch.setattr(ap, "subsysteem_aan", lambda naam, standaard=True: False)
    s = b.run_cycle()
    assert not ex.orders and s["waarde_usd"] == pytest.approx(150.0)


def test_unified_account_en_onbekende_modus_worden_geweigerd(monkeypatch):
    b = bh.BasisHype.__new__(bh.BasisHype)
    b.adres = "0xabc"
    for modus in ("unifiedAccount", None):
        monkeypatch.setattr(bh, "_info", lambda body, m=modus: m)
        with pytest.raises(RuntimeError, match="modus"):
            bh.BasisHype.toestand(b)


# ── lees_state voor de meetkant ───────────────────────────────────────────────

def test_lees_state_zonder_bestand_is_none(tmp_path):
    assert bh.lees_state(str(tmp_path / "nee.json")) is None


def test_lees_state_kapot_bestand_gooit(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{kapot")
    with pytest.raises(Exception):
        bh.lees_state(str(p))


def test_lees_state_oude_meting_met_open_benen_is_onmeetbaar(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"waarde_usd": 150.0, "open": True, "laatst": "2026-10-07T10:00:00+00:00"}))
    from datetime import datetime
    t0 = datetime.fromisoformat("2026-10-07T10:00:00+00:00").timestamp()
    assert bh.lees_state(str(p), nu=t0 + 600)[0] == 150.0
    assert bh.lees_state(str(p), nu=t0 + 7200)[0] is None


def test_lees_state_oude_meting_zonder_benen_blijft_geldig(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"waarde_usd": 150.0, "open": False, "laatst": "2026-10-01T10:00:00+00:00"}))
    assert bh.lees_state(str(p))[0] == 150.0
