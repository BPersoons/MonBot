"""Twee stille storingen uit de statusmeting van 2026-08-25.

1. cost_log.json stond drie dagen stil. `get_daily_summary()` werd alleen
   aangeroepen vanuit `_tune_all_params` (uit achter AUDITOR_ENABLED) en
   vanuit `_build_rsi_digest` — de kostenboekhouding hing dus af van een
   RSI-bericht. Dat bestand is de noemer van de kostenhorde in het plan.

2. Twee plekken riepen `db.log_trade(...)` aan, een methode die
   `DatabaseClient` niet heeft. De AttributeError werd gevangen, dus de
   Supabase-kant van die twee herstelpaden deed al die tijd niets — op één
   plek zelfs zonder logregel.
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.auditor import PerformanceAuditor
from utils.db_client import DatabaseClient

WORTEL = Path(__file__).resolve().parent.parent
BRONMAPPEN = ("agents", "utils", "core", "integrations")


def _auditor():
    with patch("utils.auditor.DatabaseClient"), \
         patch("utils.auditor.AutoParams"), \
         patch("utils.auditor.ShadowComparator"), \
         patch("utils.auditor.CostTracker"):
        auditor = PerformanceAuditor()
    auditor.logger = MagicMock()
    return auditor


def test_kostenstaat_wordt_vanuit_de_auditlus_geschreven():
    """De eerste auditronde na een start moet de dagstaat wegschrijven."""
    auditor = _auditor()
    auditor._snapshot_costs()
    auditor.cost_tracker.get_daily_summary.assert_called_once()


def test_kostenstaat_is_afgeknepen_op_een_uur():
    """Elke minuut schrijven heeft geen zin; twee keer per uur ook niet."""
    auditor = _auditor()
    auditor._snapshot_costs()
    auditor._snapshot_costs()
    assert auditor.cost_tracker.get_daily_summary.call_count == 1


def test_kostenstaat_overleeft_een_kapotte_tracker():
    """Een mislukte momentopname mag de auditronde niet omver trekken."""
    auditor = _auditor()
    auditor.cost_tracker.get_daily_summary.side_effect = OSError("schijf vol")
    auditor._snapshot_costs()  # mag niet gooien
    auditor.logger.warning.assert_called_once()
    # En de klok is NIET bijgezet, dus de volgende ronde probeert het opnieuw.
    assert auditor._last_cost_snapshot == 0.0


def test_databaseclient_heeft_geen_log_trade():
    """Struikeldraad: komt de methode er ooit bij, dan mag de grep hieronder weg."""
    assert not hasattr(DatabaseClient, "log_trade"), (
        "DatabaseClient heeft nu wel log_trade — werk deze toets en de "
        "aanroepen in execution_agent/main.py bij."
    )
    assert hasattr(DatabaseClient, "log_trade_with_reasoning")


def test_niemand_roept_db_log_trade_aan():
    """Repo-breed, niet per bestand: zo is deze fout twee keer blijven staan."""
    bestanden = [WORTEL / "main.py"]
    for map_ in BRONMAPPEN:
        bestanden.extend((WORTEL / map_).rglob("*.py"))

    treffers = []
    for pad in bestanden:
        for nr, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), 1):
            if ".db.log_trade(" in regel:
                treffers.append(f"{pad.relative_to(WORTEL)}:{nr}")

    assert not treffers, (
        "db.log_trade() bestaat niet — gebruik db.log_trade_with_reasoning(data, {}). "
        "Let op: execution_agent.log_trade() is NIET het alternatief, die schrijft "
        f"ook naar trade_log.json. Gevonden op: {treffers}"
    )


def test_de_auditlus_roept_de_momentopname_ook_echt_aan():
    """De bedrading, niet alleen de methode.

    Zonder deze toets kun je `self._snapshot_costs()` uit `run_audit_cycle`
    halen zonder dat er iets rood wordt — en dan is de kostenstaat weer stil
    zonder dat iemand het merkt. Precies hoe het drie dagen kon duren.
    """
    auditor = _auditor()
    auditor.load_json = MagicMock(return_value=[])          # geen trades
    auditor.auto_params.is_shadow_mode.return_value = False
    auditor.check_asset_performance = MagicMock()
    auditor._tune_all_params = MagicMock()

    auditor.run_audit_cycle()

    auditor.cost_tracker.get_daily_summary.assert_called_once()
