"""De motor (docs/MOTOR.md): treden, stilstand en capaciteit."""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import motor  # noqa: E402

VANDAAG = date(2026, 9, 21)


def _reg(**exps):
    return {"experimenten": exps}


def test_stand_per_trede():
    s = motor.stand(_reg(a={"trede": 0, "status": "idee", "sinds": "2026-09-20"},
                         b={"trede": 3, "status": "live", "sinds": "2026-07-19"}), VANDAAG)
    assert [e["naam"] for e in s["per_trede"][0]] == ["a"]
    assert [e["naam"] for e in s["per_trede"][3]] == ["b"]


def test_idee_dat_langer_dan_een_week_stilstaat_geeft_een_signaal():
    s = motor.stand(_reg(a={"trede": 0, "status": "idee", "sinds": "2026-09-10"},
                         b={"trede": 1, "status": "papier", "sinds": "2026-09-20"}), VANDAAG)
    assert any("a staat 11 dagen op trede 0" in x for x in s["signalen"])


def test_wachten_op_een_regime_of_op_bart_is_geen_stilstand():
    s = motor.stand(_reg(a={"trede": 1, "status": "wacht_op_regime", "sinds": "2026-08-01"},
                         b={"trede": 0, "status": "idee", "sinds": "2026-09-20"}), VANDAAG)
    assert not any("wacht" in x or " a " in x for x in s["signalen"])


def test_live_experimenten_tellen_niet_als_stilstand():
    """Een proeftuin-experiment staat bewust lang op trede 3 — dat is meten, geen stilstand."""
    s = motor.stand(_reg(a={"trede": 3, "status": "live", "sinds": "2026-07-19", "budget_usd": 100},
                         b={"trede": 0, "status": "idee", "sinds": "2026-09-20"},
                         c={"trede": 1, "status": "papier", "sinds": "2026-09-20"}), VANDAAG)
    assert s["signalen"] == []


def test_proeftuin_begrensd_door_kapitaal_niet_door_aantal():
    """Bart 22-09: geen vast maximum; $500 kapitaal begrenst (docs/MOTOR.md spelregel 2)."""
    basis = {"i": {"trede": 0, "status": "idee", "sinds": "2026-09-20"},
             "p": {"trede": 1, "status": "papier", "sinds": "2026-09-20"}}
    vijf = {"e%d" % n: {"trede": 3, "status": "live", "sinds": "2026-09-01", "budget_usd": 100} for n in range(5)}
    reg = {"globaal": {"proeftuin_kapitaal_usd": 500}, "experimenten": dict(basis, **vijf)}
    assert motor.stand(reg, VANDAAG)["signalen"] == []                 # 5 x $100 = precies $500
    reg["experimenten"]["e5"] = {"trede": 3, "status": "live", "sinds": "2026-09-01", "budget_usd": 1}
    assert any("$501 ingezet, kapitaal $500" in x for x in motor.stand(reg, VANDAAG)["signalen"])


def test_proeftuin_zonder_budget_wordt_gemeld():
    reg = {"experimenten": {"x": {"trede": 3, "status": "live", "sinds": "2026-09-01"},
                            "i": {"trede": 0, "status": "idee", "sinds": "2026-09-20"},
                            "p": {"trede": 1, "status": "papier", "sinds": "2026-09-20"}}}
    assert any("x staat op de proeftuin zonder geldig budget_usd" in x for x in motor.stand(reg, VANDAAG)["signalen"])


def test_lege_eerste_treden_betekenen_dat_de_motor_droogloopt():
    s = motor.stand(_reg(a={"trede": 3, "status": "live", "sinds": "2026-09-01"}), VANDAAG)
    assert any("trede 0 (idee) is leeg" in x for x in s["signalen"])
    assert any("trede 1 (papier) is leeg" in x for x in s["signalen"])


def test_idee_met_een_potje_waarschuwt_voor_een_vals_h5_signaal():
    s = motor.stand(_reg(a={"trede": 0, "status": "idee", "sinds": "2026-09-20", "sleeve": "house"},
                         b={"trede": 1, "status": "papier", "sinds": "2026-09-20"}), VANDAAG)
    assert any("a is een idee maar heeft een potje" in x for x in s["signalen"])


def test_gepland_experiment_mag_zijn_doelpotje_dragen():
    """Trede 1+ draagt bewust een potje; de KPI bewaakt of daar geld in staat."""
    s = motor.stand(_reg(a={"trede": 1, "status": "gepland", "sinds": "2026-09-20", "sleeve": "house"},
                         b={"trede": 0, "status": "idee", "sinds": "2026-09-20"}), VANDAAG)
    assert not any("potje" in x for x in s["signalen"])


def test_ongeldige_trede_en_ontbrekende_datum_worden_gemeld():
    s = motor.stand(_reg(a={"trede": 9, "status": "idee"},
                         b={"trede": 0, "status": "idee"},
                         c={"trede": 1, "status": "papier", "sinds": "2026-09-20"}), VANDAAG)
    assert any("a heeft geen geldige trede" in x for x in s["signalen"])
    assert any("b: geen datum" in x for x in s["signalen"])


def test_het_echte_register_is_geldig():
    """Elke regel in config/experimenten.json heeft een trede, en ideeën houden geen geld."""
    pad = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "experimenten.json")
    with open(pad, encoding="utf-8") as fh:
        reg = json.load(fh)
    s = motor.stand(reg, VANDAAG)
    assert s["zonder_trede"] == []
    assert not any("potje" in x for x in s["signalen"])


def test_vooruitmeting_is_geen_stilstand_tot_de_herzien_datum():
    """Een schaduwsignaal wacht op maandsloten; pas na de herzien-datum moet het verder."""
    basis = {"b": {"trede": 0, "status": "idee", "sinds": "2026-09-20"},
             "c": {"trede": 1, "status": "papier", "sinds": "2026-09-20"}}
    s = motor.stand(_reg(a={"trede": 2, "status": "meet_vooruit", "sinds": "2026-08-01",
                            "herzien": "2026-11-03"}, **basis), VANDAAG)
    assert s["signalen"] == []
    s = motor.stand(_reg(a={"trede": 2, "status": "meet_vooruit", "sinds": "2026-08-01",
                            "herzien": "2026-11-03"}, **basis), date(2026, 11, 4))
    assert any("herzien-datum" in x for x in s["signalen"])
    s = motor.stand(_reg(a={"trede": 2, "status": "meet_vooruit", "sinds": "2026-09-20"}, **basis), VANDAAG)
    assert any("geen 'herzien'" in x for x in s["signalen"])


def test_gestopt_is_geen_stilstand_en_vult_geen_trede():
    """Een gestopte papiertoets is klaar. Staat er verder niets op papier, dan loopt de motor droog."""
    s = motor.stand(_reg(a={"trede": 1, "status": "gestopt", "sinds": "2026-08-01"},
                         b={"trede": 0, "status": "idee", "sinds": "2026-09-20"}), VANDAAG)
    assert not any(x.startswith("a ") for x in s["signalen"])
    assert s["gestopt"] == ["a"] and s["per_trede"][1] == []
    assert any("trede 1 (papier) is leeg" in x for x in s["signalen"])


def test_ongeldig_budget_telt_nooit_als_geldig():
    """NaN, True, 0 en negatief zijn geen budget (ontwerpreview 22-09, bevinding 8)."""
    for fout in (float("nan"), True, 0, -5, float("inf"), "100"):
        reg = {"globaal": {"proeftuin_kapitaal_usd": 500},
               "experimenten": {"x": {"trede": 3, "status": "live", "sinds": "2026-09-01", "budget_usd": fout},
                                "y": {"trede": 3, "status": "live", "sinds": "2026-09-01", "budget_usd": 900},
                                "i": {"trede": 0, "status": "idee", "sinds": "2026-09-20"},
                                "p": {"trede": 1, "status": "papier", "sinds": "2026-09-20"}}}
        sig = motor.stand(reg, VANDAAG)["signalen"]
        assert any("x staat op de proeftuin zonder geldig budget_usd" in x for x in sig), repr(fout)
        assert any("$900 ingezet" in x for x in sig), repr(fout)

