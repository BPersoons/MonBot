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

# Geen echte Telegram-meldingen vanuit toetsen — zie tests/telegram_blokkade.py.
# Bewust bij het laden van conftest, dus vóór enige toetsmodule een agent importeert.
from tests.telegram_blokkade import installeer as _blokkeer_telegram  # noqa: E402

_blokkeer_telegram()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Maak zichtbaar hoeveel meldingen er anders naar Bart waren gegaan."""
    from tests.telegram_blokkade import ONDERSCHEPT
    if ONDERSCHEPT:
        terminalreporter.write_line(
            # Bewust alleen ASCII: predeploy.py leest deze uitvoer via een pijp, en een
            # gedachtestreepje liet de hele poort crashen op cp1252 (2026-09-17).
            f"Telegram: {len(ONDERSCHEPT)} melding(en) onderschept - niets naar Bart verstuurd"
        )


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
