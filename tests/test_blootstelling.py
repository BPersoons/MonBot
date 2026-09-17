"""Blootstellingsmeting: de rekenkern en de omgang met onmeetbare potjes."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import blootstelling as bl  # noqa: E402


def _reeks(n=200, zaad=7):
    rng = np.random.default_rng(zaad)
    idx = pd.date_range("2024-01-05", periods=n, freq="W-FRI")
    return pd.Series(rng.normal(0, 0.02, n), index=idx)


def test_beta_van_een_zuivere_verdubbelaar_is_twee():
    markt = _reeks()
    assert bl._dimson_beta(markt * 2, markt)[0] == pytest.approx(2.0, abs=0.01)


def test_dimson_vangt_een_dag_vertraging_die_de_gewone_beta_mist():
    """De valkuil van 17-09: WEBN sluit om 17:30, Amerikaanse aandelen om 22:00."""
    markt = _reeks()
    vertraagd = (markt * 0.5 + markt.shift(1) * 0.5).dropna()
    gewoon, dimson, _ = bl._dimson_beta(vertraagd, markt)
    assert gewoon == pytest.approx(0.5, abs=0.05), "de helft van de beweging valt buiten beeld"
    assert dimson == pytest.approx(1.0, abs=0.05), "met de vertraging erbij is de beta weer 1"


def test_correlatie_van_ongerelateerde_reeksen_is_bijna_nul():
    assert abs(bl._dimson_beta(_reeks(zaad=1), _reeks(zaad=2))[2]) < 0.2


def test_rapport_telt_een_onbekend_potje_niet_stil_mee(capsys):
    meting = {"periode": ["2024-01-05", "2026-01-05"], "weken": 104, "schok": -0.20,
              "potjes": {"tradfi": 1000.0, "yield_core": 1000.0, "iets_nieuws": 500.0},
              "beta": {"dip-koper": None, "crypto vasthouden": None}}
    bl.rapport(meting)
    uit = capsys.readouterr().out
    assert "ONMEETBAAR" in uit and "iets_nieuws" in uit
    assert "-200.00" in uit, "alleen tradfi verliest; het onbekende potje wordt niet geraden"


def test_rapport_meldt_een_onmeetbare_beta_als_onmeetbaar(capsys):
    meting = {"periode": ["2024-01-05", "2026-01-05"], "weken": 104, "schok": -0.20,
              "potjes": {"tradfi": 1000.0, "thematic_exposure": 200.0},
              "beta": {"dip-koper": None, "crypto vasthouden": None}}
    bl.rapport(meting)
    uit = capsys.readouterr().out
    assert "onmeetbaar" in uit and "thematic_exposure" in uit


def test_usdc_potjes_verliezen_niets_in_een_marktdaling(capsys):
    meting = {"periode": ["2024-01-05", "2026-01-05"], "weken": 104, "schok": -0.20,
              "potjes": {"yield_core": 2500.0, "swarm": 150.0},
              "beta": {"dip-koper": None, "crypto vasthouden": None}}
    bl.rapport(meting)
    assert "+0.00" in capsys.readouterr().out
