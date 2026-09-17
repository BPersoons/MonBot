"""Infrastructuurkosten volgen het echte machinetype (2026-09-17).

Tot nu toe stond er een vaste 0,44 in de code: alleen de e2-small, zonder schijf,
IP, registry, secrets en verkeer. Een vast getal veroudert stil bij elke
verkleining — en het is de noemer van H1.
"""
import io
import os
import sys
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import cost_tracker as ct  # noqa: E402


@pytest.fixture(autouse=True)
def schone_staat(monkeypatch):
    monkeypatch.delenv("INFRA_COST_USD_DAILY", raising=False)
    ct._machinetype_cache.clear()
    yield
    ct._machinetype_cache.clear()


def _metadata(monkeypatch, antwoorden):
    """Nep-metadataserver; `antwoorden` is een lijst van str of Exception, in volgorde."""
    oproepen = []

    def nep_urlopen(req, timeout=None):
        oproepen.append((req.full_url, dict(req.header_items()), timeout))
        a = antwoorden[min(len(oproepen), len(antwoorden)) - 1]
        if isinstance(a, Exception):
            raise a
        return io.BytesIO(a.encode())

    monkeypatch.setattr(urllib.request, "urlopen", nep_urlopen)
    return oproepen


def test_e2_micro_en_e2_small_krijgen_hun_eigen_prijs(monkeypatch):
    _metadata(monkeypatch, ["projects/397608330908/zones/europe-west1-b/machineTypes/e2-micro"])
    assert ct.infra_kosten_per_dag() == pytest.approx(0.221 + ct._BIJKOSTEN_USD_PER_DAG)
    ct._machinetype_cache.clear()
    _metadata(monkeypatch, ["projects/397608330908/zones/europe-west1-b/machineTypes/e2-small"])
    assert ct.infra_kosten_per_dag() == pytest.approx(0.442 + ct._BIJKOSTEN_USD_PER_DAG)


def test_vraagt_de_metadataserver_met_de_verplichte_kop(monkeypatch):
    oproepen = _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-micro"])
    ct.infra_kosten_per_dag()
    url, koppen, timeout = oproepen[0]
    assert url == "http://metadata.google.internal/computeMetadata/v1/instance/machine-type"
    assert {k.lower(): v for k, v in koppen.items()}.get("metadata-flavor") == "Google"
    assert timeout and timeout <= 5, "zonder timeout kan de auditlus blijven hangen"


def test_onleesbaar_rekent_de_duurste_nooit_nul(monkeypatch):
    """Onmeetbaar is nooit goedkoop: buiten GCP of bij een storing telt de duurste."""
    _metadata(monkeypatch, [OSError("geen metadataserver")])
    assert ct.infra_kosten_per_dag() == pytest.approx(0.884 + ct._BIJKOSTEN_USD_PER_DAG)


def test_onbekend_type_rekent_de_duurste(monkeypatch):
    _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/n2-standard-8"])
    assert ct.infra_kosten_per_dag() == pytest.approx(max(ct._COMPUTE_USD_PER_DAG.values()) + ct._BIJKOSTEN_USD_PER_DAG)


def test_gelezen_type_wordt_niet_elk_uur_opnieuw_gevraagd(monkeypatch):
    oproepen = _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-micro"])
    for _ in range(5):
        ct.infra_kosten_per_dag()
    assert len(oproepen) == 1


def test_een_hapering_telt_niet_de_hele_looptijd(monkeypatch):
    """Eerst mislukt, binnen het uur niet opnieuw gevraagd, daarna wel — en dan geldt het echte type."""
    klok = [1000.0]
    monkeypatch.setattr("time.monotonic", lambda: klok[0])
    oproepen = _metadata(monkeypatch, [OSError("hapering"), "projects/1/zones/z/machineTypes/e2-micro"])
    assert ct.infra_kosten_per_dag() == pytest.approx(0.884 + ct._BIJKOSTEN_USD_PER_DAG)
    klok[0] += 60
    assert ct.infra_kosten_per_dag() == pytest.approx(0.884 + ct._BIJKOSTEN_USD_PER_DAG)
    assert len(oproepen) == 1, "binnen het uur niet elke ronde 2 s wachten"
    klok[0] += 3000
    assert ct.infra_kosten_per_dag() == pytest.approx(0.884 + ct._BIJKOSTEN_USD_PER_DAG)
    assert len(oproepen) == 1, "na 51 minuten nog niet opnieuw"
    klok[0] += 600
    assert ct.infra_kosten_per_dag() == pytest.approx(0.221 + ct._BIJKOSTEN_USD_PER_DAG)
    assert len(oproepen) == 2


def test_env_var_gaat_voor(monkeypatch):
    oproepen = _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-micro"])
    monkeypatch.setenv("INFRA_COST_USD_DAILY", "0.5")
    assert ct.infra_kosten_per_dag() == 0.5
    assert oproepen == []


@pytest.mark.parametrize("waarde", ["nan", "inf", "-1", "abc", "0", "0.0"])
def test_ongeldige_env_var_wordt_genegeerd(monkeypatch, waarde):
    _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-micro"])
    monkeypatch.setenv("INFRA_COST_USD_DAILY", waarde)
    assert ct.infra_kosten_per_dag() == pytest.approx(0.221 + ct._BIJKOSTEN_USD_PER_DAG)


def test_dagstaat_boekt_de_infra_kosten_en_het_type(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-small"])
    s = ct.CostTracker().get_daily_summary()
    assert s["infra_cost_usd_daily"] == pytest.approx(0.442 + 0.232)
    assert s["machine_type"] == "e2-small"
    assert s["total_cost_usd"] == pytest.approx(0.674)   # geen LLM, geen fees in een lege map


def test_bijkosten_tellen_onbevestigde_staffels_mee():
    """Schijf en IP-adres tellen tot de factuur het tegendeel laat zien (A2-audit 2026-09-17)."""
    assert ct._BIJKOSTEN_USD_PER_DAG >= 0.039 + 0.122


def test_onverwachte_fout_bij_het_lezen_valt_ook_op_de_duurste(monkeypatch):
    """Niet alleen netwerkfouten: een kapot antwoord (geen OSError) mag de auditlus niet laten vallen."""
    _metadata(monkeypatch, [ValueError("kapot antwoord")])
    assert ct.infra_kosten_per_dag() == pytest.approx(0.884 + ct._BIJKOSTEN_USD_PER_DAG)



def test_beursfees_tellen_niet_mee_in_de_totale_kosten(monkeypatch, tmp_path):
    """H1 rekent met de NAV, waar fees al in zitten: meetellen is dubbel tellen."""
    monkeypatch.chdir(tmp_path)
    _metadata(monkeypatch, ["projects/1/zones/z/machineTypes/e2-small"])
    monkeypatch.setattr(ct.CostTracker, "_calc_exchange_fees", lambda self, d: 3.21)
    s = ct.CostTracker().get_daily_summary()
    assert s["exchange_fees_usd"] == 3.21
    assert s["total_cost_usd"] == pytest.approx(0.674)
