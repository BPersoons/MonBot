"""scripts/dipkoper_resultaat.py: optelling per munt uit Hyperliquid-fills en funding."""

import math

from scripts import dipkoper_resultaat as d


def test_per_munt_telt_rondes_fees_en_funding():
    fills = [
        {"coin": "xyz:CRCL", "closedPnl": "0.0", "fee": "0.01", "time": 1},
        {"coin": "xyz:CRCL", "closedPnl": "4.71", "fee": "0.01", "time": 2},   # ronde 1
        {"coin": "xyz:CRCL", "closedPnl": "0.0", "fee": "0.01", "time": 3},
        {"coin": "xyz:CRCL", "closedPnl": "2.83", "fee": "0.01", "time": 4},   # ronde 2
        {"coin": "xyz:CRWV", "closedPnl": "-3.17", "fee": "0.0", "time": 5},
    ]
    funding = [
        {"time": 6, "delta": {"type": "funding", "coin": "xyz:CRCL", "usdc": "-0.14"}},
        {"time": 7, "delta": {"type": "deposit", "usdc": "100"}},              # geen funding
    ]
    per, t = d.per_munt(fills, funding)
    assert math.isclose(per["xyz:CRCL"]["gerealiseerd"], 7.54)
    assert per["xyz:CRCL"]["sluitingen"] == 2
    assert math.isclose(per["xyz:CRCL"]["funding"], -0.14)
    assert math.isclose(t["gerealiseerd"], 4.37)
    assert math.isclose(t["fees"], 0.04)
    assert math.isclose(t["funding"], -0.14)


def test_pagineren_gaat_door_tot_een_onvolle_pagina(monkeypatch):
    paginas = [[{"time": 1}, {"time": 2}], [{"time": 3}], []]
    gevraagd = []

    def nep(body):
        gevraagd.append(body["startTime"])
        return paginas[len(gevraagd) - 1]

    monkeypatch.setattr(d, "_post", nep)
    assert [x["time"] for x in d._alles("userFunding", "0xabc", 0, 2)] == [1, 2, 3]
    assert gevraagd == [0, 3]
