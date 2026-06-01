"""
Dieper onderzoek: tech stock shorts.
- Per individuele ticker bekijken (INTC/NVDA vs AMD/MU)
- Extra short-strategieen testen (extremer overbought, regime-filter, divergence)
- Tighter SL varianten
"""
import ccxt, pandas as pd, numpy as np, warnings
warnings.filterwarnings('ignore')

TECH = {
    'weak':   ['XYZ-INTC/USDC','XYZ-NVDA/USDC','XYZ-TSLA/USDC'],
    'strong': ['XYZ-MU/USDC','XYZ-SNDK/USDC','XYZ-AMD/USDC'],
    'index':  ['XYZ-SP500/USDC','XYZ-XYZ100/USDC'],
}
ALL_TECH = [t for g in TECH.values() for t in g]

FEE_PCT = 0.0007; SLIPPAGE_PCT = 0.0005; COST_PCT = FEE_PCT + SLIPPAGE_PCT
INITIAL = 1000.0

exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

def fetch(ticker, days=62):
    hl = ticker.replace('/USDC', '/USDC:USDC')
    since = exchange.milliseconds() - (days * 24 * 60 * 60 * 1000)
    try:
        ohlcv = exchange.fetch_ohlcv(hl, timeframe='1h', since=since, limit=3000)
        if not ohlcv: return pd.DataFrame()
        df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
        df['ts'] = pd.to_datetime(df['ts'], unit='ms')
        return df.reset_index(drop=True)
    except: return pd.DataFrame()

def add_indicators(df):
    c = df['close']; v = df['volume']
    d = c.diff()
    g = d.where(d>0,0).rolling(14).mean(); l = (-d.where(d<0,0)).rolling(14).mean()
    df['rsi'] = (100-(100/(1+g/l.replace(0,np.nan)))).fillna(50)
    df['rsi_6']  = (100-(100/(1+(d.where(d>0,0).rolling(6).mean() / (-d.where(d<0,0)).rolling(6).mean().replace(0,np.nan))))).fillna(50)
    for span, col in [(8,'ema8'),(20,'ema20'),(50,'ema50'),(200,'ema200')]:
        df[col] = c.ewm(span=span, adjust=False).mean()
    df['macd'] = c.ewm(span=12,adjust=False).mean() - c.ewm(span=26,adjust=False).mean()
    df['macd_sig'] = df['macd'].ewm(span=9,adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    df['bb_upper'] = sma20 + 2*std20; df['bb_lower'] = sma20 - 2*std20
    df['bb_mid'] = sma20; df['bb_width'] = (df['bb_upper']-df['bb_lower'])/sma20
    hl = df['high']-df['low']
    hc = (df['high']-c.shift()).abs(); lc = (df['low']-c.shift()).abs()
    df['atr'] = pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(14).mean()
    pdm = df['high'].diff().clip(lower=0); ndm = (-df['low'].diff()).clip(lower=0)
    pdm[pdm<ndm]=0; ndm[ndm<pdm]=0
    pdi = 100*pdm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    ndi = 100*ndm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    dx = (100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)).fillna(0)
    df['adx'] = dx.rolling(14).mean().fillna(0)
    df['plus_di'] = pdi.fillna(0); df['minus_di'] = ndi.fillna(0)
    # Stochastic
    rsi_min = df['rsi'].rolling(14).min(); rsi_max = df['rsi'].rolling(14).max()
    df['stoch_k'] = ((df['rsi']-rsi_min)/(rsi_max-rsi_min).replace(0,np.nan)).fillna(0.5).rolling(3).mean()
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    # Bearish divergence helper: higher price, lower RSI over 10 bars
    df['rsi_10ago'] = df['rsi'].shift(10)
    df['close_10ago'] = c.shift(10)
    # Volume
    df['vol_ma20'] = v.rolling(20).mean()
    df['vol_ma5']  = v.rolling(5).mean()
    # Donchian
    df['dc_high'] = df['high'].rolling(20).max()
    df['dc_low']  = df['low'].rolling(20).min()
    # Supertrend
    hl2 = (df['high']+df['low'])/2
    ub = (hl2 + 3*df['atr']).copy(); lb = (hl2 - 3*df['atr']).copy()
    st_dir = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if pd.isna(ub.iloc[i]) or pd.isna(lb.iloc[i]): continue
        ub.iloc[i] = min(ub.iloc[i], ub.iloc[i-1]) if c.iloc[i-1] <= ub.iloc[i-1] else ub.iloc[i]
        lb.iloc[i] = max(lb.iloc[i], lb.iloc[i-1]) if c.iloc[i-1] >= lb.iloc[i-1] else lb.iloc[i]
        prev_ub = ub.iloc[i-1]; prev_lb = lb.iloc[i-1]
        prev_dir = st_dir.iloc[i-1]
        if prev_dir == -1:
            st_dir.iloc[i] = -1 if c.iloc[i] < ub.iloc[i] else 1
        else:
            st_dir.iloc[i] = 1 if c.iloc[i] > lb.iloc[i] else -1
    df['st_dir'] = st_dir
    return df.dropna(subset=['ema200','adx']).copy()

def backtest_short_only(df, sig_func, sl_pct=0.035):
    capital = INITIAL; position = 0.0; entry_price = 0.0
    sl_price = 0.0; in_trade = False; trades = []
    for i in range(50, len(df)):
        row = df.iloc[i]; price = row['close']
        hi = row['high']; lo = row['low']
        if in_trade and hi >= sl_price:
            r = (entry_price-sl_price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append({'r': r, 'exit': 'sl'}); in_trade = False
        sig = sig_func(df, i)
        if in_trade and sig > 0:   # exit signal
            r = (entry_price-price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append({'r': r, 'exit': 'sig'}); in_trade = False
        if not in_trade and sig < 0:
            entry_price = price; sl_price = price*(1+sl_pct)
            capital -= capital*COST_PCT; position = capital/price; in_trade = True
    if in_trade:
        price = df.iloc[-1]['close']
        r = (entry_price-price)/entry_price
        capital += r*capital - abs(capital*COST_PCT)
        trades.append({'r': r, 'exit': 'eod'})
    n = len(trades); wins=[t for t in trades if t['r']>0]; losses=[t for t in trades if t['r']<=0]
    gw=sum(t['r'] for t in wins); gl=abs(sum(t['r'] for t in losses))
    pf = gw/gl if gl>0 else (999.0 if gw>0 else 0.0)
    return {
        'pnl': (capital-INITIAL)/INITIAL*100, 'n': n,
        'wr': len(wins)/n if n>0 else 0, 'pf': pf,
        'avg_win': sum(t['r'] for t in wins)/len(wins)*100 if wins else 0,
        'avg_loss': sum(t['r'] for t in losses)/len(losses)*100 if losses else 0,
    }

# ── Short strategies to test ──────────────────────────────────────────

# 1. Extreme overbought (RSI > 78) + price fails to hold above EMA8
def S_extreme_rsi(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]
    if p['rsi']>=78 and r['rsi']<75 and r['close']<r['ema8']: return -1
    return 0

# 2. Bearish MACD divergence: price makes new 10-bar high, RSI does NOT confirm
def S_bearish_div(df, i):
    r=df.iloc[i]; price=r['close']
    if pd.isna(r['close_10ago']) or pd.isna(r['rsi_10ago']): return 0
    price_higher = price > r['close_10ago'] * 1.01
    rsi_lower    = r['rsi'] < r['rsi_10ago'] - 3
    below_ema20  = price < r['ema20']
    if price_higher and rsi_lower and below_ema20 and r['adx'] > 15: return -1
    return 0

# 3. Double top / failed breakout: price exceeds recent high then closes back below
def S_failed_breakout(df, i):
    if i < 5: return 0
    r=df.iloc[i]; price=r['close']
    recent_high = df['high'].iloc[i-5:i].max()
    prev_high_broken = df['high'].iloc[i] > recent_high  # this candle broke out
    # but close back below = failed breakout
    failed = price < recent_high * 0.995
    if prev_high_broken and failed and r['macd_hist'] < 0 and r['adx'] > 15: return -1
    return 0

# 4. Below EMA200 + MACD histogram flip negative (regime-gated)
def S_below_ema200_macd(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    if price < r['ema200'] and p['macd_hist']>0 and r['macd_hist']<=0 and r['adx']>15: return -1
    return 0

# 5. Supertrend flip + volume confirmation
def S_supertrend_vol(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]
    vol_ok = r['volume'] > r['vol_ma20'] * 1.2
    if p['st_dir']==1 and r['st_dir']==-1 and vol_ok: return -1
    return 0

# 6. Stochastic overbought rollover
def S_stoch_overbought(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]
    if p['stoch_k']>=0.80 and r['stoch_k']<p['stoch_k'] and r['stoch_k']<r['stoch_d']: return -1
    return 0

# 7. BB squeeze pop and fail: bands widen but price closes INSIDE band after pop
def S_bb_pop_fail(df, i):
    if i < 3: return 0
    r=df.iloc[i]; p=df.iloc[i-1]; pp=df.iloc[i-2]
    # bands were tight then expanded
    expanding = r['bb_width'] > pp['bb_width'] * 1.05
    # prev candle popped above upper band, this candle closes back below mid
    popped_then_failed = p['close'] > p['bb_upper'] and r['close'] < r['bb_mid']
    if expanding and popped_then_failed and r['macd_hist'] < 0: return -1
    return 0

# 8. High-vol gap rejection (price gaps up > 1.5% then closes near open)
def S_gap_rejection(df, i):
    if i < 1: return 0
    r=df.iloc[i]; p=df.iloc[i-1]
    gap_up = r['open'] > p['close'] * 1.015
    rejection = r['close'] < r['open'] * 0.998   # closes below open (bearish candle)
    if gap_up and rejection and r['rsi'] > 60: return -1
    return 0

SHORT_CANDIDATES = [
    ('S_extreme_rsi',      S_extreme_rsi),
    ('S_bearish_div',      S_bearish_div),
    ('S_failed_breakout',  S_failed_breakout),
    ('S_below_ema200_macd',S_below_ema200_macd),
    ('S_supertrend_vol',   S_supertrend_vol),
    ('S_stoch_overbought', S_stoch_overbought),
    ('S_bb_pop_fail',      S_bb_pop_fail),
    ('S_gap_rejection',    S_gap_rejection),
]

# ── Main ──────────────────────────────────────────────────────────────
print('Fetching tech data...')
raw_data = {}
for t in ALL_TECH:
    df = fetch(t, 62)
    if not df.empty and len(df) > 100:
        raw_data[t] = add_indicators(df)
print(f'Ready: {len(raw_data)} tickers\n')

for window_days, label in [(60,'60d'), (30,'30d'), (7,'7d')]:
    cutoff = window_days*24 + 50
    print(f'\n{"="*72}')
    print(f'TECH STOCKS SHORT STRATEGIES -- {label}')
    print('='*72)

    for group_name, tickers in TECH.items():
        valid = [t for t in tickers if t in raw_data]
        if not valid: continue
        print(f'\n  [{group_name.upper()}: {", ".join(t.split("-")[1].split("/")[0] for t in valid)}]')
        print(f'  {"Strategy":<24} {"AvgPnL%":>8} {"WR%":>7} {"PF":>7} {"N":>5} {"AvgW%":>8} {"AvgL%":>8}')
        print(f'  {"-"*68}')

        results = []
        for name, func in SHORT_CANDIDATES:
            pnls=[]; wrs=[]; pfs=[]; ns=[]; aws=[]; als=[]
            for t in valid:
                if t not in raw_data: continue
                df = raw_data[t].tail(cutoff).reset_index(drop=True)
                if len(df) < 80: continue
                r = backtest_short_only(df, func, sl_pct=0.035)
                if r['n'] > 0:
                    pnls.append(r['pnl']); wrs.append(r['wr']); pfs.append(r['pf'])
                    ns.append(r['n']); aws.append(r['avg_win']); als.append(r['avg_loss'])
            if not pnls: continue
            avg_pnl = sum(pnls)/len(pnls)
            results.append((name, avg_pnl, sum(wrs)/len(wrs), sum(pfs)/len(pfs),
                           sum(ns), sum(aws)/len(aws) if aws else 0, sum(als)/len(als) if als else 0))

        results.sort(key=lambda x: -x[1])
        for name, pnl, wr, pf, n, aw, al in results:
            flag = '  <<<' if pnl > 0 else ''
            print(f'  {name:<24} {pnl:>8.1f}% {wr*100:>6.0f}% {pf:>7.2f} {n:>5} {aw:>8.2f}% {al:>8.2f}%{flag}')

    # Best short per group across windows
    print(f'\n  BEST SHORT per ticker ({label}):')
    for t in ALL_TECH:
        if t not in raw_data: continue
        df = raw_data[t].tail(cutoff).reset_index(drop=True)
        if len(df) < 80: continue
        best = None; best_pnl = -999
        for name, func in SHORT_CANDIDATES:
            r = backtest_short_only(df, func, sl_pct=0.035)
            if r['n'] > 0 and r['pnl'] > best_pnl:
                best = (name, r['pnl'], r['wr'], r['pf'], r['n'])
                best_pnl = r['pnl']
        if best:
            ticker_short = t.split('-')[1].split('/')[0]
            flag = '  +' if best[1] > 0 else ''
            print(f'  {ticker_short:<8} {best[0]:<24} pnl={best[1]:>7.1f}%  WR={best[2]*100:.0f}%  PF={best[3]:.2f}  n={best[4]}{flag}')
