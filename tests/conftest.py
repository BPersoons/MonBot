"""
Test Configuration and Fixtures
Shared pytest configuration for all tests.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_exchange_data():
    """Mock exchange data for testing."""
    return {
        'BTC/USDT': {
            'price': 45000.0,
            'volume': 1000000,
            'ohlcv': [
                [1609459200000, 44000, 45500, 43800, 45000, 1000],
            ]
        },
        'ETH/USDT': {
            'price': 2800.0,
            'volume': 500000,
            'ohlcv': []
        }
    }


def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "scenario: mark test as scenario test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
