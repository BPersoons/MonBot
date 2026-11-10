"""HLP-meter op de overzichtspagina: een enkele sprong mag hem niet groen maken."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import overzicht  # noqa: E402

DAG_MS = 86400000


def _maand(stappen, av=1000.0):
    pnl, punten_pn, punten_av = 0.0, [], []
    for i, s in enumerate([0.0] + stappen):
        pnl += s * av
        punten_pn.append([i * DAG_MS, str(pnl)])
        punten_av.append([i * DAG_MS, str(av)])
    return {"accountValueHistory": punten_av, "pnlHistory": punten_pn}


def test_trimt_aan_beide_kanten():
    stappen = [0.0001] * 28 + [0.015, -0.005]
    alles, getrimd = overzicht.hlp_30d(_maand(stappen))
    assert alles == pytest.approx(((1.0001 ** 28 * 1.015 * 0.995) - 1) * 100 * 365 / 30, rel=1e-6)
    assert getrimd == pytest.approx((1.0001 ** 28 - 1) * 100 * 365 / 30, rel=1e-6)
    assert getrimd < 5 < alles


def test_te_korte_reeks_is_onmeetbaar():
    with pytest.raises(ValueError):
        overzicht.hlp_30d(_maand([0.001] * 5))
