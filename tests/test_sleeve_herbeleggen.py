"""De inzet van de dip-koper moet meegroeien met het potje.

Stond hier `budget_usd / MAX_CONCURRENT_NAMES`, dan kocht de sleeve voor altijd
posities van $42,50 -- ook met $1.289 in kas. Winst werd dan een kasstapel in
plaats van inzet. Op zestien jaar aandelenhistorie scheelde dat +405% versus
+1710% bij exact dezelfde regels (zie `scripts/sleeve_harness.py --aandelen`).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.thematic_exposure_lab import (MAX_CONCURRENT_NAMES, TRANCHE_PCTS,
                                         sleeve_nav_usd)


def _potje(kas, open_posities=()):
    return {
        "budget_usd": 255.0,
        "cash_usd": kas,
        "positions": {
            "XYZ-%d" % i: {"status": "OPEN", "current_value_usd": v}
            for i, v in enumerate(open_posities)
        },
    }


def test_nav_telt_kas_en_open_posities():
    assert sleeve_nav_usd(_potje(100.0, [42.0, 58.0])) == 200.0


def test_nav_negeert_gesloten_posities():
    p = _potje(100.0, [50.0])
    p["positions"]["dicht"] = {"status": "CLOSED", "current_value_usd": 999.0}
    assert sleeve_nav_usd(p) == 150.0


def test_nav_overleeft_rommel():
    """NaN, None en tekst mogen geen inzet van 'nan' opleveren."""
    p = _potje(float("nan"), [])
    p["positions"] = {
        "a": {"status": "OPEN", "current_value_usd": None},
        "b": {"status": "OPEN", "current_value_usd": "kapot"},
        "c": {"status": "OPEN", "current_value_usd": float("inf")},
    }
    nav = sleeve_nav_usd(p)
    assert nav == nav and nav >= 0.0        # niet NaN, niet negatief


def test_inzet_groeit_mee_met_het_potje():
    """De kern: verdubbelt het potje, dan verdubbelt de inzet."""
    klein = sleeve_nav_usd(_potje(255.0)) / MAX_CONCURRENT_NAMES
    groot = sleeve_nav_usd(_potje(510.0)) / MAX_CONCURRENT_NAMES
    assert abs(klein - 42.5) < 0.01
    assert abs(groot - 85.0) < 0.01


def test_inzet_krimpt_ook_weer():
    """Een de-riskende richting hoort net zo goed te werken."""
    assert sleeve_nav_usd(_potje(120.0)) / MAX_CONCURRENT_NAMES < 42.5


def test_inzet_volgt_niet_het_gestorte_bedrag():
    """Struikeldraad: hier lag de bug. budget_usd blijft 255, NAV niet."""
    gegroeid = _potje(600.0, [200.0, 200.0])
    assert gegroeid["budget_usd"] == 255.0
    per_naam = sleeve_nav_usd(gegroeid) / MAX_CONCURRENT_NAMES
    assert per_naam > 100.0, "inzet volgt nog steeds het gestorte bedrag"
    # En de eerste tranche moet dan ook echt groter uitvallen.
    assert per_naam * TRANCHE_PCTS[1] > 42.5


def test_open_tranche_gebruikt_de_nav_en_niet_het_gestorte_bedrag():
    """De BEDRADING, niet alleen de formule.

    Zonder deze toets kun je in `_open_tranche` terug naar
    `gestort / MAX_CONCURRENT_NAMES` zonder dat er iets rood wordt — de andere
    toetsen hierboven controleren alleen `sleeve_nav_usd` zelf. Dat is precies
    hoe deze bug oorspronkelijk onzichtbaar bleef.

    Opzet: NAV wordt hoog gezet en de kas laag, zodat de tranche op de
    cash-guard afketst en er geen beurs nodig is. Wordt `sleeve_nav_usd` niet
    aangeroepen, dan rekent de code nog met het gestorte bedrag.
    """
    from unittest.mock import MagicMock, patch
    import utils.thematic_exposure_lab as lab_mod

    lab = lab_mod.ThematicExposureLab.__new__(lab_mod.ThematicExposureLab)
    lab.exchange_client = MagicMock()

    potje = {"budget_usd": 255.0, "cash_usd": 1.0, "positions": {}}

    with patch.object(lab_mod, "sleeve_nav_usd", return_value=6000.0) as nav, \
         patch("agents.xyz_technical_analyst._market_is_open", return_value=True):
        lab._open_tranche("XYZ-MSFT", 1, {"tickers": {}}, potje, {})

    assert nav.called, "_open_tranche rekent niet met de NAV van het potje"
    # En hij ketste af op de kas, niet op de beurs: geen enkele order geplaatst.
    assert not lab.exchange_client.create_order.called
