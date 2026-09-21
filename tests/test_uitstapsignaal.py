"""Uitstapsignaal (research/uitstapsignaal.py): alleen afgesloten maanden, omslag = melding."""

import math
from datetime import date

from research import uitstapsignaal as u


def _reeks(waarden, start_jaar=2025, start_maand=1):
    """Eén dagkoers op de 15e per maand; de maandslot is dan die koers."""
    uit, j, m = {}, start_jaar, start_maand
    for w in waarden:
        uit["%04d-%02d-15" % (j, m)] = w
        m += 1
        if m == 13:
            j, m = j + 1, 1
    return uit


def test_lopende_maand_telt_niet():
    sloten = u.maandsloten({"2026-08-29": 100.0, "2026-09-18": 50.0}, date(2026, 9, 21))
    assert sloten == {"2026-08": 100.0}


def test_nan_en_nul_worden_overgeslagen():
    sloten = u.maandsloten({"2026-07-15": float("nan"), "2026-07-16": 0.0, "2026-06-15": 90.0},
                           date(2026, 9, 1))
    assert sloten == {"2026-06": 90.0}


def test_standen_pas_met_vol_venster():
    sloten = u.maandsloten(_reeks([100.0] * 9), date(2027, 1, 1))
    assert u.standen(sloten) == []
    sloten = u.maandsloten(_reeks([100.0] * 9 + [120.0]), date(2027, 1, 1))
    rij = u.standen(sloten)[-1]
    assert rij[3] == "in" and math.isclose(rij[2], 102.0)


def test_gelijk_aan_gemiddelde_is_uit():
    sloten = u.maandsloten(_reeks([100.0] * 10), date(2027, 1, 1))
    assert u.standen(sloten)[-1][3] == "uit"


def test_omslag_na_vooruitstart_geeft_melding():
    # 2025-01 .. 2026-09 stijgend, 2026-10 diep eronder
    waarden = [100.0 + i for i in range(21)] + [80.0]
    rijen = u.standen(u.maandsloten(_reeks(waarden), date(2026, 11, 5)))
    ledger = {"maanden": []}
    assert u.verwerk(ledger, rijen[:-1], []) is None   # teruggerekend + 2026-09 'in'
    melding = u.verwerk(ledger, rijen, [])
    assert melding and "UIT" in melding and "2026-10" in melding
    assert ledger["maanden"][-1]["teruggerekend"] is False


def test_omslag_in_teruggerekende_maanden_meldt_niets():
    waarden = [100.0 + i for i in range(12)] + [60.0, 60.0, 60.0]   # omslag in 2026-01
    rijen = u.standen(u.maandsloten(_reeks(waarden), date(2026, 5, 1)))
    ledger = {"maanden": []}
    assert u.verwerk(ledger, rijen, []) is None
    assert all(m["teruggerekend"] for m in ledger["maanden"])


def test_bekende_maand_niet_dubbel():
    rijen = u.standen(u.maandsloten(_reeks([100.0 + i for i in range(12)]), date(2026, 1, 1)))
    ledger = {"maanden": []}
    u.verwerk(ledger, rijen, [])
    n = len(ledger["maanden"])
    u.verwerk(ledger, rijen, [])
    assert len(ledger["maanden"]) == n


def test_schaduw_telt_alleen_vooruit_en_volgt_de_stand():
    maanden = [
        {"maand": "2026-08", "slot": 100.0, "stand": "in", "teruggerekend": True},
        {"maand": "2026-09", "slot": 100.0, "stand": "uit", "teruggerekend": False},
        {"maand": "2026-10", "slot": 90.0, "stand": "in", "teruggerekend": False},
        {"maand": "2026-11", "slot": 99.0, "stand": "in", "teruggerekend": False},
    ]
    s = u.schaduw(maanden)
    assert s["maanden"] == 2
    assert math.isclose(s["vasthouden"], -0.01)
    assert math.isclose(s["regel"], 0.10)   # oktober uit (daling gemist), november in (+10%)
