"""Kasbeheer: cap per protocol op nieuw geld en een rem op herhaald mislukte deploys.

Beide uit de A2-audit van 2026-09-15 op Fluid:
- zonder cap kon nieuw geld (en een switch) 100% van het veilige potje in één nieuw
  protocol zetten, zonder dat iemand dat besloot;
- een mislukte deposit leidde elke 5 cycli tot een nieuwe poging, met gas, zonder einde.
"""
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import treasury_agent as ta  # noqa: E402

BENCH = "aave-v3-arbitrum-usdc"


def _opp(pid, apy=3.0, automated=True):
    return {"label": pid, "apy": apy, "risk_adjusted_apy": apy, "automated": automated,
            "chain": "Arbitrum", "protocol_config": {"id": pid, "label": pid}}


def _alloc(pid, bedrag):
    return {"protocol_id": pid, "protocol_config": {"id": pid}, "amount_usd": bedrag,
            "apy": 4.0, "tranche": "yield_core"}


@pytest.fixture(autouse=True)
def cap_65():
    with patch.object(ta, "_max_aandeel_per_protocol", return_value=(0.65, BENCH)):
        yield


def test_nieuw_geld_boven_de_cap_gaat_naar_de_benchmark():
    # Potje 1000 (alles Aave) + 1000 nieuw = 2000; Fluid mag max 1300 -> 1300 Fluid, 700 Aave.
    uit = ta.TreasuryAgent._begrens_allocaties(
        [_alloc("fluid", 1000.0)], [_opp(BENCH), _opp("fluid")], {BENCH: 1000.0}, 1000.0)
    per = {a["protocol_id"]: a["amount_usd"] for a in uit}
    assert per == {"fluid": 1000.0}, "binnen de cap: ongemoeid"

    uit = ta.TreasuryAgent._begrens_allocaties(
        [_alloc("fluid", 1000.0)], [_opp(BENCH), _opp("fluid")], {BENCH: 0.0, "fluid": 800.0}, 1000.0)
    per = {a["protocol_id"]: a["amount_usd"] for a in uit}
    # totaal na = 1800, cap Fluid 1170, al 800 -> nog 370 erbij, 630 naar Aave
    assert per == {"fluid": 370.0, BENCH: 630.0}
    assert sum(per.values()) == 1000.0, "er mag geen geld verdwijnen"


def test_zonder_benchmark_blijft_het_teveel_op_de_wallet():
    uit = ta.TreasuryAgent._begrens_allocaties(
        [_alloc("fluid", 1000.0)], [_opp("fluid")], {"fluid": 800.0}, 1000.0)
    assert [(a["protocol_id"], a["amount_usd"]) for a in uit] == [("fluid", 370.0)]


def test_benchmark_zelf_wordt_niet_begrensd():
    uit = ta.TreasuryAgent._begrens_allocaties(
        [_alloc(BENCH, 2000.0)], [_opp(BENCH)], {BENCH: 5000.0}, 2000.0)
    assert uit[0]["amount_usd"] == 2000.0


def test_restbedrag_onder_minimum_gaat_helemaal_naar_de_benchmark():
    # ruimte voor Fluid is $40 (< _MIN_DEPLOY_USD) -> geen losse micro-deploy, alles Aave
    uit = ta.TreasuryAgent._begrens_allocaties(
        [_alloc("fluid", 500.0)], [_opp(BENCH), _opp("fluid")], {"fluid": 1260.0}, 500.0)
    per = {a["protocol_id"]: a["amount_usd"] for a in uit}
    assert per == {BENCH: 500.0}


def _agent():
    agent = ta.TreasuryAgent()
    agent._verstuurd = []
    agent._send_telegram = agent._verstuurd.append
    return agent


def _fout(uren_geleden, soort="DEPLOY_YIELD"):
    return {"id": "F%d" % uren_geleden, "type": soort, "status": "FAILED", "error": "revert",
            "updated_at": (datetime.utcnow() - timedelta(hours=uren_geleden)).isoformat()}


def test_deploys_geblokkeerd_na_twee_fouten_in_24u():
    agent = _agent()
    assert agent._deploy_geblokkeerd([_fout(1)]) is False
    assert agent._deploy_geblokkeerd([_fout(1), _fout(2, "YIELD_SWITCH")]) is True
    assert len(agent._verstuurd) == 1
    agent._deploy_geblokkeerd([_fout(1), _fout(2)])
    assert len(agent._verstuurd) == 1, "de melding komt maximaal één keer per 24 uur"


def test_cap_op_nieuw_geld_gebruikt_strikte_saldi_ook_zonder_yield_balances():
    """A1-audit: run_fast gaf geen yield_balances mee, waardoor de cap daar niets deed."""
    agent = _agent()
    agent._optimizer = None
    opps = [_opp(BENCH, apy=2.6), dict(_opp("fluid", apy=9.0), risk_adjusted_apy=8.0)]
    for o in opps:
        o["protocol_config"]["type"] = "aave_v3" if o["protocol_config"]["id"] == BENCH else "erc4626"
    with patch.object(agent, "_compute_target_allocation",
                      return_value={"target_trade_usd": 0, "effective_trade_pct": 0, "reason": "toets"}), \
         patch("utils.treasury_executor.get_total_yield_balance", return_value=0.0), \
         patch.object(agent, "_strikte_yield_saldi", return_value={BENCH: 0.0, "fluid": 2000.0}):
        voorstellen = agent.generate_proposals({"balance": 0}, opps, treasury_usdc=1000.0)
    per = {p["protocol_id"]: p["amount_usd"] for p in voorstellen if p["type"] == "DEPLOY_YIELD"}
    assert per == {BENCH: 1000.0}, "Fluid zit al boven de cap: alles naar de benchmark"


def test_onleesbare_saldi_sturen_nieuw_geld_naar_de_benchmark():
    agent = _agent()
    agent._optimizer = None
    opps = [_opp(BENCH, apy=2.6), dict(_opp("fluid", apy=9.0), risk_adjusted_apy=8.0)]
    with patch.object(agent, "_compute_target_allocation",
                      return_value={"target_trade_usd": 0, "effective_trade_pct": 0, "reason": "toets"}), \
         patch("utils.treasury_executor.get_total_yield_balance", return_value=0.0), \
         patch.object(agent, "_strikte_yield_saldi", return_value=None):
        voorstellen = agent.generate_proposals({"balance": 0}, opps, treasury_usdc=1000.0)
    per = {p["protocol_id"]: p["amount_usd"] for p in voorstellen if p["type"] == "DEPLOY_YIELD"}
    assert per == {BENCH: 1000.0}


def test_rem_zit_voor_switch_diversificatie_hl_excess_en_deploy_in_run_fast():
    """Aansluitingstoets (A1-audit bevinding 8): losse functies toetsen is niet genoeg."""
    from unittest.mock import MagicMock
    for geblokkeerd in (True, False):
        agent = _agent()
        fouten = [_fout(1), _fout(2)] if geblokkeerd else []
        agent.get_hl_snapshot = MagicMock(return_value={"balance": 100.0, "free_margin": 90.0})
        agent._load_proposals = MagicMock(return_value=list(fouten))
        agent._check_rebalance_needed = MagicMock(side_effect=lambda hl, p: p)
        agent._load_cached_opportunities = MagicMock(return_value=[_opp(BENCH)])
        agent._get_yield_balances = MagicMock(return_value={BENCH: 1000.0})
        agent._check_yield_switch = MagicMock(side_effect=lambda o, y, p: (p, []))
        agent._check_yield_diversification = MagicMock(side_effect=lambda o, y, p: (p, []))
        agent._check_hl_excess = MagicMock(side_effect=lambda hl, p, o: p)
        agent.generate_proposals = MagicMock(return_value=[])
        agent._monitor_funding_harvest = MagicMock()
        agent._execute_fund_sleeve = MagicMock(side_effect=lambda p: p)
        agent._execute_sleeve_rebalance = MagicMock(side_effect=lambda p: p)
        agent.execute_approved_proposals = MagicMock(side_effect=lambda p: p)
        agent._save_proposals = MagicMock()
        with patch("utils.treasury_executor.get_arb_usdc_balance", return_value=500.0):
            agent.run_fast()
        aangeroepen = {
            "switch": agent._check_yield_switch.called,
            "diversificatie": agent._check_yield_diversification.called,
            "hl_excess": agent._check_hl_excess.called,
            "deploy": agent.generate_proposals.called,
        }
        if geblokkeerd:
            assert not any(aangeroepen.values()), "rem niet overal: %s" % aangeroepen
        else:
            assert all(aangeroepen.values()), "zonder fouten moet alles draaien: %s" % aangeroepen


def test_rem_zit_voor_switch_diversificatie_hl_excess_en_deploy_in_run(tmp_path, monkeypatch):
    """A1-audit ronde 2: dezelfde aansluitingstoets als voor run_fast, nu voor run()."""
    from unittest.mock import MagicMock
    monkeypatch.chdir(tmp_path)   # run() schrijft treasury_state.json in de werkmap
    for geblokkeerd in (True, False):
        agent = _agent()
        fouten = [_fout(1), _fout(2)] if geblokkeerd else []
        agent.get_hl_snapshot = MagicMock(return_value={"balance": 100.0, "free_margin": 90.0})
        agent.get_yield_opportunities = MagicMock(return_value=[_opp(BENCH)])
        agent._get_yield_balances = MagicMock(return_value={BENCH: 1000.0})
        agent._compute_target_allocation = MagicMock(return_value={})
        agent._get_sleeve_allocation = MagicMock(return_value={"total": 0.0})
        agent._load_proposals = MagicMock(return_value=list(fouten))
        agent.generate_proposals = MagicMock(return_value=[])
        agent._upsert_proposals = MagicMock(return_value=[])
        agent._check_rebalance_needed = MagicMock(side_effect=lambda hl, p: p)
        agent._check_hl_excess = MagicMock(side_effect=lambda hl, p, o: p)
        agent._check_yield_switch = MagicMock(side_effect=lambda o, y, p: (p, []))
        agent._check_yield_diversification = MagicMock(side_effect=lambda o, y, p: (p, []))
        agent._check_funding_harvest = MagicMock()
        agent._monitor_funding_harvest = MagicMock()
        agent._check_sleeve_funding = MagicMock(side_effect=lambda s, g, hl, p: (p, []))
        agent._execute_fund_sleeve = MagicMock(side_effect=lambda p: p)
        agent._check_sleeve_rebalance = MagicMock(side_effect=lambda s, g, p: (p, []))
        agent._execute_sleeve_rebalance = MagicMock(side_effect=lambda p: p)
        agent.execute_approved_proposals = MagicMock(side_effect=lambda p: p)
        agent._save_proposals = MagicMock()
        agent._get_harvest_state = MagicMock(return_value={})
        with patch("utils.treasury_executor.get_arb_usdc_balance", return_value=500.0):
            agent.run()
        aangeroepen = {
            "switch": agent._check_yield_switch.called,
            "diversificatie": agent._check_yield_diversification.called,
            "hl_excess": agent._check_hl_excess.called,
            "deploy": agent.generate_proposals.called,
        }
        if geblokkeerd:
            assert not any(aangeroepen.values()), "rem niet overal in run(): %s" % aangeroepen
        else:
            assert all(aangeroepen.values()), "zonder fouten moet alles draaien: %s" % aangeroepen


def _deploy_onderweg(status="BRIDGED"):
    return {"id": "TRP_x", "type": "DEPLOY_YIELD", "status": status, "protocol_id": "fluid"}


def _switch_agent(strikt):
    agent = _agent()
    agent._strikte_yield_saldi = lambda: dict(strikt)
    agent._load_protocol_config = lambda: [{"id": BENCH, "label": BENCH, "type": "aave_v3"},
                                           {"id": "fluid", "label": "fluid", "type": "erc4626"}]
    return agent


def test_geen_switch_zolang_een_deploy_onderweg_is():
    """A1-audit ronde 2: de cap ziet geld onderweg niet, dus geen twee bewegingen tegelijk."""
    opps = [_opp(BENCH, apy=2.6), dict(_opp("fluid", apy=9.0), risk_adjusted_apy=8.0)]
    saldi = {BENCH: 1000.0}
    zonder, _ = _switch_agent({BENCH: 1000.0, "fluid": 0.0})._check_yield_switch(opps, saldi, [])
    assert [p["type"] for p in zonder] == ["YIELD_SWITCH"], "controle: zonder deploy onderweg wél een switch"
    for status in ("APPROVED", "WITHDRAWING", "NEEDS_MANUAL_WITHDRAWAL", "BRIDGED"):
        met, _ = _switch_agent({BENCH: 1000.0, "fluid": 0.0})._check_yield_switch(
            opps, saldi, [_deploy_onderweg(status)])
        assert [p["type"] for p in met] == ["DEPLOY_YIELD"], status


def test_geen_yield_beweging_tijdens_een_rebalance():
    """A1-audit V6: rebalance en switch trekken aan dezelfde Aave-positie en wallet."""
    opps = [_opp(BENCH, apy=2.6), dict(_opp("fluid", apy=9.0), risk_adjusted_apy=8.0)]
    saldi = {BENCH: 1000.0}
    zonder, _ = _switch_agent({BENCH: 1000.0, "fluid": 0.0})._check_yield_switch(opps, saldi, [])
    assert [p["type"] for p in zonder] == ["YIELD_SWITCH"], "controle: zonder rebalance wél een switch"
    for status in ("APPROVED", "REBALANCING", "BRIDGE_BACK_NEEDED", "BRIDGING_TO_HL"):
        lopend = [{"id": "TRR_x", "type": "REBALANCE", "status": status}]
        met, _ = _switch_agent({BENCH: 1000.0, "fluid": 0.0})._check_yield_switch(opps, saldi, lopend)
        assert [p["type"] for p in met] == ["REBALANCE"], status
    # een afgeronde rebalance blokkeert niets
    klaar = [{"id": "TRR_y", "type": "REBALANCE", "status": "COMPLETED"}]
    weer, _ = _switch_agent({BENCH: 1000.0, "fluid": 0.0})._check_yield_switch(opps, saldi, klaar)
    assert [p["type"] for p in weer] == ["REBALANCE", "YIELD_SWITCH"]


def test_geen_diversificatie_zolang_een_deploy_onderweg_is():
    opps = [_opp(BENCH, apy=2.6), _opp("fluid", apy=2.5)]
    saldi = {BENCH: 1000.0, "fluid": 50.0}
    zonder, _ = _switch_agent(saldi)._check_yield_diversification(opps, saldi, [])
    assert [p.get("diversification") for p in zonder] == [True], "controle: zonder deploy wél diversificatie"
    met, _ = _switch_agent(saldi)._check_yield_diversification(opps, saldi, [_deploy_onderweg()])
    assert [p["type"] for p in met] == ["DEPLOY_YIELD"]


def test_geen_hl_overschot_zolang_een_switch_loopt():
    from unittest.mock import MagicMock
    hl = {"balance": 1000.0, "free_margin": 900.0}
    for status, verwacht_gelezen in ((None, True), ("APPROVED", False), ("SWITCHING", False)):
        agent = _agent()
        voorstellen = [] if status is None else [{"id": "TRS_x", "type": "YIELD_SWITCH", "status": status}]
        saldo = MagicMock(return_value=0.0)
        with patch("utils.treasury_executor.get_total_yield_balance", saldo), \
             patch("utils.treasury_executor.get_arb_usdc_balance", return_value=0.0), \
             patch.object(agent, "_compute_target_allocation", return_value={"target_trade_usd": 1000.0}):
            uit = agent._check_hl_excess(hl, voorstellen, [_opp(BENCH)])
        assert saldo.called is verwacht_gelezen, status
        assert uit == voorstellen


def test_run_fast_geen_deploy_in_de_ronde_waarin_een_switch_ontstaat():
    """A1-hertoets: de switch-check maakt een APPROVED-switch, daarna mocht generate nog."""
    from unittest.mock import MagicMock
    for switch_vuurt in (False, True):
        agent = _agent()
        agent.get_hl_snapshot = MagicMock(return_value={"balance": 0.0, "free_margin": 0.0})
        agent._load_proposals = MagicMock(return_value=[])
        agent._check_rebalance_needed = MagicMock(side_effect=lambda hl, p: p)
        agent._load_cached_opportunities = MagicMock(return_value=[_opp(BENCH)])
        agent._get_yield_balances = MagicMock(return_value={BENCH: 1000.0})

        def switch(o, y, p, vuurt=switch_vuurt):
            if vuurt:
                p = p + [{"id": "TRS_x", "type": "YIELD_SWITCH", "status": "APPROVED"}]
            return p, []
        agent._check_yield_switch = MagicMock(side_effect=switch)
        agent._check_yield_diversification = MagicMock(side_effect=lambda o, y, p: (p, []))
        agent._check_hl_excess = MagicMock(side_effect=lambda hl, p, o: p)
        agent.generate_proposals = MagicMock(return_value=[])
        agent._monitor_funding_harvest = MagicMock()
        agent._execute_fund_sleeve = MagicMock(side_effect=lambda p: p)
        agent._execute_sleeve_rebalance = MagicMock(side_effect=lambda p: p)
        agent.execute_approved_proposals = MagicMock(side_effect=lambda p: p)
        agent._save_proposals = MagicMock()
        with patch("utils.treasury_executor.get_arb_usdc_balance", return_value=500.0):
            agent.run_fast()
        assert agent.generate_proposals.called is (not switch_vuurt), "switch_vuurt=%s" % switch_vuurt


def test_run_doet_eerst_de_rebalance_en_daarna_pas_een_deploy(tmp_path, monkeypatch):
    """A1-audit bevinding 1: in run() ontstond de deploy vóór de rebalance — beide in één
    cyclus, wallet→Aave en Aave→wallet tegelijk. In productie 2× gebeurd (18-07, 23-07)."""
    from unittest.mock import MagicMock
    monkeypatch.chdir(tmp_path)
    volgorde = []
    agent = _agent()
    agent.get_hl_snapshot = MagicMock(return_value={"balance": 100.0, "free_margin": 90.0})
    agent.get_yield_opportunities = MagicMock(return_value=[_opp(BENCH)])
    agent._get_yield_balances = MagicMock(return_value={BENCH: 1000.0})
    agent._compute_target_allocation = MagicMock(return_value={})
    agent._get_sleeve_allocation = MagicMock(return_value={"total": 0.0})
    agent._load_proposals = MagicMock(return_value=[])

    def rebalance(hl, p):
        volgorde.append("rebalance")
        return list(p) + [{"id": "TRR_x", "type": "REBALANCE", "status": "APPROVED"}]
    agent._check_rebalance_needed = MagicMock(side_effect=rebalance)

    def generate(*a, **k):
        volgorde.append("deploy")
        return []
    agent.generate_proposals = MagicMock(side_effect=generate)
    agent._upsert_proposals = MagicMock(return_value=[])
    agent._check_hl_excess = MagicMock(side_effect=lambda hl, p, o: p)
    agent._check_yield_switch = MagicMock(side_effect=lambda o, y, p: (p, []))
    agent._check_yield_diversification = MagicMock(side_effect=lambda o, y, p: (p, []))
    agent._check_funding_harvest = MagicMock()
    agent._monitor_funding_harvest = MagicMock()
    agent._check_sleeve_funding = MagicMock(side_effect=lambda s, g, hl, p: (p, []))
    agent._execute_fund_sleeve = MagicMock(side_effect=lambda p: p)
    agent._check_sleeve_rebalance = MagicMock(side_effect=lambda s, g, p: (p, []))
    agent._execute_sleeve_rebalance = MagicMock(side_effect=lambda p: p)
    agent.execute_approved_proposals = MagicMock(side_effect=lambda p: p)
    agent._save_proposals = MagicMock()
    agent._get_harvest_state = MagicMock(return_value={})
    with patch("utils.treasury_executor.get_arb_usdc_balance", return_value=500.0):
        agent.run()
    assert volgorde == ["rebalance"], "de rebalance draait eerst en blokkeert de deploy: %s" % volgorde


def test_tweede_rebalance_kan_niet_ontstaan_tijdens_het_bridgen():
    """A1-audit bevinding 3: BRIDGING_TO_HL zat niet in de eigen guard van de rebalance."""
    from unittest.mock import MagicMock
    hl = {"balance": 10.0, "free_margin": 10.0}
    for status in ("APPROVED", "REBALANCING", "BRIDGE_BACK_NEEDED", "BRIDGING_TO_HL"):
        agent = _agent()
        agent._compute_target_allocation = MagicMock(
            return_value={"target_trade_usd": 1000.0, "effective_trade_pct": 30, "reason": "toets"})
        agent._load_allocation_config = MagicMock(return_value={"rebalance_drift_pct": 10})
        lopend = [{"id": "TRR_a", "type": "REBALANCE", "status": status}]
        with patch("utils.treasury_executor.get_aave_balance", return_value=2000.0):
            uit = agent._check_rebalance_needed(hl, list(lopend))
        assert uit == lopend, "geen tweede rebalance tijdens %s" % status


def test_telegram_valt_terug_op_platte_tekst():
    """A1-audit bevinding 7: een melding die Telegram niet parseert ging volledig verloren."""
    pogingen = []

    class _Antwoord:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=10):
        import json as _j
        pogingen.append(_j.loads(req.data.decode("utf-8")))
        if len(pogingen) == 1:
            raise RuntimeError("Bad Request: can't parse entities")
        return _Antwoord()

    agent = ta.TreasuryAgent()
    with patch.object(ta, "_telegram_token", return_value="t"), \
         patch.object(ta, "_telegram_chat_id", return_value="c"), \
         patch("urllib.request.urlopen", urlopen):
        agent._send_telegram("*vet* `yield_core` _kapot")
    assert len(pogingen) == 2, "geen tweede poging zonder opmaak"
    assert pogingen[0].get("parse_mode") == "Markdown"
    assert "parse_mode" not in pogingen[1]
    assert pogingen[1]["text"] == "*vet* `yield_core` _kapot", "tekst blijft ongewijzigd"


def test_de_twee_echte_botsingen_van_juli_kunnen_niet_meer():
    """Regressie op de échte tijdstempels uit treasury_proposals.json.

    18-07: TRP_20260718_1904_0 aangemaakt om 19:04:48.928, terwijl TRR_20260718_1852 om
    19:04:48.932 zijn Aave-opname bevestigde. 23-07: TRP_20260723_1447_excess deployed om
    15:14:28, veertien seconden vóór aave_withdrawn_at 15:14:42 van TRR_20260723_1501.
    In beide gevallen vochten een deploy en een rebalance om dezelfde dollars.
    """
    for datum, rebalance_status in (("2026-07-18", "APPROVED"), ("2026-07-23", "BRIDGE_BACK_NEEDED")):
        lopend = [{"id": "TRR_%s" % datum, "type": "REBALANCE", "status": rebalance_status,
                   "amount_usd": 267.28, "aave_withdrawn_at": "%sT15:14:42" % datum}]
        assert ta._yield_beweging_onderweg(lopend) is True, (
            "een rebalance in %s moet elke nieuwe yield-beweging blokkeren" % rebalance_status)


def test_oude_fouten_en_andere_types_tellen_niet():
    agent = _agent()
    oud = [_fout(30), _fout(40)]
    ander = [dict(_fout(1), type="FUND_SLEEVE"), dict(_fout(2), type="FUND_SLEEVE")]
    assert agent._deploy_geblokkeerd(oud + ander) is False
