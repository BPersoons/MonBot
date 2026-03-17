"""Tests for SwarmLearner agent."""
import json
import os
import pytest
from unittest.mock import MagicMock, patch
from agents.swarm_learner import SwarmLearner


@pytest.fixture
def learner():
    """Create a SwarmLearner with mocked dependencies."""
    with patch("agents.swarm_learner.LLMClient", side_effect=Exception("no LLM")):
        sl = SwarmLearner(exchange_client=None, db_client=None)
    return sl


@pytest.fixture
def sample_history():
    return [
        {"ticker": "BTC/USDC", "score": 0.45, "decision": "BUILD_CASE",
         "reason": "[STANDARD] Tech: +0.50 [RSI:55] | Fund: +0.30 | Sent: +0.20",
         "current_price": 60000, "direction": "LONG", "timestamp": "2025-01-01T00:00:00"},
        {"ticker": "ETH/USDC", "score": 0.35, "decision": "NO_GO",
         "reason": "[STANDARD] Tech: +0.25 | Fund: +0.10 | Sent: +0.15",
         "current_price": 3000, "direction": "LONG", "timestamp": "2025-01-01T01:00:00"},
        {"ticker": "SOL/USDC", "score": 0.20, "decision": "NO_GO",
         "reason": "[STANDARD] Tech: +0.10 | Fund: +0.05 | Sent: +0.08",
         "current_price": 100, "direction": "LONG", "timestamp": "2025-01-01T02:00:00"},
        {"ticker": "DOGE/USDC", "score": 0.55, "decision": "MONITOR",
         "reason": "[MOMENTUM] Tech: +0.60 | Fund: +0.40 | Sent: +0.30",
         "current_price": 0.15, "direction": "LONG", "timestamp": "2025-01-01T03:00:00"},
    ]


class TestSubscoreParsing:
    def test_parse_standard_format(self, learner):
        reason = "[STANDARD] Tech: +0.50 [RSI:55] | Fund: +0.30 | Sent: +0.20"
        assert learner._parse_subscore(reason, "Tech") == 0.50
        assert learner._parse_subscore(reason, "Fund") == 0.30
        assert learner._parse_subscore(reason, "Sent") == 0.20

    def test_parse_negative_scores(self, learner):
        reason = "Tech: -0.30 | Fund: -0.10 | Sent: +0.05"
        assert learner._parse_subscore(reason, "Tech") == -0.30
        assert learner._parse_subscore(reason, "Fund") == -0.10
        assert learner._parse_subscore(reason, "Sent") == 0.05

    def test_parse_missing_label(self, learner):
        reason = "No breakdown available"
        assert learner._parse_subscore(reason, "Tech") is None

    def test_parse_empty_string(self, learner):
        assert learner._parse_subscore("", "Tech") is None


class TestFunnelAnalysis:
    def test_funnel_counts(self, learner, sample_history):
        trades = [{"status": "OPEN"}, {"status": "CLOSED"}]
        result = learner._analyze_funnel(sample_history, trades)
        assert result["total_analyzed"] == 4
        assert result["passed_score_threshold"] == 2  # 0.45 and 0.55 >= 0.4
        assert result["llm_build_case"] == 1
        assert result["monitor_count"] == 1
        assert result["no_go_count"] == 2
        assert result["executed"] == 2

    def test_funnel_empty_history(self, learner):
        result = learner._analyze_funnel([], [])
        assert result["total_analyzed"] == 0


class TestIndicatorBottleneck:
    def test_identifies_lowest_contributor(self, learner, sample_history):
        result = learner._analyze_indicator_bottleneck(sample_history)
        assert result["lowest_contributor"] in ("tech", "fund", "sent")
        assert result["avg_scores"]["tech"] is not None
        assert result["avg_scores"]["fund"] is not None
        assert result["avg_scores"]["sent"] is not None

    def test_near_miss_counting(self, learner, sample_history):
        result = learner._analyze_indicator_bottleneck(sample_history)
        # score 0.35 is between 0.30 and 0.40 -> 1 near miss
        assert result["near_miss_count"] == 1


class TestThresholdImpact:
    def test_threshold_candidates_all_present(self, learner, sample_history):
        result = learner._analyze_threshold_impact(sample_history)
        for t in SwarmLearner.THRESHOLD_CANDIDATES:
            assert str(t) in result["thresholds"]

    def test_current_threshold_shows_current(self, learner, sample_history):
        result = learner._analyze_threshold_impact(sample_history)
        assert result["thresholds"]["0.4"]["delta"] == "current"

    def test_score_distribution_populated(self, learner, sample_history):
        result = learner._analyze_threshold_impact(sample_history)
        assert len(result["score_distribution"]) > 0


class TestMissedTrades:
    def test_no_exchange_returns_empty(self, learner, sample_history):
        result = learner._simulate_missed_trades(sample_history)
        # No exchange client -> _get_current_price returns 0.0 -> all skipped
        assert result == []

    def test_with_mock_exchange(self, learner, sample_history):
        mock_exchange = MagicMock()
        mock_exchange.get_market_price.return_value = 3500.0
        learner.exchange = mock_exchange
        result = learner._simulate_missed_trades(sample_history)
        # ETH and SOL are NO_GO with current_price > 0
        assert len(result) > 0
        assert all("hypothetical_pnl_pct" in r for r in result)


class TestRunLearningCycle:
    def test_empty_history_returns_empty(self, learner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = learner.run_learning_cycle()
        assert result == {}

    def test_full_cycle_produces_report(self, learner, tmp_path, monkeypatch, sample_history):
        monkeypatch.chdir(tmp_path)
        # Write sample decision history
        with open("decision_history.json", "w") as f:
            json.dump(sample_history, f)
        with open("trade_log.json", "w") as f:
            json.dump([{"status": "OPEN"}], f)

        result = learner.run_learning_cycle()

        assert "funnel" in result
        assert "indicator_bottleneck" in result
        assert "missed_trades" in result
        assert "threshold_impact" in result
        assert result["llm_summary"] == "LLM not available."

        # Check report file was written
        assert os.path.exists("learning_report.json")

        # Check dashboard was updated
        assert os.path.exists("dashboard.json")
        with open("dashboard.json") as f:
            dash = json.load(f)
        assert "learning_summary" in dash


class TestBacklogInsights:
    def test_builds_insights_from_report(self, learner, sample_history):
        trades = [{"status": "OPEN"}]
        report = {
            "funnel": learner._analyze_funnel(sample_history, trades),
            "indicator_bottleneck": learner._analyze_indicator_bottleneck(sample_history),
            "missed_trades": [],
            "threshold_impact": learner._analyze_threshold_impact(sample_history),
            "llm_summary": "Test summary for diagnostics.",
        }
        insights = learner._build_backlog_insights(report)
        # Should always produce at least a bottleneck insight
        assert len(insights) >= 1
        titles = [i["title"] for i in insights]
        assert any("[SwarmLearner]" in t for t in titles)
