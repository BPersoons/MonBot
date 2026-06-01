"""
Strategy Research: find a strategy that outperforms the current swarm 5x.
Tests 6 strategies on last 60 days of HL data across 8 liquid markets.

Run: python scripts/strategy_research.py
"""

import ccxt
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────── Config ───────────────────────────
TICKERS = [
    'BTC/USDC', 'ETH/USDC', 'SOL/USDC', 'HYPE/USDC',
    'XRP/USDC', 'NEAR/USDC', 'XLM/USDC', 'ZEC/USDC'
]
DAYS = 60
TIMEFRAME = '1h'
FEE_PCT = 0.0007      # 0.07% per side (HL taker)
SLIPPAGE_PCT = 0.0005 # 0.05% per side
COST_PCT = FEE_PCT + SLIPPAGE_PCT  # 0.12% per trade entry/exit
INITIAL_CAPITAL = 1000.0
SL_PCT = 0.035        # 3.5% stop-loss for all strategies

# ─────────────────────────── Data ─────────────────────────────
def fetch_data(exchange, ticker: str) -> pd.DataFrame:
    hl_ticker = f"{ticker}:USDC"
    since = exchange.milliseconds() - (DAYS * 24 * 60 * 60 * 1000)
    try:
        ohlcv = exchange.fetch_ohlcv(hl_ticker, timeframe=TIMEFRAME, since=since, limit=2000)
        if not ohlcv:
            return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except Exception as e:
        print(f"  [!] {ticker}: {e}")
        return pd.DataFrame()


# ─────────────────────────── Indicators ───────────────────────
def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df['close']
    v = df['volume']

    # RSI 14
    delta = c.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
    df['rsi'] = df['rsi'].fillna(50)

    # EMAs
    df['ema8']  = c.ewm(span=8, adjust=False).mean()
    df['ema20'] = c.ewm(span=20, adjust=False).mean()
    df['ema50'] = c.ewm(span=50, adjust=False).mean()
    df['ema200']= c.ewm(span=200, adjust=False).mean()

    # MACD 12/26/9
    exp12 = c.ewm(span=12, adjust=False).mean()
    exp26 = c.ewm(span=26, adjust=False).mean()
    df['macd'] = exp12 - exp26
    df['macd_sig'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']

    # Bollinger Bands 20/2
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    df['bb_upper'] = sma20 + 2 * std20
    df['bb_lower'] = sma20 - 2 * std20
    df['bb_mid'] = sma20
    df['bb_pct'] = (c - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # ATR 14
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # ADX 14
    plus_dm  = df['high'].diff().clip(lower=0)
    minus_dm = (-df['low'].diff()).clip(lower=0)
    plus_dm[plus_dm < minus_dm]  = 0
    minus_dm[minus_dm < plus_dm] = 0
    atr14 = df['atr']
    pdi = 100 * plus_dm.rolling(14).mean() / atr14.replace(0, np.nan)
    ndi = 100 * minus_dm.rolling(14).mean() / atr14.replace(0, np.nan)
    dx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    df['adx'] = dx.rolling(14).mean().fillna(0)
    df['plus_di'] = pdi.fillna(0)
    df['minus_di'] = ndi.fillna(0)

    # Supertrend 10/3
    hl2 = (df['high'] + df['low']) / 2
    upper_band = hl2 + 3 * df['atr']
    lower_band = hl2 - 3 * df['atr']
    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if pd.isna(upper_band.iloc[i]) or pd.isna(lower_band.iloc[i]):
            supertrend.iloc[i] = lower_band.iloc[i] if not pd.isna(lower_band.iloc[i]) else c.iloc[i]
            continue
        prev_sup = supertrend.iloc[i-1] if not pd.isna(supertrend.iloc[i-1]) else lower_band.iloc[i]
        prev_ub  = upper_band.iloc[i-1] if not pd.isna(upper_band.iloc[i-1]) else upper_band.iloc[i]
        prev_lb  = lower_band.iloc[i-1] if not pd.isna(lower_band.iloc[i-1]) else lower_band.iloc[i]
        upper_band.iloc[i] = min(upper_band.iloc[i], prev_ub) if c.iloc[i-1] <= prev_ub else upper_band.iloc[i]
        lower_band.iloc[i] = max(lower_band.iloc[i], prev_lb) if c.iloc[i-1] >= prev_lb else lower_band.iloc[i]
        if prev_sup == prev_ub:
            supertrend.iloc[i] = upper_band.iloc[i] if c.iloc[i] < upper_band.iloc[i] else lower_band.iloc[i]
            direction.iloc[i]  = -1 if c.iloc[i] < upper_band.iloc[i] else 1
        else:
            supertrend.iloc[i] = lower_band.iloc[i] if c.iloc[i] > lower_band.iloc[i] else upper_band.iloc[i]
            direction.iloc[i]  = 1 if c.iloc[i] > lower_band.iloc[i] else -1
    df['supertrend'] = supertrend
    df['st_dir'] = direction

    # Volume MA
    df['vol_ma20'] = v.rolling(20).mean()

    # Donchian Channel 20
    df['dc_high'] = df['high'].rolling(20).max()
    df['dc_low']  = df['low'].rolling(20).min()

    return df.dropna(subset=['ema200', 'adx']).copy()


# ─────────────────────────── Backtest Engine ──────────────────
def run_backtest(df: pd.DataFrame, signal_func, name: str) -> dict:
    """
    Signal func: returns +1 (long), -1 (short), 0 (no signal).
    Uses fixed-% SL; no TP (ride the trend with trailing stop via signal exit).
    """
    capital = INITIAL_CAPITAL
    position = 0.0       # units held
    entry_price = 0.0
    sl_price = 0.0
    direction = 0        # +1 long, -1 short
    trades = []

    for i in range(200, len(df)):  # skip warm-up
        row = df.iloc[i]
        price = row['close']
        high  = row['high']
        low   = row['low']

        # Check stop-loss first
        if direction == 1 and position > 0:
            if low <= sl_price:
                # Hit SL
                exit_p = sl_price
                pnl = (exit_p - entry_price) / entry_price * capital
                capital += pnl - abs(capital * COST_PCT)
                trades.append({'pnl_pct': (exit_p - entry_price) / entry_price, 'exit': 'sl'})
                position = 0; direction = 0

        elif direction == -1 and position > 0:
            if high >= sl_price:
                exit_p = sl_price
                pnl = (entry_price - exit_p) / entry_price * capital
                capital += pnl - abs(capital * COST_PCT)
                trades.append({'pnl_pct': (entry_price - exit_p) / entry_price, 'exit': 'sl'})
                position = 0; direction = 0

        # Get new signal
        sig = signal_func(df, i)

        # Exit on opposite signal
        if direction == 1 and position > 0 and sig < 0:
            pnl = (price - entry_price) / entry_price * capital
            capital += pnl - abs(capital * COST_PCT)
            trades.append({'pnl_pct': (price - entry_price) / entry_price, 'exit': 'sig'})
            position = 0; direction = 0

        elif direction == -1 and position > 0 and sig > 0:
            pnl = (entry_price - price) / entry_price * capital
            capital += pnl - abs(capital * COST_PCT)
            trades.append({'pnl_pct': (entry_price - price) / entry_price, 'exit': 'sig'})
            position = 0; direction = 0

        # Enter new position
        if direction == 0 and sig != 0:
            entry_price = price
            direction = int(sig)
            sl_price = price * (1 - SL_PCT) if sig > 0 else price * (1 + SL_PCT)
            capital -= capital * COST_PCT
            position = capital / price

    # Close at end
    if direction != 0 and position > 0:
        price = df.iloc[-1]['close']
        if direction == 1:
            pnl = (price - entry_price) / entry_price * capital
        else:
            pnl = (entry_price - price) / entry_price * capital
        capital += pnl - abs(capital * COST_PCT)
        trades.append({'pnl_pct': (price - entry_price) / entry_price * direction, 'exit': 'eod'})

    n = len(trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    gross_win  = sum(t['pnl_pct'] for t in wins)
    gross_loss = abs(sum(t['pnl_pct'] for t in losses))
    pf = gross_win / gross_loss if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)

    return {
        'strategy': name,
        'final': round(capital, 2),
        'pnl_pct': round((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100, 2),
        'trades': n,
        'win_rate': round(len(wins)/n, 3) if n > 0 else 0,
        'profit_factor': round(pf, 2),
        'avg_win_pct': round(sum(t['pnl_pct'] for t in wins) / len(wins) * 100, 2) if wins else 0,
        'avg_loss_pct': round(sum(t['pnl_pct'] for t in losses) / len(losses) * 100, 2) if losses else 0,
    }


# ─────────────────────────── Strategies ──────────────────────
# 1. CURRENT AGENT STRATEGY (baseline)
def sig_agent(df, i):
    row = df.iloc[i]
    price = row['close']
    rsi = row['rsi']
    ema20 = row['ema20']
    ema50 = row['ema50']
    signal = 0.0
    if rsi > 70: signal -= 0.4
    elif rsi > 60: signal += 0.2
    elif rsi < 30: signal += 0.4
    elif rsi < 40: signal -= 0.2
    if price > ema20 > ema50: signal += 0.5
    elif price > ema20: signal += 0.3
    elif price < ema20 < ema50: signal -= 0.5
    elif price < ema20: signal -= 0.3
    signal = max(-1.0, min(1.0, signal))
    return 1.0 if signal > 0.3 else (-1.0 if signal < -0.3 else 0.0)


# 2. SUPERTREND + ADX TREND STRENGTH
def sig_supertrend_adx(df, i):
    row = df.iloc[i]
    prev = df.iloc[i-1]
    if pd.isna(row['st_dir']) or row['adx'] < 20:
        return 0
    # Supertrend direction change = entry signal
    if prev['st_dir'] == -1 and row['st_dir'] == 1:
        return 1.0   # flip bullish
    if prev['st_dir'] == 1 and row['st_dir'] == -1:
        return -1.0  # flip bearish
    return 0


# 3. EMA RIBBON + RSI MOMENTUM (not reversion)
# Buy: price > ema8 > ema20 > ema50, RSI 50-70 (building momentum, not overbought)
# Sell: price < ema8 < ema20 < ema50, RSI 30-50
def sig_ema_ribbon(df, i):
    row = df.iloc[i]
    price = row['close']
    e8, e20, e50 = row['ema8'], row['ema20'], row['ema50']
    rsi = row['rsi']
    adx = row['adx']
    if adx < 15:  # skip choppy markets
        return 0
    # Long: full bull alignment + RSI in momentum zone
    if price > e8 > e20 > e50 and 50 <= rsi <= 72:
        return 1.0
    # Short: full bear alignment + RSI in momentum zone
    if price < e8 < e20 < e50 and 28 <= rsi <= 50:
        return -1.0
    return 0


# 4. MACD ZERO-CROSS + ADX FILTER
# Only trade MACD crossovers when ADX > 20 (trending market)
def sig_macd_adx(df, i):
    row = df.iloc[i]
    prev = df.iloc[i-1]
    adx = row['adx']
    if adx < 20:
        return 0
    # MACD crosses above zero = bull signal
    if prev['macd'] < 0 and row['macd'] >= 0 and row['plus_di'] > row['minus_di']:
        return 1.0
    # MACD crosses below zero = bear signal
    if prev['macd'] > 0 and row['macd'] <= 0 and row['minus_di'] > row['plus_di']:
        return -1.0
    return 0


# 5. DONCHIAN BREAKOUT + VOLUME CONFIRMATION
# Buy: price breaks above 20-period high on high volume
# Sell: price breaks below 20-period low on high volume
def sig_donchian_vol(df, i):
    row = df.iloc[i]
    prev = df.iloc[i-1]
    price = row['close']
    vol_spike = row['volume'] > row['vol_ma20'] * 1.5
    adx = row['adx']
    if adx < 18:
        return 0
    # Breakout: new 20-period high with volume
    if price > prev['dc_high'] and vol_spike:
        return 1.0
    # Breakdown: new 20-period low with volume
    if price < prev['dc_low'] and vol_spike:
        return -1.0
    return 0


# 6. BOLLINGER SQUEEZE + MOMENTUM (Keltner/Squeeze)
# Buy when BB contracts then price pops above upper BB with MACD positive
# Short when BB contracts then price drops below lower BB with MACD negative
def sig_bb_squeeze(df, i):
    row = df.iloc[i]
    prev = df.iloc[i-1]
    price = row['close']
    bb_width = (row['bb_upper'] - row['bb_lower']) / row['bb_mid']
    prev_bb_width = (prev['bb_upper'] - prev['bb_lower']) / prev['bb_mid']
    # Squeeze expanding (bands widen) = momentum entry
    squeeze_expanding = bb_width > prev_bb_width * 1.02
    if squeeze_expanding and row['macd'] > row['macd_sig'] and price > row['bb_mid']:
        return 1.0
    if squeeze_expanding and row['macd'] < row['macd_sig'] and price < row['bb_mid']:
        return -1.0
    return 0


# 7. TREND CONTINUATION: EMA200 + MACD HIST FLIP
# Long only above EMA200, enter when MACD histogram turns positive from negative
# Short only below EMA200, enter when MACD histogram turns negative from positive
def sig_trend_continuation(df, i):
    row = df.iloc[i]
    prev = df.iloc[i-1]
    price = row['close']
    above_200 = price > row['ema200']
    # Bull: above EMA200, MACD hist flips positive
    if above_200 and prev['macd_hist'] < 0 and row['macd_hist'] >= 0 and row['adx'] > 15:
        return 1.0
    # Bear: below EMA200, MACD hist flips negative
    if not above_200 and prev['macd_hist'] > 0 and row['macd_hist'] <= 0 and row['adx'] > 15:
        return -1.0
    return 0


STRATEGIES = [
    ('1_Agent_Baseline',        sig_agent),
    ('2_Supertrend_ADX',        sig_supertrend_adx),
    ('3_EMA_Ribbon',            sig_ema_ribbon),
    ('4_MACD_ADX',              sig_macd_adx),
    ('5_Donchian_Volume',       sig_donchian_vol),
    ('6_BB_Squeeze',            sig_bb_squeeze),
    ('7_Trend_Continuation',    sig_trend_continuation),
]


# ─────────────────────────── Main ────────────────────────────
def main():
    exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

    all_results = []  # (strategy_name, ticker, metrics)

    for ticker in TICKERS:
        print(f"\nFetching {ticker}...")
        df = fetch_data(exchange, ticker)
        if df.empty or len(df) < 250:
            print(f"  [skip] Not enough data ({len(df)} candles)")
            continue
        df = calc_indicators(df)
        print(f"  {len(df)} candles after warmup")

        ticker_row = []
        for name, func in STRATEGIES:
            result = run_backtest(df.copy(), func, name)
            result['ticker'] = ticker
            all_results.append(result)
            ticker_row.append(result)

        # Print per-ticker summary
        print(f"  {'Strategy':<30} {'PnL%':>7} {'Trades':>7} {'WR%':>6} {'PF':>6}")
        print(f"  {'-'*58}")
        for r in ticker_row:
            print(f"  {r['strategy']:<30} {r['pnl_pct']:>7.1f}% {r['trades']:>7} {r['win_rate']*100:>5.0f}% {r['profit_factor']:>6.2f}")

    # ── Aggregate across all tickers ──
    print("\n" + "="*70)
    print("AGGREGATE RESULTS (avg across all tickers)")
    print("="*70)

    strategy_names = [s[0] for s in STRATEGIES]
    agg = {}
    for name in strategy_names:
        rows = [r for r in all_results if r['strategy'] == name]
        if not rows:
            continue
        avg_pnl = sum(r['pnl_pct'] for r in rows) / len(rows)
        avg_wr   = sum(r['win_rate'] for r in rows) / len(rows)
        avg_pf   = sum(r['profit_factor'] for r in rows) / len(rows)
        total_trades = sum(r['trades'] for r in rows)
        agg[name] = {
            'avg_pnl_pct': avg_pnl,
            'avg_win_rate': avg_wr,
            'avg_pf': avg_pf,
            'total_trades': total_trades,
        }

    # Sort by avg PnL
    sorted_agg = sorted(agg.items(), key=lambda x: -x[1]['avg_pnl_pct'])

    baseline_pnl = agg.get('1_Agent_Baseline', {}).get('avg_pnl_pct', 0)

    print(f"\n{'Strategy':<30} {'AvgPnL%':>8} {'AvgWR%':>8} {'AvgPF':>7} {'Trades':>8} {'vs Baseline':>12}")
    print("-"*78)
    for name, m in sorted_agg:
        mult = m['avg_pnl_pct'] / baseline_pnl if baseline_pnl != 0 else float('inf')
        mult_str = f"{mult:.1f}x" if abs(mult) < 1000 else "inf"
        flag = " *** 5X TARGET" if m['avg_pnl_pct'] > 0 and (mult >= 5 or baseline_pnl <= 0) else ""
        print(f"{name:<30} {m['avg_pnl_pct']:>8.1f}% {m['avg_win_rate']*100:>7.0f}% {m['avg_pf']:>7.2f} {m['total_trades']:>8} {mult_str:>12}{flag}")

    print(f"\nBaseline (current agent): {baseline_pnl:.1f}% avg PnL over {DAYS}d")
    print(f"5x target: {baseline_pnl * 5:.1f}%")

    # ── Best strategy per-ticker breakdown ──
    best_name = sorted_agg[0][0] if sorted_agg else None
    if best_name:
        print(f"\n--- Best strategy breakdown: {best_name} ---")
        rows = [r for r in all_results if r['strategy'] == best_name]
        print(f"{'Ticker':<20} {'PnL%':>7} {'Trades':>7} {'WR%':>6} {'PF':>6} {'AvgW%':>8} {'AvgL%':>8}")
        print("-"*65)
        for r in sorted(rows, key=lambda x: -x['pnl_pct']):
            print(f"{r['ticker']:<20} {r['pnl_pct']:>7.1f}% {r['trades']:>7} {r['win_rate']*100:>5.0f}% {r['profit_factor']:>6.2f} {r['avg_win_pct']:>7.2f}% {r['avg_loss_pct']:>7.2f}%")


if __name__ == '__main__':
    main()
