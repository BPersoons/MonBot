"""Een vastgelopen handmatige HL-opname mag kasbeheer niet stil en voor altijd blokkeren.

A1-hertoets kasbeheer 2026-09-15: een DEPLOY_YIELD in NEEDS_MANUAL_WITHDRAWAL hield
generate, HL-overschot, switch en diversificatie tegen, zonder verlooptijd, en de monitor
kende de status niet. Bovendien zette willekeurige USDC die later op de wallet kwam hem
alsnog naar BRIDGED.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import treasury_executor as te  # noqa: E402


@pytest.fixture(autouse=True)
def _vaste_omgeving(monkeypatch):
    """De toetsen mogen niet van de shell afhangen.

    A1-audit ronde 5: dezelfde mutatie gaf 18 passed óf 4 failed, puur omdat
    `HL_VAULT_ADDRESS` wel of niet in de omgeving stond. Productie heeft dat adres, dus
    de toetsen ook — een toets die overrides wil, doet dat expliciet.
    """
    monkeypatch.setenv("HL_VAULT_ADDRESS", "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445")
    monkeypatch.delenv("HL_WALLET_ADDRESS", raising=False)


def _iso(uren_geleden):
    return (datetime.now(timezone.utc) - timedelta(hours=uren_geleden)).isoformat()


def _voorstel(status="NEEDS_MANUAL_WITHDRAWAL", **extra):
    p = {"id": "TRP_x", "type": "DEPLOY_YIELD", "status": status, "amount_usd": 500.0,
         "source": "hl", "withdrawal_destination": te._TREASURY_WALLET}
    p.update(extra)
    return p


def test_handmatige_opname_verloopt_na_48u_als_het_geld_er_niet_is():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(49)))
    assert uit["status"] == "EXPIRED"


def test_geld_dat_net_op_tijd_aankomt_wint_van_de_verlooptijd():
    """A1-audit bevinding 6: de verlooptak stond vóór de saldo-poll (venster ~5 min)."""
    with patch.object(te, "get_arb_usdc_balance", return_value=1000.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(49)))
    assert uit["status"] == "BRIDGED", "aangekomen geld mag niet alsnog verlopen"


def test_binnen_48u_gaat_hij_gewoon_door_als_het_geld_er_is():
    with patch.object(te, "get_arb_usdc_balance", return_value=1000.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since=_iso(1)))
    assert uit["status"] == "BRIDGED"


def test_oud_voorstel_zonder_eigen_veld_valt_terug_op_updated_at():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(updated_at=_iso(60)))
    assert uit["status"] == "EXPIRED"


def test_automatische_bridge_verloopt_niet():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel("WITHDRAWING", updated_at=_iso(60)))
    assert uit["status"] == "WITHDRAWING"


def test_onleesbare_tijd_verloopt_niet_stil():
    with patch.object(te, "get_arb_usdc_balance", return_value=0.0):
        uit = te.advance_proposal(_voorstel(manual_withdrawal_since="gisteren"))
    assert uit["status"] == "NEEDS_MANUAL_WITHDRAWAL"


def _monitor(tmp_path, proposals):
    from agents import swarm_monitor as sm
    (tmp_path / "treasury_proposals.json").write_text(json.dumps(proposals), encoding="utf-8")
    state_file = os.path.join(tempfile.gettempdir(), "monitor_alert_state_TEST_ONLY.json")
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", state_file):
        monitor = sm.SwarmMonitor(db_client=MagicMock())
    monitor._send_telegram = MagicMock()
    return sm, monitor


def _rebalance_gestrand(uren_geleden=2, **extra):
    p = {"id": "TRR_x", "type": "REBALANCE", "status": "FAILED", "amount_usd": 267.28,
         "aave_withdrawn_at": _iso(uren_geleden), "error": "bridge minimum"}
    p.update(extra)
    return p


VAULT_ADR = "0x92D4D9D4c0371D10F3d62194ECD7d43eB9E4F445"


def _saldi(per_adres):
    """Nep-_rpc die balanceOf per adres een eigen bedrag geeft."""
    def rpc(methode, params):
        data = str(params[0].get("data", "")).lower()
        for adres, bedrag in per_adres.items():
            if adres.lower()[2:] in data:
                return hex(int(round(bedrag * 10 ** 6)))
        return "0x0"
    return rpc


def _saldo(usdc):
    return lambda methode, params: hex(int(round(usdc * 10 ** 6)))


def test_monitor_meldt_de_gebeurtenis_ook_als_de_wallet_al_leeg_is(tmp_path, monkeypatch):
    """A1-audit: op 23-07 stond het geld binnen een minuut al terug in Aave.

    Een drempel op het wallet-saldo had dat incident gemist — daarom melden we op de
    gebeurtenis en is het saldo alleen een veld.
    """
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called, "lege wallet is juist het echte geval"
    tekst = monitor._send_telegram.call_args[0][0]
    assert "267" in tekst and "$0.00" in tekst
    assert "niet bevestigd" in tekst, "niet claimen dat het geld nog op de wallet staat"
    assert "op HL zijn aangekomen" in tekst, "de bevestiging kan verlopen zijn"

    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert not monitor._send_telegram.called, "geen tweede melding binnen 24 uur"


def test_monitor_meldt_beide_adressen(tmp_path, monkeypatch):
    """Bij een mislukte bridge-stap-2 staat het geld op het vault-Arb-adres, niet op de wallet."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    from utils.treasury_executor import _TREASURY_WALLET
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc", _saldi({_TREASURY_WALLET: 0.0, VAULT_ADR: 267.28})):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    tekst = monitor._send_telegram.call_args[0][0]
    assert "$0.00" in tekst and "$267.28" in tekst
    assert "vault-Arb" in tekst and VAULT_ADR[-4:] in tekst, "adres herkenbaar in de melding"


def test_monitor_onderscheidt_nul_van_onmeetbaar(tmp_path, monkeypatch):
    """`get_arb_usdc_balance` slikt RPC-fouten in als 0.0 — hier mag dat niet gebeuren."""
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])

    def kapot(methode, params):
        raise RuntimeError("All Arbitrum RPCs failed")

    with patch("utils.treasury_executor._rpc", kapot):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called
    assert "onmeetbaar" in monitor._send_telegram.call_args[0][0]


def test_monitor_zwijgt_bij_oud_scheef_en_opgelost(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)

    # het echte record van 23-07: 55 dagen oud
    sm, oud = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=55 * 24)])
    with patch("utils.treasury_executor._rpc", _saldo(1600.0)):
        oud._check_gestrand_rebalance_geld(nu)
    assert not oud._send_telegram.called, "dood record mag geen vers geld claimen"

    # tijdstempel in de toekomst (klokscheefheid) — nooit melden, ook al wint hij de min()
    sm, scheef = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=-120)])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        scheef._check_gestrand_rebalance_geld(nu)
    assert not scheef._send_telegram.called

    # een latere GESLAAGDE rebalance loste het margeprobleem op — mét meetbaar vault-adres,
    # want zonder dat adres blijft de check bewust melden (zie de toets hieronder)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    sm, klaar = _monitor(tmp_path, [
        _rebalance_gestrand(uren_geleden=5),
        {"id": "TRR_later", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 401.83,
         "aave_withdrawn_at": _iso(4), "completed_at": _iso(3)},
    ])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        klaar._check_gestrand_rebalance_geld(nu)
    assert not klaar._send_telegram.called, "opgelost = geen melding meer"


def test_monitor_kiest_de_meest_recente_en_herhaalt_alleen_bij_geld(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    nu = datetime.now(timezone.utc)
    sm, monitor = _monitor(tmp_path, [
        _rebalance_gestrand(uren_geleden=13 * 24, id="TRR_OUD", amount_usd=50.0),
        _rebalance_gestrand(uren_geleden=1, id="TRR_VERS", amount_usd=267.28),
    ])
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu)
    tekst = monitor._send_telegram.call_args[0][0]
    assert "TRR_VERS" in tekst and "TRR_OUD" not in tekst
    assert "267" in tekst and "$50" not in tekst, "geen bedrag noemen dat nergens bij hoort"

    # tweede melding pas na 24 uur, en daarna nooit meer
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=25))
    assert monitor._send_telegram.called and "herinnering" in monitor._send_telegram.call_args[0][0]
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(267.28)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=50))
    assert not monitor._send_telegram.called, "binnen 72 uur na de tweede: stil"

    # daarna nog hooguit elke 3 dagen, en alléén zolang er echt geld ligt
    from utils.treasury_executor import _TREASURY_WALLET
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldi({_TREASURY_WALLET: 20.0, VAULT_ADR: 20.0})):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=100))
    assert not monitor._send_telegram.called, "$40 is doorzeuren niet waard: geen herhaling"

    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldi({_TREASURY_WALLET: 267.28, VAULT_ADR: 0.0})):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=110))
    assert monitor._send_telegram.called, "$267 blijft liggen: na 3 dagen opnieuw melden"


def test_onmeetbaar_saldo_blijft_herhalen(tmp_path, monkeypatch):
    """A1-audit ronde 5: onmeetbaar mag geen "te weinig geld" betekenen.

    Anders zwijgt de check permanent zodra de RPC of het vault-adres een dag wegvalt,
    terwijl er juist geld kan liggen. Bij het afsluiten gold die regel al.
    """
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)

    def kapot(methode, params):
        raise RuntimeError("All Arbitrum RPCs failed")

    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    for uren in (0, 25):
        with patch("utils.treasury_executor._rpc", kapot):
            monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=uren))
    assert monitor._send_telegram.call_count == 2
    monitor._send_telegram.reset_mock()
    # de tweede melding viel op t+25u, dus de derde mag pas 72u dáárna
    with patch("utils.treasury_executor._rpc", kapot):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=100))
    assert monitor._send_telegram.called, "onmeetbaar: blijven herhalen, niet verstommen"


def test_herhaalklok_blijft_op_72_uur(tmp_path, monkeypatch):
    """De toestandsmachine `:1` → `:2` → `:h` moet na elke herhaling opnieuw 72u wachten."""
    monkeypatch.chdir(tmp_path)
    from utils.treasury_executor import _TREASURY_WALLET
    nu = datetime.now(timezone.utc)
    veel = _saldi({_TREASURY_WALLET: 267.28, VAULT_ADR: 0.0})
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])

    # De klok loopt telkens vanaf de VORIGE melding: t+0, t+25, dan 72u later (t+100),
    # en daarna weer 72u (t+180). t+96 en t+110 vallen binnen zo'n venster.
    gemeld = []
    for uren in (0, 25, 96, 100, 110, 180):
        monitor._send_telegram.reset_mock()
        with patch("utils.treasury_executor._rpc", veel):
            monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=uren))
        if monitor._send_telegram.called:
            gemeld.append(uren)
    assert gemeld == [0, 25, 100, 180], "kreeg %s — 96u en 110u liggen binnen 72u na de vorige" % gemeld


def test_vault_adres_valt_niet_terug_op_de_agent_wallet(tmp_path, monkeypatch):
    """A1-audit ronde 4: de fix uit ronde 3 zat in de code maar in geen enkele toets.

    `HL_WALLET_ADDRESS` is de agent-wallet — een ánder adres. Werd die als vault gelezen,
    dan meldde de check een saldo dat nergens bij hoort en kon hij een geval sluiten op
    grond van het verkeerde adres.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    monkeypatch.setenv("HL_WALLET_ADDRESS", "0xAgEnT0000000000000000000000000000001111")
    from utils.treasury_executor import _TREASURY_WALLET
    voorstellen = [
        _rebalance_gestrand(uren_geleden=5),
        {"id": "TRR_later", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 401.83,
         "aave_withdrawn_at": _iso(4), "completed_at": _iso(3)},
    ]
    sm, monitor = _monitor(tmp_path, voorstellen)
    with patch("utils.treasury_executor._rpc", _saldi({_TREASURY_WALLET: 0.0})), \
         patch("utils.gcp_secrets.get_secret", return_value=""):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert monitor._send_telegram.called, "onbekend vault-adres mag een geval niet sluiten"
    tekst = monitor._send_telegram.call_args[0][0]
    assert "1111" not in tekst, "de agent-wallet mag niet als vault-adres worden getoond"
    assert "niet gemeten" in tekst


def test_vault_adres_komt_uit_de_secrets_als_de_omgeving_leeg_is(tmp_path, monkeypatch):
    """In de container staat HL_VAULT_ADDRESS níét in de omgeving.

    `main.py` injecteert de secrets pas in het draaiende proces, en een los `docker exec`
    ziet ze niet. De secrets-terugval is daarmee het enige pad dat in productie werkt —
    en dat was door geen enkele toets gedekt (A1-audit ronde 6).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    from utils.treasury_executor import _TREASURY_WALLET
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    with patch("utils.treasury_executor._rpc",
               _saldi({_TREASURY_WALLET: 0.0, VAULT_ADR: 267.28})), \
         patch("utils.gcp_secrets.get_secret", return_value=VAULT_ADR):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    tekst = monitor._send_telegram.call_args[0][0]
    assert "$267.28" in tekst, "het vault-saldo hoort gemeten te worden via de secrets"
    assert VAULT_ADR[-4:] in tekst and "niet gemeten" not in tekst


def test_saldo_wordt_hooguit_elke_zes_uur_gemeten(tmp_path, monkeypatch):
    """A1-audit ronde 4: meten vóór de cooldown gaf ~8.000 eth_calls per 14 dagen."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    nu = datetime.now(timezone.utc)
    voorstellen = [
        _rebalance_gestrand(uren_geleden=5),
        {"id": "TRR_later", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 401.83,
         "aave_withdrawn_at": _iso(4), "completed_at": _iso(3)},
    ]
    sm, monitor = _monitor(tmp_path, voorstellen)
    aanroepen = []

    def tel(methode, params):
        aanroepen.append(params[0].get("data"))
        return "0x0"

    with patch("utils.treasury_executor._rpc", tel):
        monitor._check_gestrand_rebalance_geld(nu)                       # meet, sluit af
        monitor._check_gestrand_rebalance_geld(nu + timedelta(minutes=5))
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=1))
    assert not monitor._send_telegram.called, "afgesloten geval meldt niet"
    assert len(aanroepen) == 2, "twee adressen, één meting per 6 uur — kreeg %d" % len(aanroepen)

    with patch("utils.treasury_executor._rpc", tel):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(hours=7))
    assert len(aanroepen) == 4, "na 6 uur mag hij opnieuw meten"


def test_mislukte_melding_geeft_geen_stilte(tmp_path, monkeypatch):
    """A1-audit ronde 2: `_send_telegram` slikte fouten in, dus stempelen ná de melding
    betekende niets. Nu geeft hij False terug en blijft de melding openstaan."""
    monkeypatch.chdir(tmp_path)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand()])
    monitor._send_telegram = MagicMock(return_value=False)
    nu = datetime.now(timezone.utc)
    for wanneer in (nu, nu + timedelta(minutes=5), nu + timedelta(hours=2)):
        with patch("utils.treasury_executor._rpc", _saldo(0.0)):
            monitor._check_gestrand_rebalance_geld(wanneer)
    assert monitor._send_telegram.call_count == 2, (
        "mislukte melding mag niet stempelen, maar wel een uur afremmen: "
        "poging 1 en 3 wel, poging binnen dat uur niet")


def test_twee_verschillende_strandingen_melden_allebei(tmp_path, monkeypatch):
    """De cooldown hangt aan het voorstel-id, niet aan de check."""
    monkeypatch.chdir(tmp_path)
    nu = datetime.now(timezone.utc)
    sm, monitor = _monitor(tmp_path, [_rebalance_gestrand(uren_geleden=6, id="TRR_EEN")])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(nu)
    assert "TRR_EEN" in monitor._send_telegram.call_args[0][0]

    (tmp_path / "treasury_proposals.json").write_text(json.dumps([
        _rebalance_gestrand(uren_geleden=6, id="TRR_EEN"),
        _rebalance_gestrand(uren_geleden=1, id="TRR_TWEE"),
    ]), encoding="utf-8")
    monitor._send_telegram.reset_mock()
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(nu + timedelta(minutes=5))
    assert monitor._send_telegram.called, "een nieuwe stranding moet wél melden"
    assert "TRR_TWEE" in monitor._send_telegram.call_args[0][0]


def test_opgelost_telt_alleen_als_er_ook_niets_meer_staat(tmp_path, monkeypatch):
    """A1-audit ronde 2: een latere geslaagde rebalance leegt alleen het VAULT-adres.

    Geld op de treasury-wallet blijft liggen, en onder $100 raakt ook het deploy-pad het
    niet aan — dan zou "opgelost" de melding uitzetten terwijl er geld renteloos staat.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HL_VAULT_ADDRESS", VAULT_ADR)
    voorstellen = [
        _rebalance_gestrand(uren_geleden=5),
        {"id": "TRR_later", "type": "REBALANCE", "status": "COMPLETED", "amount_usd": 401.83,
         "aave_withdrawn_at": _iso(4), "completed_at": _iso(3)},
    ]
    sm, blijft = _monitor(tmp_path, voorstellen)
    with patch("utils.treasury_executor._rpc", _saldo(60.0)):
        blijft._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert blijft._send_telegram.called, "$60 blijft liggen: blijven melden"

    sm, stil = _monitor(tmp_path, voorstellen)
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        stil._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert not stil._send_telegram.called, "niets meer te bridgen: afsluiten"

    # onmeetbaar saldo mag NOOIT als "afgesloten" gelden — onmeetbaar is geen nul
    def kapot(methode, params):
        raise RuntimeError("All Arbitrum RPCs failed")

    sm, onzeker = _monitor(tmp_path, voorstellen)
    with patch("utils.treasury_executor._rpc", kapot):
        onzeker._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert onzeker._send_telegram.called, "onmeetbaar: blijven melden"

    # en zonder vault-adres weet de check niets over dat adres: ook dan doormelden
    monkeypatch.delenv("HL_VAULT_ADDRESS", raising=False)
    sm, geen_adres = _monitor(tmp_path, voorstellen)
    with patch("utils.treasury_executor._rpc", _saldo(0.0)), \
         patch("utils.gcp_secrets.get_secret", return_value=""):
        geen_adres._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    assert geen_adres._send_telegram.called, "vault-adres onbekend: niet stilzwijgend afsluiten"


def test_voorstel_zonder_id_meldt_geen_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    zonder = _rebalance_gestrand()
    zonder.pop("id")
    sm, monitor = _monitor(tmp_path, [zonder])
    with patch("utils.treasury_executor._rpc", _saldo(0.0)):
        monitor._check_gestrand_rebalance_geld(datetime.now(timezone.utc))
    tekst = monitor._send_telegram.call_args[0][0]
    assert "None" not in tekst and "voorstel zonder id" in tekst


def test_monitor_meldt_een_hangende_handmatige_opname(tmp_path, monkeypatch):
    from agents import swarm_monitor as sm
    monkeypatch.chdir(tmp_path)
    (tmp_path / "treasury_proposals.json").write_text(json.dumps(
        [dict(_voorstel(), created_at=_iso(7), title="HL excess")]), encoding="utf-8")
    state_file = os.path.join(tempfile.gettempdir(), "monitor_alert_state_TEST_ONLY.json")
    with patch.object(sm.SwarmMonitor, "ALERT_STATE_FILE", state_file):
        monitor = sm.SwarmMonitor(db_client=MagicMock())
    monitor._send_telegram = MagicMock()
    with patch.object(sm, "_telegram_token", return_value="t"), \
         patch.object(sm, "_telegram_chat_id", return_value="c"):
        monitor._check_stuck_proposals(datetime.now(timezone.utc))
    assert monitor._send_telegram.called
    assert "NEEDS_MANUAL_WITHDRAWAL" in monitor._send_telegram.call_args[0][0]
