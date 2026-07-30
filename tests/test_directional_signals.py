"""G3a — verify core/directional_signals.py is a faithful port of the proven
strategy_final.py signal functions, and that routing works.

The equivalence test is the important one: it runs BOTH the ported functions and
the originals over an identical synthetic OHLCV frame and asserts they return the
same direction on every candle. If the port ever drifts, this fails.
"""

import importlib

import numpy as np
import pandas as pd
import pytest

from core import directional_signals as ds


def _synthetic_ohlcv(n=600, seed=7):
    """Random-walk OHLCV with enough structure to trigger every signal branch."""
    rng = np.random.default_rng(seed)
    # trend + noise + regime shifts so we hit bull, bear and chop
    steps = rng.normal(0, 1, n)
    steps[:200] += 0.6      # uptrend
    steps[200:400] -= 0.7   # downtrend
    # steps[400:] ~ flat/chop
    close = 100 + np.cumsum(steps)
    close = np.maximum(close, 1.0)
    high = close + np.abs(rng.normal(0, 0.8, n))
    low = close - np.abs(rng.normal(0, 0.8, n))
    open_ = close + rng.normal(0, 0.3, n)
    vol = np.abs(rng.normal(1000, 200, n))
    ts = np.arange(n) * 3600_000
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


@pytest.fixture(scope="module")
def prepared():
    raw = _synthetic_ohlcv()
    df = ds.add_directional_indicators(raw).reset_index(drop=True)
    assert len(df) > 100, "not enough rows after indicator warmup"
    return df


@pytest.fixture(scope="module")
def original_funcs():
    """Import the originals from strategy_final without running main()."""
    sf = importlib.import_module("scripts.strategy_final")
    return sf.signal_crypto, sf.signal_tech, sf.signal_commodities


def test_required_columns_present(prepared):
    for col in ds.REQUIRED_COLUMNS:
        assert col in prepared.columns, f"missing indicator column {col}"


@pytest.mark.parametrize("ported_name,orig_idx", [
    ("signal_crypto", 0), ("signal_tech", 1), ("signal_commodities", 2)])
def test_port_matches_original(prepared, original_funcs, ported_name, orig_idx):
    ported = getattr(ds, ported_name)
    orig = original_funcs[orig_idx]
    mismatches = []
    for i in range(1, len(prepared)):
        a = ported(prepared, i)
        b = orig(prepared, i)
        if a != b:
            mismatches.append((i, a, b))
    assert not mismatches, f"{ported_name} diverged from original at {mismatches[:5]}"


def test_signals_return_valid_directions(prepared):
    for i in range(1, len(prepared)):
        for fn in (ds.signal_crypto, ds.signal_tech, ds.signal_commodities):
            assert fn(prepared, i) in (-1, 0, 1)


def test_branches_fire_crypto_commodities(prepared):
    """Sanity: crypto & commodities (trend both ways) produce LONG and SHORT on the
    fixture, so the equivalence test is exercising real branches, not just zeros."""
    for fn in (ds.signal_crypto, ds.signal_commodities):
        outs = {fn(prepared, i) for i in range(1, len(prepared))}
        assert 1 in outs, f"{fn.__name__} never produced a LONG on the fixture"
        assert -1 in outs, f"{fn.__name__} never produced a SHORT on the fixture"


def test_tech_short_branch_targeted():
    """Tech shorts need a specific bearish-divergence-below-EMA200 case the random
    fixture rarely hits — craft it directly and confirm signal_tech returns -1."""
    # 11 rows; at i=10: price below EMA200, higher than 10 bars ago, but lower RSI.
    n = 11
    df = pd.DataFrame({
        "close":       [100.0] * n,
        "ema200":      [120.0] * n,   # price < EMA200 → bear regime
        "adx":         [25.0] * n,
        "st_dir":      [-1] * n,       # no bullish flip (LONG1 blocked)
        "macd_hist":   [-1.0] * n,     # r.macd_hist<0 with above_200 False (LONG2 blocked)
        "close_10ago": [98.0] * n,     # 100 > 98*1.01 = 98.98 ✓
        "rsi":         [40.0] * n,
        "rsi_10ago":   [50.0] * n,     # 40 < 50-3 ✓
    })
    assert ds.signal_tech(df, 10) == -1
    assert ds.get_signal_for_asset("tech_stock", df, 10) == -1


def test_router_dispatches_by_class(prepared):
    i = len(prepared) - 1
    assert ds.get_signal_for_asset("crypto", prepared, i) == ds.signal_crypto(prepared, i)
    assert ds.get_signal_for_asset("tech_stock", prepared, i) == ds.signal_tech(prepared, i)
    assert ds.get_signal_for_asset("commodity", prepared, i) == ds.signal_commodities(prepared, i)
    # unknown class falls back to crypto
    assert ds.get_signal_for_asset("mystery", prepared, i) == ds.signal_crypto(prepared, i)


def test_signal_for_ticker_routes_via_detect(prepared):
    i = len(prepared) - 1
    assert ds.signal_for_ticker("BTC/USDC", prepared, i) == ds.signal_crypto(prepared, i)
    assert ds.signal_for_ticker("XYZ-AMD/USDC", prepared, i) == ds.signal_tech(prepared, i)
    assert ds.signal_for_ticker("XYZ-GOLD/USDC", prepared, i) == ds.signal_commodities(prepared, i)
