import pytest
from unittest.mock import MagicMock, patch
from agents.project_lead import ProjectLead

@pytest.fixture
def project_lead():
    with patch('utils.db_client.DatabaseClient'), \
         patch('agents.project_lead.TechnicalAnalyst'), \
         patch('agents.project_lead.FundamentalAnalyst'), \
         patch('agents.project_lead.SentimentAnalyst'):
        
        pl = ProjectLead()
        # Mock dependencies heavily to test pure routing logic
        pl.execution_agent = MagicMock()
        pl.risk_manager = MagicMock()
        pl.dashboard_provider = MagicMock()
        return pl

def test_project_lead_build_case_no_unbound_error(project_lead):
    """Test that a BUILD_CASE decision returns a valid dictionary without UnboundLocalError"""
    details = {
        'technical': {'signal': 1.0, 'price': 50.0},
        'fundamental': {'signal': 1.0},
        'sentiment': {'signal': 1.0},
        'strategy_mode': 'STANDARD'
    }
    # Force the LLM simulation to return BUILD_CASE
    project_lead.synthesize_signals = MagicMock(return_value={
        "next_step": "BUILD_CASE",
        "bull_case": "Test Bull",
        "bear_case": "Test Bear",
        "target_entry_price": 50.0,
        "combined_score": 2.5,
        "details": details
    })
    
    # Mock Risk Manager to approve
    project_lead.risk_manager.validate_trade_proposal = MagicMock(return_value={
        "approved": True,
        "metrics": {"recommended_allocation_usdt": 100}
    })
    
    # Mock execution to succeed
    project_lead.execution_agent.execute_order = MagicMock(return_value={"id": "mock_trade"})
    
    market_context = {}
    
    with patch('utils.narrator.NarrativeGenerator') as MockNarrator:
        mock_narrator_instance = MockNarrator.return_value
        mock_narrator_instance.generate_business_case.return_value = {
            'narrative_status': 'VALID',
            'thesis': 'Mocked Thesis',
            'anti_thesis': 'Mocked Anti-Thesis',
            'synthesis': 'Mocked Synthesis'
        }
        
        result = project_lead.process_opportunity("TEST", market_context=market_context)
    
    assert "target_entry_price" in result
    assert result["target_entry_price"] == 50.0
    assert result["status"] == "BUY"

def test_project_lead_monitor_no_unbound_error(project_lead):
    """Test that a MONITOR decision returns a valid dictionary without UnboundLocalError for current_price"""
    details = {
        'technical': {'signal': 0.5, 'price': 50.0}, # Note price is 50, but target is 48
        'fundamental': {'signal': 0.5},
        'sentiment': {'signal': 0.5},
        'strategy_mode': 'STANDARD'
    }
    # Force the LLM simulation to return MONITOR
    project_lead.synthesize_signals = MagicMock(return_value={
        "next_step": "MONITOR",
        "bull_case": "Test Bull",
        "bear_case": "Test Bear",
        "target_entry_price": 48.0,
        "combined_score": 1.5,
        "details": details
    })
    
    market_context = {}
    
    result = project_lead.process_opportunity("TEST", market_context=market_context)
    
    assert "target_entry_price" in result
    assert result["target_entry_price"] == 48.0
    assert result["status"] == "MONITOR"

def test_project_lead_no_go_no_unbound_error(project_lead):
    """Test that a NO_GO decision returns a valid dictionary without UnboundLocalError"""
    details = {
        'technical': {'signal': -1.0, 'price': 50.0}, 
        'fundamental': {'signal': -1.0},
        'sentiment': {'signal': -1.0},
        'strategy_mode': 'STANDARD'
    }
    # Force the LLM simulation to return NO_GO
    project_lead.synthesize_signals = MagicMock(return_value={
        "next_step": "NO_GO",
        "bull_case": "Test Bull",
        "bear_case": "Test Bear",
        "combined_score": -3.0,
        "details": details
    })
    
    market_context = {}
    
    result = project_lead.process_opportunity("TEST", market_context=market_context)
    
    assert "target_entry_price" in result
    assert result["target_entry_price"] == 50.0  # Should fallback to current_price without crashing
    assert result["status"] == "NO_GO"
