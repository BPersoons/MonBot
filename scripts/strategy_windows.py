"""Run 30d and 7d backtests for top 3 strategies."""
import ccxt, pandas as pd, numpy as np, warnings
warnings.filterwarnings('ignore')

TICKERS = ['BTC/USDC','ETH/USDC','SOL/USDC','HYPE/USDC','XRP/USDC','NEAR/USDC','XLM/USDC','ZEC/USDC']
FEE_PCT = 0.0007; SLIPPAGE_PCT = 0.0005; COST_PCT = FEE_PCT + SLIPPAGE_PCT
INITIAL = 1000.0; SL_PCT = 0.035

exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def fetch(ticker, days):
    hl = f'{ticker}:USDC'
    since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
    try:
        ohlcv = exchange.fetch_ohlcv(hl, timeframe='1h', since=since, limit=3000)
        if not ohlcv:
            return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except Exception as e:
        print(f'  [skip] {ticker}: {e}')
        return pd.DataFrame()

def add_indicators(df):
    c = df['close']
    delta = c.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).fillna(50)
    df['ema8']   = c.ewm(span=8,  adjust=False).mean()
    df['ema20']  = c.ewm(span=20, adjust=False).mean()
    df['ema50']  = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200,adjust=False).mean()
    exp12 = c.ewm(span=12, adjust=False).mean()
    exp26 = c.ewm(span=26, adjust=False).mean()
    df['macd']      = exp12 - exp26
    df['macd_sig']  = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    hl = df['high'] - df['low']
    hc = (df['high'] - df['close'].shift()).abs()
    lc = (df['low']  - df['close'].shift()).abs()
    df['atr'] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()
    pdm = df['high'].diff().clip(lower=0)
    ndm = (-df['low'].diff()).clip(lower=0)
    pdm[pdm < ndm] = 0; ndm[ndm < pdm] = 0
    pdi = 100 * pdm.rolling(14).mean() / df['atr'].replace(0, np.nan)
    ndi = 100 * ndm.rolling(14).mean() / df['atr'].replace(0, np.nan)
    dx  = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    df['adx']      = dx.rolling(14).mean().fillna(0)
    df['plus_di']  = pdi.fillna(0)
    df['minus_di'] = ndi.fillna(0)
    return df.dropna(subset=['ema200', 'adx']).copy()

def backtest(df, sig_func):
    capital = INITIAL; position = 0.0; entry_price = 0.0
    sl_price = 0.0; direction = 0; trades = []
    for i in range(50, len(df)):
        row = df.iloc[i]; price = row['close']
        hi = row['high']; lo = row['low']
        # stop-loss check
        if direction == 1 and position > 0 and lo <= sl_price:
            pnl_r = (sl_price - entry_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            trades.append(pnl_r); position = 0; direction = 0
        elif direction == -1 and position > 0 and hi >= sl_price:
            pnl_r = (entry_price - sl_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            trades.append(pnl_r); position = 0; direction = 0
        sig = sig_func(df, i)
        # signal exit
        if direction == 1 and position > 0 and sig < 0:
            pnl_r = (price - entry_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            trades.append(pnl_r); position = 0; direction = 0
        elif direction == -1 and position > 0 and sig > 0:
            pnl_r = (entry_price - price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            trades.append(pnl_r); position = 0; direction = 0
        # entry
        if direction == 0 and sig != 0:
            entry_price = price; direction = int(sig)
            sl_price = price * (1 - SL_PCT) if sig > 0 else price * (1 + SL_PCT)
            capital -= capital * COST_PCT; position = capital / price
    # close at end
    if direction != 0 and position > 0:
        price = df.iloc[-1]['close']
        pnl_r = (price - entry_price)/entry_price if direction == 1 else (entry_price - price)/entry_price
        capital += pnl_r * capital - abs(capital * COST_PCT)
        trades.append(pnl_r)
    n = len(trades)
    wins   = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    gw = sum(wins); gl = abs(sum(losses))
    pf = gw/gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    return {'pnl': (capital - INITIAL) / INITIAL * 100, 'n': n,
            'wr': len(wins)/n if n > 0 else 0, 'pf': pf}

# ---- signal functions ----
def sig_agent(df, i):
    r = df.iloc[i]; p = r['close']; rsi = r['rsi']; e20 = r['ema20']; e50 = r['ema50']
    s = 0.0
    if rsi > 70:   s -= 0.4
    elif rsi > 60: s += 0.2
    elif rsi < 30: s += 0.4
    elif rsi < 40: s -= 0.2
    if   p > e20 > e50: s += 0.5
    elif p > e20:       s += 0.3
    elif p < e20 < e50: s -= 0.5
    elif p < e20:       s -= 0.3
    s = max(-1, min(1, s))
    return 1.0 if s > 0.3 else (-1.0 if s < -0.3 else 0)

def sig_macd_adx(df, i):
    r = df.iloc[i]; prev = df.iloc[i-1]
    if r['adx'] < 20: return 0
    if prev['macd'] < 0 and r['macd'] >= 0 and r['plus_di'] > r['minus_di']:  return  1.0
    if prev['macd'] > 0 and r['macd'] <= 0 and r['minus_di'] > r['plus_di']:  return -1.0
    return 0

def sig_trend_cont(df, i):
    r = df.iloc[i]; prev = df.iloc[i-1]; price = r['close']
    above = price > r['ema200']
    if above and prev['macd_hist'] < 0 and r['macd_hist'] >= 0 and r['adx'] > 15:     return  1.0
    if not above and prev['macd_hist'] > 0 and r['macd_hist'] <= 0 and r['adx'] > 15: return -1.0
    return 0

STRATEGIES = [
    ('Agent_Baseline',     sig_agent),
    ('MACD_ADX',           sig_macd_adx),
    ('Trend_Continuation', sig_trend_cont),
]

# ---- main ----
print('Fetching 62 days of data...')
raw_data = {}
for t in TICKERS:
    df = fetch(t, 62)
    if not df.empty and len(df) > 100:
        raw_data[t] = add_indicators(df)
print(f'Ready: {len(raw_data)} tickers')

for window_days, label in [(30, '30 DAYS'), (7, '7 DAYS')]:
    cutoff = window_days * 24 + 50  # candles to slice (1h)
    print(f'\n{"="*68}')
    print(f'LAST {label}')
    print('='*68)

    summary = []
    for strat_name, sig_func in STRATEGIES:
        pnls=[]; wrs=[]; pfs=[]; ns=[]
        for ticker, df_full in raw_data.items():
            df = df_full.tail(cutoff).reset_index(drop=True)
            if len(df) < 80:
                continue
            r = backtest(df, sig_func)
            pnls.append(r['pnl']); wrs.append(r['wr']); pfs.append(r['pf']); ns.append(r['n'])
        if not pnls:
            continue
        summary.append((strat_name,
                        sum(pnls)/len(pnls),
                        sum(wrs)/len(wrs),
                        sum(pfs)/len(pfs),
                        sum(ns)))

    baseline_pnl = next((x[1] for x in summary if x[0] == 'Agent_Baseline'), 0)
    summary_sorted = sorted(summary, key=lambda x: -x[1])

    print(f'  {"Strategy":<25} {"AvgPnL%":>8} {"AvgWR%":>8} {"AvgPF":>7} {"Trades":>7}  vs Baseline')
    print(f'  {"-"*72}')
    for name, pnl, wr, pf, nt in summary_sorted:
        delta = pnl - baseline_pnl
        flag  = '  <<<' if name != 'Agent_Baseline' and delta > 0 else ''
        print(f'  {name:<25} {pnl:>8.1f}% {wr*100:>7.0f}% {pf:>7.2f} {nt:>7}  {delta:+.1f}pp{flag}')

    # Per-ticker for best
    best_name = summary_sorted[0][0]
    best_func = next(f for n, f in STRATEGIES if n == best_name)
    print(f'\n  Per-ticker [{best_name}]:')
    print(f'  {"Ticker":<18} {"PnL%":>7} {"Trades":>7} {"WR%":>6} {"PF":>6}')
    print(f'  {"-"*50}')
    per_t = []
    for ticker, df_full in raw_data.items():
        df = df_full.tail(cutoff).reset_index(drop=True)
        if len(df) < 80:
            continue
        r = backtest(df, best_func)
        per_t.append((ticker, r['pnl'], r['n'], r['wr'], r['pf']))
    for t, pnl, n, wr, pf in sorted(per_t, key=lambda x: -x[1]):
        print(f'  {t:<18} {pnl:>7.1f}%  {n:>3}     {wr*100:>4.0f}%  {pf:>6.2f}')
