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
    # Kosten horen bij de BEGINdatum van het interval (snapshot om 00:05 = gisteren).
    kosten = {"2026-09-10": 0.44, "2026-09-11": 0.44}
    aave = {"2026-09-11": 2.5, "2026-09-12": 2.7}
    dip = {"2026-09-10": 20.0, "2026-09-11": 20.0, "2026-09-12": 23.5}
    uit = kpi.bereken(hist, stromen, register, kosten, aave, dip, {}, "2026-09-12")
    h1, h2 = uit["h1"], uit["h2"]
    assert h1["per_potje_usd"]["yield_core"] == 2.0
    assert h1["dip_koper_netto_usd"] == 3.5
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


def test_gat_in_de_reeks_telt_alle_kosten_van_het_gat(register):
    """A1-audit ronde 2: mist de snapshot van 09-11, dan horen beide kostendagen erbij."""
    hist = [_snap(0, yield_core=1000.0), _snap(2, yield_core=1002.0)]
    kosten = {"2026-09-10": 0.44, "2026-09-11": 0.44}
    uit = kpi.bereken(hist, [], register, kosten, {}, {}, {}, "2026-09-12")
    assert uit["h1"]["kosten_usd"] == 0.88 and uit["h1"]["opbrengst_usd"] == 2.0


def _live(register, naam="hlp_vault", **velden):
    """Kopie van het echte register met één experiment op live (schema blijft gelden)."""
    r = json.loads(json.dumps(register))
    r["experimenten"][naam].update({"status": "live"}, **velden)
    return r


def test_h3_experimentverlies_negeert_de_inleg(register):
    # house: 0 -> 500 (inleg, geen winst) -> 480 (verlies 20)
    from datetime import datetime, timezone
    hist = [_snap(0, house=0.0), _snap(1, house=500.0), _snap(2, house=480.0)]
    stromen = [{"ts": T0 + 3600, "van": "yield_core", "naar": "house", "bedrag_usd": 500.0}]
    start = datetime.fromtimestamp(T0, timezone.utc).isoformat()
    uit = kpi.bereken(hist, stromen, _live(register, verlies_meten_vanaf=start),
                      {}, {}, {}, {}, "2026-09-12")
    assert uit["h3"]["per_experiment_usd"]["hlp_vault"] == 20.0
    assert uit["h3"]["verlies_usd"] == 20.0 and uit["h3"]["doel_gehaald"]


def test_h3_telt_een_experiment_dat_nog_niet_leeft_niet_mee(register):
    """Productiefout 2026-09-16: `house` bestond al, dus H3 meldde $1.087 op HLP-in-spe."""
    hist = [_snap(0, house=1500.0), _snap(1, house=1000.0), _snap(2, house=400.0)]
    # alleen de experimenten die nog niet leven (basis_hype staat sinds 08-10 live)
    register = {**register, "experimenten": {k: v for k, v in register["experimenten"].items()
                                              if v.get("status") != "live"}}
    uit = kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-12")
    assert uit["h3"]["per_experiment_usd"] == {}
    assert uit["h3"]["verlies_usd"] == 0.0 and uit["h3"]["doel_gehaald"]


def test_h3_live_zonder_startdatum_is_onmeetbaar_geen_getal(register):
    """Zonder startdatum erft het experiment de hele historie — dat gaf de $1.087,80."""
    hist = [_snap(0, house=1087.8), _snap(1, house=1086.5), _snap(2, house=0.0)]
    r = _live(register)
    r["experimenten"]["basis_hype"]["status"] = "idee"   # live sinds 08-10; hier alleen HLP
    uit = kpi.bereken(hist, [], r, {}, {}, {}, {}, "2026-09-12")
    assert uit["h3"]["per_experiment_usd"] == {}, "geen getal"
    assert "experimentverlies:hlp_vault" in uit["h5"]["onmeetbaar"]
    assert not uit["h5"]["doel_gehaald"]


def test_geld_in_een_niet_live_experiment_wordt_gemarkeerd(register):
    """De stille nul in de andere richting: het budget bewaakt dan niets."""
    hist = [_snap(0, house=500.0), _snap(1, house=480.0)]
    uit = kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-11")
    assert "experiment_niet_live:hlp_vault" in uit["h5"]["onmeetbaar"]
    # leeg potje = niets aan de hand
    leeg = kpi.bereken([_snap(0, house=0.0), _snap(1, house=0.0)], [], register,
                       {}, {}, {}, {}, "2026-09-11")
    assert leeg["h5"]["onmeetbaar"] == []


def test_productiestand_basis_geeft_geen_valse_h5(register):
    """Productie 2026-10-12: basis_traag (uit) deelde potje `basis` met basis_hype (live).
    De $115 van basis_hype zette H5 op rood als 'experiment_niet_live:basis_traag'.
    Opgelost in het register (eigen potje), niet met een uitzondering in de KPI."""
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(T0, timezone.utc).isoformat()
    r = _live(register, naam="basis_hype", verlies_meten_vanaf=start)
    hist = [_snap(0, basis=115.0), _snap(1, basis=115.0)]
    uit = kpi.bereken(hist, [], r, {}, {}, {}, {}, "2026-09-11")
    assert not any(m.startswith("experiment_niet_live") for m in uit["h5"]["onmeetbaar"])
    assert uit["h3"]["per_experiment_usd"]["basis_hype"] == 0.0
    # Staat basis_hype zelf niet live, dan is hetzelfde geld wel onbewaakt.
    r["experimenten"]["basis_hype"]["status"] = "gepland"
    uit = kpi.bereken(hist, [], r, {}, {}, {}, {}, "2026-09-11")
    assert "experiment_niet_live:basis_hype" in uit["h5"]["onmeetbaar"]


def test_h3_meet_pas_vanaf_de_startdatum_van_het_experiment(register):
    """Verlies van vóór de start telt niet mee — anders erft het experiment oude historie."""
    hist = [_snap(0, house=1000.0), _snap(1, house=600.0), _snap(2, house=550.0)]
    from datetime import datetime, timezone
    start = datetime.fromtimestamp(T0 + DAG, timezone.utc).isoformat()
    uit = kpi.bereken(hist, [], _live(register, verlies_meten_vanaf=start),
                      {}, {}, {}, {}, "2026-09-12")
    assert uit["h3"]["per_experiment_usd"]["hlp_vault"] == 50.0, "alleen 600 -> 550"


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


def _ms(iso):
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


EEN_FUNDING = [{"time": 1788998400000, "delta": {"type": "funding", "coin": "xyz:A", "usdc": "0"}}]


def _hl_nep(fills=(), funding=EEN_FUNDING):
    """Vervangt alleen het netwerk: de hele keten erboven blijft echt."""
    def post(body):
        if body["type"] == "clearinghouseState":
            return {"assetPositions": []}
        return list(fills if body["type"] == "userFillsByTime" else funding)
    return post


def _dip_omgeving(monkeypatch, post):
    from utils import dip_netto
    import utils.gcp_secrets as sec
    monkeypatch.setattr(dip_netto, "_post", post)
    monkeypatch.setattr(dip_netto, "HERHAAL_PAUZE_SEC", 0)
    monkeypatch.setattr(sec, "get_secret", lambda naam, *a, **k: "0xtest")


def _aave_bekend(tmp_path):
    (tmp_path / "treasury_state.json").write_text(json.dumps({"opportunities": [
        {"protocol_config": {"id": "aave-v3-arbitrum-usdc"}, "apy": 2.5}]}), encoding="utf-8")


def test_dip_koper_telt_netto_uit_hyperliquid_niet_uit_het_boek(tmp_path, monkeypatch, register):
    """Rood zodra fees, funding of de bron (HL i.p.v. eigen boek) terugvalt."""
    from datetime import datetime, timezone
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sleeve_nav.json").write_text(json.dumps(
        {"history": [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.0),
                     _snap(2, yield_core=1000.0)]}), encoding="utf-8")
    (tmp_path / "cost_log.json").write_text(json.dumps(
        {"history": {"2026-09-10": {"total_cost_usd": 0.5}, "2026-09-11": {"total_cost_usd": 0.5}}}),
        encoding="utf-8")
    # Het eigen boek zegt +99: mag H1 niet bereiken.
    (tmp_path / "thematic_exposure_positions.json").write_text(
        json.dumps({"realized_pnl_usd": 99.0}), encoding="utf-8")
    monkeypatch.setattr(kpi, "REGISTER_FILE", os.path.join(REPO, "config", "experimenten.json"))
    fills = [{"time": _ms("2026-09-10T12:00:00"), "closedPnl": "10.0", "fee": "0.25", "tid": 1},
             {"time": _ms("2026-09-11T12:00:00"), "closedPnl": "-4.0", "fee": "0.25", "tid": 2}]
    funding = [{"time": _ms("2026-09-10T13:00:00"), "delta": {"type": "funding", "usdc": "-1.0"}},
               {"time": _ms("2026-09-11T13:00:00"), "delta": {"type": "funding", "usdc": "-0.5"}}]
    _dip_omgeving(monkeypatch, _hl_nep(fills, funding))
    _aave_bekend(tmp_path)
    regel = kpi.update_kpi(nu=datetime(2026, 9, 12, 0, 10, tzinfo=timezone.utc),
                           kpi_pad=str(tmp_path / "data" / "kpi.json"))
    # (10 - 0,25 - 1) + (-4 - 0,25 - 0,5) = 8,75 - 4,75 = 4,00 over BEIDE dagen van het venster
    assert regel["h1"]["dip_koper_netto_usd"] == 4.0
    assert regel["h1"]["opbrengst_usd"] == 4.0 and regel["h1"]["netto_usd"] == 3.0
    assert regel["dip_gerealiseerd_usd"] == 99.0     # het boek blijft alleen ter vergelijking
    assert regel["h5"]["doel_gehaald"]


def test_dip_koper_onbereikbaar_is_onmeetbaar_geen_nul(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sleeve_nav.json").write_text(json.dumps(
        {"history": [_snap(0, yield_core=1000.0), _snap(1, yield_core=1001.0)]}), encoding="utf-8")
    (tmp_path / "cost_log.json").write_text(json.dumps(
        {"history": {"2026-09-10": {"total_cost_usd": 0.5}}}), encoding="utf-8")
    monkeypatch.setattr(kpi, "REGISTER_FILE", os.path.join(REPO, "config", "experimenten.json"))

    def stuk(body):
        raise OSError("HL onbereikbaar")
    _dip_omgeving(monkeypatch, stuk)
    _aave_bekend(tmp_path)
    regel = kpi.update_kpi(nu=datetime(2026, 9, 11, 0, 10, tzinfo=timezone.utc),
                           kpi_pad=str(tmp_path / "data" / "kpi.json"))
    h1 = regel["h1"]
    assert h1["netto_usd"] is None and h1["opbrengst_usd"] is None and h1["dip_koper_netto_usd"] is None
    assert not h1["doel_gehaald"]
    assert "dip_koper_netto" in regel["h5"]["onmeetbaar"] and not regel["h5"]["doel_gehaald"]
    # De rente hangt niet af van HL: H2 blijft staan.
    assert regel["h2"]["verschil_pp"] is not None


def test_dip_venster_begint_bij_de_beginsnapshot(register):
    """Zonder dit valt de eerste dag van het venster weg (de oude fout: 84 van 85 dagen)."""
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.0), _snap(2, yield_core=1000.0)]
    kosten = {"2026-09-10": 0.5, "2026-09-11": 0.5}
    dip = {"2026-09-10": 0.0, "2026-09-11": 7.0, "2026-09-12": 9.0}
    uit = kpi.bereken(hist, [], register, kosten, {}, dip, {}, "2026-09-12")
    assert uit["h1"]["dip_koper_netto_usd"] == 9.0


def test_nan_in_het_boek_blokkeert_de_kpi_niet(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sleeve_nav.json").write_text(json.dumps(
        {"history": [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.0)]}), encoding="utf-8")
    (tmp_path / "cost_log.json").write_text(json.dumps(
        {"history": {"2026-09-10": {"total_cost_usd": 0.5}}}), encoding="utf-8")
    (tmp_path / "thematic_exposure_positions.json").write_text('{"realized_pnl_usd": NaN}', encoding="utf-8")
    monkeypatch.setattr(kpi, "REGISTER_FILE", os.path.join(REPO, "config", "experimenten.json"))
    _dip_omgeving(monkeypatch, _hl_nep())
    regel = kpi.update_kpi(nu=datetime(2026, 9, 11, 0, 10, tzinfo=timezone.utc),
                           kpi_pad=str(tmp_path / "data" / "kpi.json"))
    assert regel["dip_gerealiseerd_usd"] is None and regel["h1"]["netto_usd"] is not None


def test_dag_zonder_kosten_telt_ook_niet_voor_de_dip_koper(register):
    """Rood bij een verschil van eerste tot laatste dag: dan telt de winst van de gat-dag mee."""
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.0), _snap(2, yield_core=1000.0),
            _snap(3, yield_core=1000.0)]
    kosten = {"2026-09-10": 0.5, "2026-09-12": 0.5}     # 09-11 ontbreekt
    dip = {"2026-09-10": 0.0, "2026-09-11": 1.0, "2026-09-12": 10.0, "2026-09-13": 12.0}
    h1 = kpi.bereken(hist, [], register, kosten, {}, dip, {}, "2026-09-13")["h1"]
    assert h1["dagen"] == 2 and h1["kosten_usd"] == 1.0
    assert h1["dip_koper_netto_usd"] == 3.0     # 1 + 2, zonder de +9 van de gat-dag


def test_reeks_met_een_ontbrekende_datum_is_onmeetbaar(register):
    """De oude fout: een reeks die later begint dan het venster gaf stil te weinig."""
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.0), _snap(2, yield_core=1000.0)]
    kosten = {"2026-09-10": 0.5, "2026-09-11": 0.5}
    uit = kpi.bereken(hist, [], register, kosten, {}, {"2026-09-11": 2.0, "2026-09-12": 9.0}, {}, "2026-09-12")
    assert uit["h1"]["netto_usd"] is None and uit["h1"]["opbrengst_usd"] is None
    assert uit["h1"]["dip_koper_netto_usd"] is None and not uit["h1"]["doel_gehaald"]
    assert "dip_koper_reeks:2026-09-11" in uit["h5"]["onmeetbaar"]


def test_kosten_blijven_bewaard_als_cost_log_ze_kwijt_is(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    _dip_omgeving(monkeypatch, _hl_nep())
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "sleeve_nav.json").write_text(json.dumps(
        {"history": [_snap(0, yield_core=1000.0), _snap(1, yield_core=1000.5)]}), encoding="utf-8")
    # cost_log kent 09-10 niet meer (rolt na 30 dagen); kpi.json heeft hem nog.
    (tmp_path / "cost_log.json").write_text(json.dumps(
        {"history": {"2026-09-11": {"total_cost_usd": 0.44}}}), encoding="utf-8")
    kpi_pad = tmp_path / "data" / "kpi.json"
    kpi_pad.write_text(json.dumps({"history": [], "kosten_per_dag": {"2026-09-10": 0.40}}),
                       encoding="utf-8")
    monkeypatch.setattr(kpi, "REGISTER_FILE", os.path.join(REPO, "config", "experimenten.json"))
    regel = kpi.update_kpi(nu=datetime(2026, 9, 11, 0, 10, tzinfo=timezone.utc), kpi_pad=str(kpi_pad))
    assert regel["h1"]["dagen"] == 1 and regel["h1"]["kosten_usd"] == 0.40
    opgeslagen = json.loads(kpi_pad.read_text(encoding="utf-8"))
    assert opgeslagen["kosten_per_dag"] == {"2026-09-10": 0.40, "2026-09-11": 0.44}


def test_nan_wordt_geweigerd(register):
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=float("nan"))]
    with pytest.raises(ValueError):
        kpi.bereken(hist, [], register, {"2026-09-10": 0.44}, {}, {}, {}, "2026-09-11")


def test_nan_op_een_dag_zonder_kosten_wordt_ook_geweigerd(register):
    """Zonder de scan vooraf sloeg de lus deze dag over en las de NaN nooit."""
    hist = [_snap(0, yield_core=1000.0), _snap(1, yield_core=float("nan"))]
    with pytest.raises(ValueError):
        kpi.bereken(hist, [], register, {}, {}, {}, {}, "2026-09-11")
