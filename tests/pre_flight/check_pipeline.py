"""
Pre-flight API contract validator.

Validates that cross-agent method signatures are compatible with how callers invoke them.
Uses inspect.signature() — no network calls, no side effects, runs in <1s.

Catches signature mismatches (e.g. missing/renamed parameters) before deployment.

Usage:
    python -m tests.pre_flight.check_pipeline
"""

import inspect
import logging
import sys
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("PreFlight-Pipeline")

# ── Contract definitions ─────────────────────────────────────────────────────
# Each entry: caller (description), callee (class, method name), required_params
# (list of param names the caller passes — all must exist in the callee signature).

def _build_contracts():
    """Import agent classes and return the CONTRACT list.  Deferred so import
    errors surface as individual failures rather than crashing the whole check."""
    from agents.technical_analyst import TechnicalAnalyst
    from agents.fundamental_analyst import FundamentalAnalyst
    from agents.sentiment_analyst import SentimentAnalyst

    return [
        {
            "caller": "project_lead.py (TA call with direction)",
            "callee_class": TechnicalAnalyst,
            "method": "analyze_async",
            "required_params": ["ticker", "catalyst", "direction"],
        },
        {
            "caller": "project_lead.py (FundamentalAnalyst call)",
            "callee_class": FundamentalAnalyst,
            "method": "analyze_async",
            "required_params": ["ticker"],
        },
        {
            "caller": "project_lead.py (SentimentAnalyst call)",
            "callee_class": SentimentAnalyst,
            "method": "analyze_async",
            "required_params": ["ticker"],
        },
    ]


def run_contract_checks() -> bool:
    """Run all contract checks. Returns True if all pass."""
    try:
        contracts = _build_contracts()
    except ImportError as e:
        logger.error(f"Failed to import agent classes: {e}")
        logger.error("Run check_imports first to diagnose import errors.")
        return False

    failures = 0

    for c in contracts:
        cls = c["callee_class"]
        method_name = c["method"]
        required = c["required_params"]
        caller = c["caller"]

        # Get the method
        method = getattr(cls, method_name, None)
        if method is None:
            logger.error(
                f"CONTRACT FAIL: {cls.__name__}.{method_name} does not exist\n"
                f"  Caller: {caller}\n"
                f"  Expected method: {method_name}"
            )
            failures += 1
            continue

        # Inspect signature
        try:
            sig = inspect.signature(method)
        except (ValueError, TypeError) as e:
            logger.error(f"CONTRACT FAIL: cannot inspect {cls.__name__}.{method_name}: {e}")
            failures += 1
            continue

        params = set(sig.parameters.keys()) - {"self"}

        # Check each required param is present (positional or keyword)
        missing = [p for p in required if p not in params]
        if missing:
            logger.error(
                f"CONTRACT FAIL: {cls.__name__}.{method_name} is missing required parameter(s): {missing}\n"
                f"  Caller: {caller}\n"
                f"  Required: {required}\n"
                f"  Actual:   {sorted(params)}"
            )
            failures += 1
        else:
            logger.info(f"  OK  {cls.__name__}.{method_name}({', '.join(required)}) — called by {caller}")

    return failures == 0


def _check_backtester_signal_frequency() -> bool:
    """
    Smoke-test: verify the AutoBacktester generates enough signals for the
    ResearchAgent pre-screen to surface candidates.

    The ResearchAgent requires pnl > 0 AND trades >= 2 AND rr_after_costs >= 1.0
    over a 7-day window. If the backtester returns 0 trades for major tickers,
    no candidates will be surfaced and the swarm will silently stop trading.

    Uses synthetic OHLCV data (no live API call) to avoid network dependency in CI.
    The test verifies signal COUNT only — not profitability — since market conditions
    determine profitability but signal frequency is a property of the strategy logic.
    """
    import pandas as pd
    import numpy as np
    from core.strategy_logic import StrategyLogic

    # Generate 200 hours of synthetic trending price data
    # (enough warmup for all indicators including EMA200 via ewm)
    np.random.seed(42)
    n = 250
    price = 50000.0
    prices = [price]
    for _ in range(n - 1):
        price *= (1 + np.random.normal(0.0002, 0.012))
        prices.append(price)

    df = pd.DataFrame({
        'open':   prices,
        'high':   [p * 1.005 for p in prices],
        'low':    [p * 0.995 for p in prices],
        'close':  prices,
        'volume': [1_000_000 * (1 + abs(np.random.normal(0, 0.5))) for _ in prices],
    })

    # Test the legacy agent signal (used by backtester for pre-screen)
    indicators = StrategyLogic.calculate_indicators(df['close'].tolist())
    signal_count = 0
    for i in range(50, len(df)):
        price_i = df['close'].iloc[i]
        current = {k: v.iloc[i] for k, v in indicators.items()}
        s, _ = StrategyLogic.get_agent_signal(price_i, current)
        if abs(s) > 0.3:
            signal_count += 1

    min_signals = 3  # expect at least 3 signals in 200 candles (~8 days)
    if signal_count < min_signals:
        logger.error(
            f"  FAIL  AutoBacktester agent signal: only {signal_count} signals in {n} candles "
            f"(need >= {min_signals}). ResearchAgent will surface 0 candidates."
        )
        return False

    logger.info(f"  OK  AutoBacktester agent signal: {signal_count} signals in {n} candles (>= {min_signals})")
    return True


if __name__ == "__main__":
    project_root = os.getcwd()
    sys.path.insert(0, project_root)
    logger.info(f"Project root: {project_root}")

    all_ok = True

    logger.info("Checking cross-agent API contracts...")
    if not run_contract_checks():
        all_ok = False
    else:
        logger.info("SUCCESS: All API contracts valid.")

    logger.info("Checking treasury system contracts...")
    try:
        from tests.pre_flight.check_treasury import run_all_checks as run_treasury_checks
        if not run_treasury_checks():
            all_ok = False
        else:
            logger.info("SUCCESS: Treasury system valid.")
    except Exception as e:
        logger.error(f"Treasury check crashed: {e}")
        all_ok = False

    logger.info("Checking backtester signal frequency (ResearchAgent pre-screen smoke test)...")
    try:
        _bt_ok = _check_backtester_signal_frequency()
        if not _bt_ok:
            all_ok = False
    except Exception as e:
        logger.error(f"Backtester smoke test crashed: {e}")
        all_ok = False

    if all_ok:
        logger.info("PRE-FLIGHT PIPELINE CONTRACT CHECK PASSED")
        sys.exit(0)
    else:
        logger.error("FAILED: One or more checks failed. Fix before deploying.")
        sys.exit(1)
