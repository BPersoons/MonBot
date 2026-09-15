"""subsysteem_aan: één schakelaar voor main.py en SwarmMonitor.

Staat een subsysteem uit, dan moeten twee plekken dat op dezelfde manier lezen:
main.py (draait het?) en SwarmMonitor (moet ik alarmeren als het stil is?). Lezen
ze het verschillend, dan zet je de pijplijn uit en krijg je er elke dag een
droogte-alarm voor terug — precies wat er vijf weken gebeurde.
"""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auto_params import AutoParams, subsysteem_aan  # noqa: E402


@pytest.mark.parametrize("waarde, verwacht", [
    (None, True),       # sleutel ontbreekt: niets verandert
    (True, True),
    ("true", True),
    (False, False),
    ("false", False),
    ("OFF", False),
    (0, False),
    ("0", False),
    ("no", False),
])
def test_leest_de_sleutel(waarde, verwacht):
    with patch.object(AutoParams, "__init__", lambda self: None), \
         patch.object(AutoParams, "get_candidate_value", return_value=waarde) as lees:
        assert subsysteem_aan("handelspijplijn") is verwacht
    lees.assert_called_with("subsystem_handelspijplijn_enabled")


def test_ontbrekende_sleutel_volgt_de_standaard():
    with patch.object(AutoParams, "__init__", lambda self: None), \
         patch.object(AutoParams, "get_candidate_value", return_value=None):
        assert subsysteem_aan("iets", standaard=False) is False


def test_onleesbare_config_valt_terug_op_de_standaard():
    """Een kapotte config mag een subsysteem niet stil uitzetten."""
    with patch.object(AutoParams, "__init__", side_effect=OSError("kapot")):
        assert subsysteem_aan("handelspijplijn") is True
