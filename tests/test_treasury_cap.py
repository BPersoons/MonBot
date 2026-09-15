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


def test_oude_fouten_en_andere_types_tellen_niet():
    agent = _agent()
    oud = [_fout(30), _fout(40)]
    ander = [dict(_fout(1), type="FUND_SLEEVE"), dict(_fout(2), type="FUND_SLEEVE")]
    assert agent._deploy_geblokkeerd(oud + ander) is False
