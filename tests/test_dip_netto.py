"""Netto-resultaat dip-koper uit HL: met de hand uitgerekende getallen."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import dip_netto  # noqa: E402

D1 = 1788998400000      # 2026-09-10T00:00:00Z
FILL = [{"time": D1, "closedPnl": "0", "fee": "0", "tid": 1}]


def _fund(t, usdc="-1", coin="xyz:A"):
    return {"time": t, "delta": {"type": "funding", "coin": coin, "usdc": usdc}}


def _nep(fills=(), funding=(), posities=0):
    def post(body):
        if body["type"] == "clearinghouseState":
            return {"assetPositions": [{"position": {"szi": "1"}}] * posities}
        return list(fills if body["type"] == "userFillsByTime" else funding)
    return post


def test_netto_is_gerealiseerd_min_fees_plus_funding():
    fills = [{"time": D1 + 1000, "closedPnl": "10", "fee": "0.5", "tid": 1}]
    assert dip_netto.netto_per_dag(fills, [_fund(D1 + 2000, "-2")]) == {"2026-09-10": 7.5}


def test_ontvangen_funding_telt_op_en_andere_regels_niet():
    funding = [_fund(D1, "1.5"), {"time": D1, "delta": {"type": "deposit", "usdc": "1000"}}]
    assert dip_netto.netto_per_dag([], funding) == {"2026-09-10": 1.5}


def test_datum_is_utc():
    laat = D1 + 86400000 - 1
    assert list(dip_netto.netto_per_dag([{"time": laat, "closedPnl": "1", "fee": "0"}], [])) == ["2026-09-10"]


def test_cumulatief_telt_een_dag_pas_de_nacht_erna():
    uit = dip_netto.cumulatief({"2026-09-11": 3.0}, "2026-09-10", "2026-09-13")
    assert uit == {"2026-09-10": 0.0, "2026-09-11": 0.0, "2026-09-12": 3.0, "2026-09-13": 3.0}


@pytest.mark.parametrize("waarde", ["nan", "inf"])
def test_niet_eindig_wordt_geweigerd(waarde):
    with pytest.raises(ValueError):
        dip_netto.netto_per_dag([{"time": D1, "closedPnl": waarde, "fee": "0"}], [])


@pytest.mark.parametrize("fill", [{"time": D1, "fee": "0"}, {"time": D1, "closedPnl": None, "fee": "0"},
                                  {"time": D1, "closedPnl": "1"}])
def test_ontbrekend_veld_is_een_fout_geen_nul(fill):
    with pytest.raises((KeyError, TypeError)):
        dip_netto.netto_per_dag([fill], [])


def test_ontbrekend_funding_bedrag_is_een_fout_geen_nul():
    with pytest.raises(KeyError):
        dip_netto.netto_per_dag([], [{"time": D1, "delta": {"type": "funding"}}])


def test_pagineert_tot_de_laatste_pagina(monkeypatch):
    paginas = [[_fund(D1 + i) for i in range(500)], [_fund(D1 + 600)]]
    starts = []

    def post(body):
        if body["type"] == "clearinghouseState":
            return {"assetPositions": []}
        if body["type"] == "userFillsByTime":
            return []
        starts.append(body["startTime"])
        return paginas[len(starts) - 1]
    monkeypatch.setattr(dip_netto, "_post", post)
    uit = dip_netto.haal_cumulatief("0xtest", "2026-09-11")
    assert uit["2026-09-11"] == pytest.approx(-501.0)
    assert starts[1] == D1 + 499


def test_regels_met_dezelfde_tijd_over_de_paginagrens_blijven_en_tellen_een_keer(monkeypatch):
    """Rood bij herstart op tijd + 1 (regels weg) en zonder ontdubbelen (regels dubbel)."""
    eerste = [_fund(D1 + i, coin="xyz:A") for i in range(499)] + [_fund(D1 + 500, coin="xyz:A")]
    tweede = [_fund(D1 + 500, coin="xyz:A"), _fund(D1 + 500, coin="xyz:B")]
    aanroepen = []

    def post(body):
        if body["type"] == "clearinghouseState":
            return {"assetPositions": []}
        if body["type"] == "userFillsByTime":
            return []
        aanroepen.append(body["startTime"])
        if len(aanroepen) == 1:
            return eerste
        return [x for x in tweede if x["time"] >= body["startTime"]]
    monkeypatch.setattr(dip_netto, "_post", post)
    assert dip_netto.haal_cumulatief("0xtest", "2026-09-11")["2026-09-11"] == pytest.approx(-501.0)


def test_venster_begint_niet_voor_de_eigen_wallet_en_is_begrensd(monkeypatch):
    monkeypatch.setattr(dip_netto, "_post", _nep(funding=[_fund(D1)]))
    assert min(dip_netto.haal_cumulatief("0xtest", "2026-08-01")) == "2026-07-20"
    assert min(dip_netto.haal_cumulatief("0xtest", "2026-12-31")) == "2026-09-22"


def test_te_lang_ophalen_faalt_luid(monkeypatch):
    monkeypatch.setattr(dip_netto, "_post", _nep(funding=[_fund(D1)]))
    monkeypatch.setattr(dip_netto, "MAX_DUUR_SEC", -1)
    with pytest.raises(TimeoutError):
        dip_netto.haal_cumulatief("0xtest", "2026-09-11")


def test_lege_respons_is_onmeetbaar_geen_nul(monkeypatch):
    monkeypatch.setattr(dip_netto, "_post", _nep())
    with pytest.raises(ValueError):
        dip_netto.haal_cumulatief("0xtest", "2026-09-11")


def test_open_positie_zonder_fills_is_onvolledig(monkeypatch):
    """A1 r2: lege fills met verse funding gaven stil een getal (~$35 te gunstig op Q4)."""
    monkeypatch.setattr(dip_netto, "_post", _nep(funding=[_fund(D1)], posities=1))
    monkeypatch.setattr(dip_netto, "_nu_ms", lambda: D1 + 3600 * 1000)
    with pytest.raises(ValueError):
        dip_netto.haal_cumulatief("0xtest", "2026-09-11")


def test_funding_regel_zonder_type_is_een_fout():
    with pytest.raises(KeyError):
        dip_netto.netto_per_dag([], [{"time": D1, "delta": {"usdc": "-1"}}])


def test_open_positie_met_oude_funding_is_onvolledig(monkeypatch):
    monkeypatch.setattr(dip_netto, "_post", _nep(fills=FILL, funding=[_fund(D1)], posities=1))
    monkeypatch.setattr(dip_netto, "_nu_ms", lambda: D1 + 27 * 3600 * 1000)
    with pytest.raises(ValueError):
        dip_netto.haal_cumulatief("0xtest", "2026-09-11")


def test_open_positie_met_verse_funding_is_goed(monkeypatch):
    monkeypatch.setattr(dip_netto, "_post", _nep(fills=FILL, funding=[_fund(D1)], posities=1))
    monkeypatch.setattr(dip_netto, "_nu_ms", lambda: D1 + 25 * 3600 * 1000)
    assert dip_netto.haal_cumulatief("0xtest", "2026-09-11")["2026-09-11"] == pytest.approx(-1.0)


def test_kortstondige_storing_wordt_overbrugd(monkeypatch):
    goed = _nep(funding=[_fund(D1)])
    fouten = []

    def post(body):
        if not fouten:
            fouten.append(1)
            raise OSError("even weg")
        return goed(body)
    monkeypatch.setattr(dip_netto, "_post", post)
    monkeypatch.setattr(dip_netto, "HERHAAL_PAUZE_SEC", 0)
    assert dip_netto.haal_cumulatief("0xtest", "2026-09-11")["2026-09-11"] == pytest.approx(-1.0)
    assert fouten == [1]


def test_aanhoudende_storing_gaat_door(monkeypatch):
    def post(body):
        raise OSError("weg")
    monkeypatch.setattr(dip_netto, "_post", post)
    monkeypatch.setattr(dip_netto, "HERHAAL_PAUZE_SEC", 0)
    with pytest.raises(OSError):
        dip_netto.haal_cumulatief("0xtest", "2026-09-11")
