"""Monitor Check 26: waarschuwen vóórdat kasbeheer of een bridge zonder gas vastloopt (M3)."""
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import swarm_monitor as sm  # noqa: E402
from utils import treasury_executor as te  # noqa: E402

NU = datetime(2026, 9, 17, 22, 0, tzinfo=timezone.utc)
VAULT = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"


@pytest.fixture(autouse=True)
def _vaste_omgeving(monkeypatch):
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT)
    monkeypatch.delenv("HL_WALLET_ADDRESS", raising=False)
    monkeypatch.setattr("utils.treasury_executor._fetch_secret_rest", lambda naam: "")


@pytest.fixture
def monitor(tmp_path):
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", str(tmp_path / "geen_staat.json")):
        m = sm.SwarmMonitor(db_client=MagicMock())
    m._send_telegram = MagicMock(return_value=True)
    return m


def _saldi(monkeypatch, **eth):
    """Nep-RPC: eth_getBalance per adres; een Exception-waarde gooit."""
    vragen = []
    per_adres = {te._TREASURY_WALLET.lower(): eth.get("treasury"), VAULT.lower(): eth.get("vault")}

    def nep_rpc(methode, params):
        assert methode == "eth_getBalance", "alleen saldo lezen, geen andere RPC"
        vragen.append(params[0])
        waarde = per_adres[params[0].lower()]
        if isinstance(waarde, Exception):
            raise waarde
        return hex(int(round(waarde * 10 ** 18)))

    monkeypatch.setattr(te, "_rpc", nep_rpc)
    return vragen


def _tekst(monitor):
    return " ".join(str(c.args[0]) for c in monitor._send_telegram.call_args_list)


def test_genoeg_gas_meldt_niets(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.000474, vault=0.000147)   # de stand na de bijvulling van 17-09
    monitor._check_eth_gas(NU)
    monitor._send_telegram.assert_not_called()


def test_vaste_ethgrens_zou_de_hoofdwallet_meteen_laten_alarmeren(monitor, monkeypatch):
    """0,000147 ETH is ~27 bridges: geen alarm, ook al ligt het onder 0,00015."""
    _saldi(monkeypatch, treasury=0.001, vault=0.000147)
    monitor._check_eth_gas(NU)
    assert "hoofdwallet" not in _tekst(monitor)


def test_treasury_laag_geeft_een_melding_met_saldo_en_ruimte(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.000124, vault=0.001)      # de stand van vóór de bijvulling
    monitor._check_eth_gas(NU)
    assert monitor._send_telegram.call_count == 1
    tekst = _tekst(monitor)
    assert "treasury" in tekst and "0.000124" in tekst and "~6 transacties" in tekst
    assert "stuur_eth_voor_gas" in tekst


def test_vault_laag_verwijst_naar_bart_niet_naar_interne_bijvulling(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.001, vault=0.000110)
    monitor._check_eth_gas(NU)
    tekst = _tekst(monitor)
    assert "hoofdwallet" in tekst and "Bart" in tekst and "stuur_eth_voor_gas" not in tekst


def test_onder_de_blokkadegrens_heet_het_op(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00005, vault=0.001)
    monitor._check_eth_gas(NU)
    assert "is OP" in _tekst(monitor)


def test_de_grens_ligt_op_vijftien_transacties(monitor, monkeypatch):
    per_tx = te._GAS_KOSTEN_AAVE_ETH
    _saldi(monkeypatch, treasury=te._MIN_ETH_FOR_GAS + 15.2 * per_tx, vault=0.001)
    monitor._check_eth_gas(NU)
    monitor._send_telegram.assert_not_called()
    _saldi(monkeypatch, treasury=te._MIN_ETH_FOR_GAS + 14.8 * per_tx, vault=0.001)
    monitor._check_eth_gas(NU + timedelta(hours=2))
    assert monitor._send_telegram.call_count == 1


def test_hooguit_een_keer_per_uur_meten(monitor, monkeypatch):
    vragen = _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monitor._check_eth_gas(NU)
    monitor._check_eth_gas(NU + timedelta(minutes=5))
    monitor._check_eth_gas(NU + timedelta(minutes=59))
    assert len(vragen) == 2, "één meting per wallet per uur"
    monitor._check_eth_gas(NU + timedelta(minutes=61))
    assert len(vragen) == 4


def test_laag_blijven_meldt_pas_na_drie_dagen_opnieuw(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    for uur in range(0, 72, 1):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=1))
    assert monitor._send_telegram.call_count == 1
    monitor._check_eth_gas(NU + timedelta(hours=72, minutes=2))
    assert monitor._send_telegram.call_count == 2


def test_herstel_en_opnieuw_laag_meldt_opnieuw(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    monitor._check_eth_gas(NU)
    _saldi(monkeypatch, treasury=0.001, vault=0.001)          # bijgevuld
    monitor._check_eth_gas(NU + timedelta(hours=2))
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)        # weer opgebruikt
    monitor._check_eth_gas(NU + timedelta(hours=4))
    assert monitor._send_telegram.call_count == 2


def test_schommelen_rond_de_grens_geeft_geen_reeks_meldingen(monitor, monkeypatch):
    per_tx = te._GAS_KOSTEN_AAVE_ETH
    laag = te._MIN_ETH_FOR_GAS + 14 * per_tx
    net_boven = te._MIN_ETH_FOR_GAS + 17 * per_tx             # boven 15, onder 15 × 1,5
    for i, saldo in enumerate([laag, net_boven, laag, net_boven, laag]):
        _saldi(monkeypatch, treasury=saldo, vault=0.001)
        monitor._check_eth_gas(NU + timedelta(hours=2 * i))
    assert monitor._send_telegram.call_count == 1


def test_onmeetbaar_is_geen_alarm_en_wist_de_staat_niet(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    monitor._check_eth_gas(NU)
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=RuntimeError("rpc weg"))
    monitor._check_eth_gas(NU + timedelta(hours=2))
    assert monitor._send_telegram.call_count == 1
    assert "eth_gas_laag:treasury" in monitor._sent_alerts
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    monitor._check_eth_gas(NU + timedelta(hours=4))
    assert monitor._send_telegram.call_count == 1, "nog binnen de 3 dagen: geen tweede melding"


def test_mislukte_melding_stempelt_niet_maar_remt_wel_af(monitor, monkeypatch):
    monitor._send_telegram = MagicMock(return_value=False)
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    monitor._check_eth_gas(NU)
    assert "eth_gas_laag:treasury" not in monitor._sent_alerts
    monitor._check_eth_gas(NU + timedelta(minutes=30))        # meet niet (uur-poort)
    assert monitor._send_telegram.call_count == 1, "na een mislukte melding niet elke ronde opnieuw"
    monitor._send_telegram = MagicMock(return_value=True)
    monitor._check_eth_gas(NU + timedelta(minutes=61))
    assert monitor._send_telegram.call_count == 1
    assert "eth_gas_laag:treasury" in monitor._sent_alerts


def test_onbekend_vaultadres_meet_alleen_de_treasury(monitor, monkeypatch):
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setattr("utils.gcp_secrets.get_secret", lambda *a, **k: None)
    vragen = _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monitor._check_eth_gas(NU)
    assert [v.lower() for v in vragen] == [te._TREASURY_WALLET.lower()]


def test_de_check_draait_in_elke_monitorronde(monitor):
    """Echt een ronde draaien (checks zelf onderschept): de broncode lezen ziet een mutatie niet."""
    monitor._safe_check = MagicMock()
    monitor._save_alert_state = MagicMock()
    monitor._report_to_supabase = MagicMock()
    monitor._run_checks()
    namen = [c.args[0].__name__ for c in monitor._safe_check.call_args_list]
    assert "_check_eth_gas" in namen


def test_stempels_overleven_een_herstart(monitor, monkeypatch, tmp_path):
    """De 3-dagenklok staat in monitor_alert_state.json (gemount), niet alleen in het geheugen."""
    _saldi(monkeypatch, treasury=0.00011, vault=0.001)
    pad = str(tmp_path / "staat.json")
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", pad):
        monitor._check_eth_gas(datetime.now(timezone.utc))
        monitor._save_alert_state()
        nieuw = sm.SwarmMonitor(db_client=MagicMock())
    nieuw._send_telegram = MagicMock(return_value=True)
    nieuw._check_eth_gas(datetime.now(timezone.utc) + timedelta(hours=2))
    nieuw._send_telegram.assert_not_called()


def test_treasury_melding_noemt_wat_de_hoofdwallet_kan_missen(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00011, vault=0.000497)
    monitor._check_eth_gas(NU)
    tekst = _tekst(monitor)
    over = 0.000497 - te._HOOFDWALLET_RESERVE_ETH
    assert f"{over:.6f} ETH missen" in tekst and "stuur_eth_voor_gas" in tekst


def test_treasury_melding_zegt_nieuw_eth_als_de_hoofdwallet_niets_kan_missen(monitor, monkeypatch):
    """A1-audit: het advies 'intern bijvullen' kon de hoofdwallet zelf onder de grens brengen."""
    _saldi(monkeypatch, treasury=0.00011, vault=0.000147)
    monitor._check_eth_gas(NU)
    tekst = _tekst(monitor)
    assert "kan niets missen" in tekst and "Bart" in tekst
    assert "stuur_eth_voor_gas" not in tekst


def test_treasury_melding_zonder_meting_van_de_hoofdwallet(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=0.00011, vault=RuntimeError("rpc"))
    monitor._check_eth_gas(NU)
    assert "onbekend" in _tekst(monitor)


def test_reserve_van_de_hoofdwallet_valt_precies_op_de_waarschuwingsgrens(monitor, monkeypatch):
    """Eén grens: een bijvulling die de reserve respecteert, laat Check 26 niet afgaan."""
    _saldi(monkeypatch, treasury=0.001, vault=te._HOOFDWALLET_RESERVE_ETH + 1e-9)
    monitor._check_eth_gas(NU)
    monitor._send_telegram.assert_not_called()
    assert te._HOOFDWALLET_RESERVE_ETH >= 0.0001 + 15 * te._GAS_KOSTEN_BRIDGE_ETH - 1e-12


def test_een_dag_onmeetbaar_geeft_een_melding(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=0.001)
    for uur in range(0, 24):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=1))
    monitor._send_telegram.assert_not_called()
    monitor._check_eth_gas(NU + timedelta(hours=24, minutes=2))
    assert monitor._send_telegram.call_count == 1
    assert "onmeetbaar" in _tekst(monitor) and "treasury-wallet" in _tekst(monitor)
    for uur in range(25, 72):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=3))
    assert monitor._send_telegram.call_count == 1, "daarna hooguit elke 3 dagen"


def test_een_geslaagde_meting_zet_de_onmeetbaar_klok_terug(monitor, monkeypatch):
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=0.001)
    for uur in range(0, 20):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=1))
    _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monitor._check_eth_gas(NU + timedelta(hours=20, minutes=2))
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=0.001)
    for uur in range(21, 44):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=3))
    monitor._send_telegram.assert_not_called()


def test_advies_rekent_met_de_reserve_niet_met_de_blokkadegrens(monitor, monkeypatch):
    """0,00017 ETH: boven _MIN is er 0,00007 over, boven de reserve maar 0,000045 — te weinig."""
    _saldi(monkeypatch, treasury=0.00011, vault=0.00017)
    monitor._check_eth_gas(NU)
    assert "kan niets missen" in _tekst(monitor)



def test_tweede_storing_na_herstel_meldt_weer_na_een_dag(monitor, monkeypatch):
    """A1-audit r2: de meldstempel van de eerste storing mocht de tweede niet 72u stilhouden."""
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=0.001)
    for uur in range(0, 25):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=1))
    assert monitor._send_telegram.call_count == 1
    _saldi(monkeypatch, treasury=0.001, vault=0.001)
    monitor._check_eth_gas(NU + timedelta(hours=26))
    _saldi(monkeypatch, treasury=RuntimeError("rpc weg"), vault=0.001)
    for uur in range(27, 52):
        monitor._check_eth_gas(NU + timedelta(hours=uur, minutes=1))
    assert monitor._send_telegram.call_count == 2
