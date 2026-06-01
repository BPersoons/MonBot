"""
Split backtest: long trades vs short trades afzonderlijk.
Zodat we weten of het rendement uit longs, shorts, of beide komt.
"""
import ccxt, pandas as pd, numpy as np, warnings
warnings.filterwarnings('ignore')

CRYPTO   = ['BTC/USDC','ETH/USDC','SOL/USDC','HYPE/USDC','XRP/USDC','NEAR/USDC','XLM/USDC','ZEC/USDC']
STOCKS   = ['XYZ-MU/USDC','XYZ-SNDK/USDC','XYZ-AMD/USDC','XYZ-INTC/USDC',
            'XYZ-SP500/USDC','XYZ-XYZ100/USDC']
COMMODITIES = ['XYZ-CL/USDC','XYZ-BRENTOIL/USDC','XYZ-GOLD/USDC','XYZ-SILVER/USDC']

FEE_PCT = 0.0007; SLIPPAGE_PCT = 0.0005; COST_PCT = FEE_PCT + SLIPPAGE_PCT
INITIAL = 1000.0; SL_PCT = 0.035

exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def fetch(ticker, days):
    hl = ticker.replace('/USDC', '/USDC:USDC') if ':USDC' not in ticker else ticker
    since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
    try:
        ohlcv = exchange.fetch_ohlcv(hl, timeframe='1h', since=since, limit=3000)
        if not ohlcv: return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except: return pd.DataFrame()

def add_indicators(df):
    c = df['close']
    delta = c.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).fillna(50)
    df['ema20']  = c.ewm(span=20, adjust=False).mean()
    df['ema50']  = c.ewm(span=50, adjust=False).mean()
    df['ema200'] = c.ewm(span=200, adjust=False).mean()
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

def backtest_split(df, sig_func):
    """Returns separate stats for long and short trades."""
    capital = INITIAL; position = 0.0; entry_price = 0.0
    sl_price = 0.0; direction = 0
    long_trades = []; short_trades = []

    for i in range(50, len(df)):
        row = df.iloc[i]; price = row['close']
        hi = row['high']; lo = row['low']

        if direction == 1 and position > 0 and lo <= sl_price:
            pnl_r = (sl_price - entry_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            long_trades.append(pnl_r); position = 0; direction = 0

        elif direction == -1 and position > 0 and hi >= sl_price:
            pnl_r = (entry_price - sl_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            short_trades.append(pnl_r); position = 0; direction = 0

        sig = sig_func(df, i)

        if direction == 1 and position > 0 and sig < 0:
            pnl_r = (price - entry_price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            long_trades.append(pnl_r); position = 0; direction = 0

        elif direction == -1 and position > 0 and sig > 0:
            pnl_r = (entry_price - price) / entry_price
            capital += pnl_r * capital - abs(capital * COST_PCT)
            short_trades.append(pnl_r); position = 0; direction = 0

        if direction == 0 and sig != 0:
            entry_price = price; direction = int(sig)
            sl_price = price * (1 - SL_PCT) if sig > 0 else price * (1 + SL_PCT)
            capital -= capital * COST_PCT; position = capital / price

    if direction != 0 and position > 0:
        price = df.iloc[-1]['close']
        pnl_r = (price - entry_price)/entry_price if direction == 1 else (entry_price - price)/entry_price
        capital += pnl_r * capital - abs(capital * COST_PCT)
        if direction == 1: long_trades.append(pnl_r)
        else:              short_trades.append(pnl_r)

    def metrics(trades):
        if not trades: return {'n': 0, 'wr': 0, 'pf': 0, 'avg_pnl': 0}
        wins   = [t for t in trades if t > 0]
        losses = [t for t in trades if t <= 0]
        gw = sum(wins); gl = abs(sum(losses))
        pf = gw/gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        return {'n': len(trades), 'wr': len(wins)/len(trades),
                'pf': pf, 'avg_pnl': sum(trades)/len(trades)*100}

    return metrics(long_trades), metrics(short_trades)

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

STRATEGIES = [('MACD_ADX', sig_macd_adx), ('Trend_Continuation', sig_trend_cont)]

GROUPS = {
    'Crypto':       CRYPTO,
    'Tech Stocks':  STOCKS,
    'Commodities':  COMMODITIES,
}

# fetch
print('Fetching 60d data...')
raw_data = {}
for tlist in GROUPS.values():
    for t in tlist:
        if t not in raw_data:
            df = fetch(t, 62)
            if not df.empty and len(df) > 100:
                raw_data[t] = add_indicators(df)

cutoff = 60 * 24 + 50  # 60 dagen

for group_name, tickers in GROUPS.items():
    group_data = {t: raw_data[t] for t in tickers if t in raw_data}
    if not group_data: continue

    print(f'\n{"="*70}')
    print(f'{group_name.upper()} -- 60d -- Long vs Short split')
    print('='*70)

    for strat_name, sig_func in STRATEGIES:
        L_ns=[]; L_wrs=[]; L_pfs=[]; L_pnls=[]
        S_ns=[]; S_wrs=[]; S_pfs=[]; S_pnls=[]

        for ticker, df_full in group_data.items():
            df = df_full.tail(cutoff).reset_index(drop=True)
            if len(df) < 80: continue
            lm, sm = backtest_split(df, sig_func)
            if lm['n'] > 0:
                L_ns.append(lm['n']); L_wrs.append(lm['wr'])
                L_pfs.append(lm['pf']); L_pnls.append(lm['avg_pnl'])
            if sm['n'] > 0:
                S_ns.append(sm['n']); S_wrs.append(sm['wr'])
                S_pfs.append(sm['pf']); S_pnls.append(sm['avg_pnl'])

        def agg(vals): return sum(vals)/len(vals) if vals else 0
        print(f'\n  [{strat_name}]')
        print(f'  {"Direction":<10} {"AvgPnL/trade":>13} {"WR%":>7} {"AvgPF":>7} {"N trades":>10}')
        print(f'  {"-"*52}')
        print(f'  {"LONG":<10} {agg(L_pnls):>12.2f}%  {agg(L_wrs)*100:>6.0f}%  {agg(L_pfs):>6.2f}  {sum(L_ns):>8}')
        print(f'  {"SHORT":<10} {agg(S_pnls):>12.2f}%  {agg(S_wrs)*100:>6.0f}%  {agg(S_pfs):>6.2f}  {sum(S_ns):>8}')
        long_better  = agg(L_pnls) > agg(S_pnls)
        short_better = agg(S_pnls) > agg(L_pnls)
        note = "  -> Longs winnen" if long_better else ("  -> Shorts winnen" if short_better else "  -> Gelijk")
        l_pos = agg(L_pnls) > 0; s_pos = agg(S_pnls) > 0
        both  = "(beide winstgevend)" if l_pos and s_pos else ("(alleen longs)" if l_pos else ("(alleen shorts)" if s_pos else "(beide verlies)"))
        print(f'  {note} {both}')
