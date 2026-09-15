"""Pre-deploy-poort: de state-audit vangt drift tussen compose-mounts en STATE_FILES."""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from scripts.predeploy import state_audit  # noqa: E402

COMPOSE = """
services:
  swarm:
    volumes:
      - ./data:/app/data
      - ./trade_log.json:/app/trade_log.json
      - ./a_state.json:/app/a_state.json
      - ./b_state.json:/app/b_state.json
"""
DEPLOY = '''
STATE_FILES="a_state.json c_state.json"
for f in $STATE_FILES trade_log.json; do backup; done
sudo chmod 666 trade_log.json
'''


def test_audit_vindt_drift_in_beide_richtingen():
    fouten = state_audit(COMPOSE, DEPLOY)
    assert any("c_state.json" in f and "niet gemount" in f for f in fouten)
    assert any("b_state.json" in f and "niet in STATE_FILES" in f for f in fouten)
    assert not any("a_state.json" in f for f in fouten)
    assert not any("trade_log.json" in f for f in fouten)


def test_audit_mist_state_files_regel():
    assert state_audit(COMPOSE, "echo geen state") == [
        "STATE_FILES niet gevonden in scripts/deploy_update.sh"]


def test_de_echte_repo_is_consistent():
    """Draait tegen de echte bestanden: faalt zodra er weer een statebestand drift."""
    with open(os.path.join(REPO, "docker-compose.prod.yml"), encoding="utf-8") as fh:
        compose = fh.read()
    with open(os.path.join(REPO, "scripts", "deploy_update.sh"), encoding="utf-8") as fh:
        deploy = fh.read()
    assert state_audit(compose, deploy) == []
