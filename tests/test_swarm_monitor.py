"""
Unit tests for SwarmMonitor health checks.

Prevents regressions like:
- NoneType comparison errors when Supabase returns null cycle_count
- Crashes in _check_supabase_health / _check_pipeline_output on unexpected None values
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.swarm_monitor import SwarmMonitor


def _make_monitor():
    """Return a SwarmMonitor with a mocked db client."""
    monitor = SwarmMonitor.__new__(SwarmMonitor)
    monitor.db = MagicMock()
    monitor.logger = MagicMock()
    monitor._prev_check_time = None
    monitor._prev_cycle_counts = {}
    monitor._prev_output_snapshots = {}
    monitor._check_count = 1
    monitor._last_alert_time = None
    return monitor


def _agent(name, cycle_count=1, status="IDLE", meta=None, last_pulse=None):
    """Build a fake swarm_health row."""
    if last_pulse is None:
        last_pulse = datetime.now(tz=timezone.utc).isoformat()
    return {
        "agent_name": name,
        "cycle_count": cycle_count,
        "status": status,
        "last_pulse": last_pulse,
        "metadata": meta or {},
        "last_error": None,
    }


def _mock_db_with_agents(monitor, rows):
    """Wire monitor.db so that swarm_health queries return `rows`."""
    result_mock = MagicMock()
    result_mock.data = rows
    monitor.db.client.table.return_value.select.return_value.execute.return_value = result_mock
    # Also handle chained queries (order/limit) used by ProductOwner backlog check
    monitor.db.client.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])


# ---------------------------------------------------------------------------
# Test: null cycle_count from Supabase must not crash comparisons
# ---------------------------------------------------------------------------

def test_check_supabase_health_null_cycle_count_does_not_crash():
    """_check_supabase_health must not raise TypeError when cycle_count is None (Supabase null)."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=None, status="IDLE")])
    # Should not raise
    issues = monitor._check_supabase_health(now)
    assert isinstance(issues, list)


def test_check_pipeline_output_null_cycle_count_does_not_crash():
    """_check_pipeline_output must not raise TypeError when cycle_count is None."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    rows = [
        _agent("Scout", cycle_count=None, meta={"scanned_count": 0, "approved_count": 0, "total_universe": 0}),
        _agent("ProjectLead", cycle_count=None, status="IDLE", meta={"latest_decisions": []}),
        _agent("PerformanceAuditor", cycle_count=None),
        _agent("ProductOwner", cycle_count=None),
        _agent("Heartbeat", cycle_count=None),
    ]
    _mock_db_with_agents(monitor, rows)
    issues = monitor._check_pipeline_output(now)
    assert isinstance(issues, list)


def test_frozen_cycle_detection_with_null_count():
    """Second check with null cycle_count must not crash frozen-cycle detection."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    # Seed previous state
    monitor._prev_check_time = now - timedelta(minutes=20)
    monitor._prev_cycle_counts["Heartbeat"] = 0
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=None)])
    issues = monitor._check_supabase_health(now)
    assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# Test: normal operation still works
# ---------------------------------------------------------------------------

def test_healthy_agents_produce_no_agent_errors():
    """Agents with recent pulses and IDLE status produce no AGENT_ERROR/AGENT_STALE issues."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    _mock_db_with_agents(monitor, [
        _agent("Heartbeat", cycle_count=5, status="ACTIVE"),
        _agent("ProjectLead", cycle_count=5, status="IDLE"),
    ])
    issues = monitor._check_supabase_health(now)
    assert not any(i["type"] in ("AGENT_ERROR", "AGENT_STALE") for i in issues)


def test_stale_heartbeat_flagged():
    """Heartbeat with a pulse > 30 min old must be flagged as AGENT_STALE."""
    monitor = _make_monitor()
    now = datetime.now(tz=timezone.utc)
    old_pulse = (now - timedelta(minutes=45)).isoformat()
    _mock_db_with_agents(monitor, [_agent("Heartbeat", cycle_count=3, status="IDLE", last_pulse=old_pulse)])
    issues = monitor._check_supabase_health(now)
    stale = [i for i in issues if i["type"] == "AGENT_STALE" and i["agent"] == "Heartbeat"]
    assert stale, "Expected AGENT_STALE for Heartbeat with 45-min-old pulse"
