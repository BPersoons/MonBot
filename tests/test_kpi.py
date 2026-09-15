"""KPI's met met de hand uitgerekende getallen — geen herhaling van de formule."""
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from utils import kpi  # noqa: E402

T0 = 1788998400.0   # 2026-09-10T00:00:00Z
DAG = 86400.0


def _snap(dag, **potjes):
    ts = T0 + dag * DAG
    from datetime import datetime, timezone
    return {"date": datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"),
            "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "sleeves": potjes}


@pytest.fixture(scope="module")
def register():
    with open(os.path.join(REPO, "config", "experimenten.json"), encoding="utf-8") as fh:
        return json.load(fh)


def test_h1_h2_flowgecorrigeerd_met_de_hand(register):
    # yield_core: 1000 -> 1001 (winst 1) -> 1502 met +500 instroom (winst 1)
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=1001.0),
            _snap(2, yield_core=1502.0)]
    stromen = [{"ts": T0 + DAG + 3600, "van": "swarm", "naar": "yield_core", "bedrag_usd": 500.0}]
    kosten = {"2026-09-11": 0.44, "2026-09-12": 0.44}
    aave = {"2026-09-11": 2.5, "2026-09-12": 2.7}
    dip = {"2026-09-11": 20.0, "2026-09-12": 23.5}
    uit = kpi.bereken(hist, stromen, register, kosten, aave, dip, {}, "2026-09-12")
    h1, h2 = uit["h1"], uit["h2"]
    assert h1["per_potje_usd"]["yield_core"] == 2.0
    assert h1["dip_koper_gerealiseerd_usd"] == 3.5
    assert h1["opbrengst_usd"] == 5.5 and h1["kosten_usd"] == 0.88
    assert h1["netto_usd"] == 4.62 and h1["doel_gehaald"] and h1["voorlopig"]
    # r1 = 1/1000, r2 = 1/(1001 + 250) ; groei over 2 dagen, geannualiseerd
    groei = (1 + 1 / 1000) * (1 + 1 / 1251)
    verwacht = (groei ** (365 / 2) - 1) * 100
    assert h2["rendement_jaar_pct"] == pytest.approx(round(verwacht, 2))
    assert h2["aave_apy_pct"] == 2.6


def test_dag_zonder_kosten_telt_niet_mee(register):
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=1010.0)]
    uit = kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-11")
    assert uit["h1"]["dagen"] == 0 and uit["h1"]["opbrengst_usd"] == 0.0
    assert uit["h2"]["rendement_jaar_pct"] is None


def test_h3_experimentverlies_negeert_de_inleg(register):
    # house: 0 -> 500 (inleg, geen winst) -> 480 (verlies 20)
    hist = [_snap(0, house=0.0), _snap(1, house=500.0), _snap(2, house=480.0)]
    stromen = [{"ts": T0 + 3600, "van": "yield_core", "naar": "house", "bedrag_usd": 500.0}]
    uit = kpi.bereken(hist, stromen, register, {}, {}, {}, {}, "2026-09-12")
    assert uit["h3"]["per_experiment_usd"]["hlp_vault"] == 20.0
    assert uit["h3"]["verlies_usd"] == 20.0 and uit["h3"]["doel_gehaald"]


def test_h4_leest_de_brandoefening(register):
    hist = [_snap(0, yield_core=1.0)]
    goed = {"laatste_oefening": {"detectie_min": 4.0, "alles_gevonden": True}}
    assert kpi.bereken(hist, [], register, {}, {}, {}, goed, "2026-09-10")["h4"]["doel_gehaald"]
    traag = {"laatste_oefening": {"detectie_min": 14.0, "alles_gevonden": True}}
    assert not kpi.bereken(hist, [], register, {}, {}, {}, traag, "2026-09-10")["h4"]["doel_gehaald"]
    assert not kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-10")["h4"]["doel_gehaald"]


def test_h5_telt_gaten_vanaf_de_eerste_meting(register):
    hist = [_snap(0, yield_core=1.0), _snap(1, yield_core=1.0), _snap(4, yield_core=1.0)]
    uit = kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-14")
    assert uit["h5"]["gaten"] == ["2026-09-12", "2026-09-13"]
    assert not uit["h5"]["doel_gehaald"]


def test_nan_wordt_geweigerd(register):
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=float("nan"))]
    with pytest.raises(ValueError):
        kpi.bereken(hist, [], register, {"2026-09-11": 0.44}, {}, {}, {}, "2026-09-11")
