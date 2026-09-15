"""Kapitaalstromen: een overboeking is geen winst en geen verlies."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import flows  # noqa: E402


def _proposals():
    return [
        {"id": "A", "type": "DEPLOY_YIELD", "status": "DEPLOYED", "source": "hl",
         "amount_usd": 300.0, "source_hl": 250.0, "updated_at": "2026-09-01T10:00:00"},
        {"id": "B", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 100.0,
         "updated_at": "2026-09-02T10:00:00+00:00"},
        {"id": "C", "type": "FUND_SLEEVE", "status": "DEPLOYED", "amount_usd": 50.0,
         "deployed_at": "2026-09-03T10:00:00"},
        {"id": "D", "type": "SLEEVE_REBALANCE", "status": "DEPLOYED", "amount_usd": 20.0,
         "deployed_at": "2026-09-04T10:00:00"},
        {"id": "E", "type": "DEPLOY_YIELD", "status": "PENDING", "source_hl": 999.0,
         "created_at": "2026-09-05T10:00:00"},
        {"id": "F", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": float("nan"),
         "updated_at": "2026-09-06T10:00:00"},
    ]


def test_proposals_worden_stromen_alleen_als_het_geld_echt_verplaatst_is():
    stromen = flows.uit_proposals(_proposals())
    bronnen = {s["bron"]: s for s in stromen}
    assert set(bronnen) == {"proposal:A", "proposal:B", "proposal:C", "proposal:D"}, \
        "PENDING en een NaN-bedrag mogen geen stroom worden"
    assert bronnen["proposal:A"]["bedrag_usd"] == 250.0, "DEPLOY_YIELD telt alleen het HL-deel"
    assert (bronnen["proposal:A"]["van"], bronnen["proposal:A"]["naar"]) == ("swarm", "yield_core")
    assert (bronnen["proposal:B"]["van"], bronnen["proposal:B"]["naar"]) == ("yield_core", "swarm")


def test_netto_flow_telt_richting_en_venster():
    stromen = flows.uit_proposals(_proposals())
    t = flows._epoch
    alles = (t("2026-08-31T00:00:00"), t("2026-09-30T00:00:00"))
    assert flows.netto_flow(stromen, "yield_core", *alles) == pytest.approx(250.0 - 100.0)
    assert flows.netto_flow(stromen, "swarm", *alles) == pytest.approx(-250 + 100 - 50 + 20)
    # Venster (t0, t1]: stroom A op 09-01 10:00 valt buiten (09-01 10:00, ...]
    assert flows.netto_flow(stromen, "yield_core", t("2026-09-01T10:00:00"),
                            t("2026-09-30T00:00:00")) == pytest.approx(-100.0)


def test_kasbeheer_onderweg():
    assert flows.kasbeheer_onderweg([{"status": "BRIDGED"}]) is True
    assert flows.kasbeheer_onderweg(_proposals()) is False


def test_boek_flow_schrijft_in_place_en_weigert_onzin(tmp_path):
    pad = str(tmp_path / "data" / "flows.json")
    flows.boek_flow("extern", "tradfi", 250, "storting DeGiro", ts=1789000000, pad=pad)
    flows.boek_flow("yield_core", "house", 500, "HLP-inleg", ts=1789000100, pad=pad)
    with open(pad, encoding="utf-8") as fh:
        assert len(json.load(fh)["flows"]) == 2
    stromen = flows.laad_flows(proposals_pad=str(tmp_path / "bestaat_niet.json"),
                               handmatig_pad=pad)
    assert flows.netto_flow(stromen, "house", 0, 2e9) == 500
    for fout in ((0, "nul"), (float("nan"), "nan"), (-5, "negatief")):
        with pytest.raises(ValueError):
            flows.boek_flow("extern", "tradfi", fout[0], fout[1], pad=pad)
    with pytest.raises(ValueError):
        flows.boek_flow("house", "house", 10, "zelfde potje", pad=pad)


def test_corrupt_bestand_faalt_luid(tmp_path):
    pad = tmp_path / "flows.json"
    pad.write_text("{kapot", encoding="utf-8")
    with pytest.raises(flows.FlowsOnleesbaar):
        flows.laad_flows(proposals_pad=str(tmp_path / "nee.json"), handmatig_pad=str(pad))
