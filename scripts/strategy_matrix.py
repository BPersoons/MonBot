"""
Full strategy matrix:
- 5 long candidates + 6 short candidates
- Tested separately per direction, per asset class
- Best long + best short combined into hybrid
- Compared against previous best (MACD_ADX combined)

Run: python scripts/strategy_matrix.py
"""
import ccxt, pandas as pd, numpy as np, warnings
warnings.filterwarnings('ignore')

GROUPS = {
    'Crypto':      ['BTC/USDC','ETH/USDC','SOL/USDC','HYPE/USDC',
                    'XRP/USDC','NEAR/USDC','XLM/USDC','ZEC/USDC'],
    'TechStocks':  ['XYZ-MU/USDC','XYZ-SNDK/USDC','XYZ-AMD/USDC',
                    'XYZ-INTC/USDC','XYZ-SP500/USDC','XYZ-XYZ100/USDC'],
    'Commodities': ['XYZ-CL/USDC','XYZ-BRENTOIL/USDC',
                    'XYZ-GOLD/USDC','XYZ-SILVER/USDC'],
}
ALL_TICKERS = [t for g in GROUPS.values() for t in g]

FEE_PCT = 0.0007; SLIPPAGE_PCT = 0.0005; COST_PCT = FEE_PCT + SLIPPAGE_PCT
INITIAL = 1000.0; SL_PCT = 0.035

exchange = ccxt.hyperliquid({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# ── Data ────────────────────────────────────────────────────────────────
def fetch(ticker, days=62):
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
    c = df['close']; v = df['volume']
    # RSI
    d = c.diff()
    g = d.where(d>0,0).rolling(14).mean(); l = (-d.where(d<0,0)).rolling(14).mean()
    df['rsi'] = (100-(100/(1+g/l.replace(0,np.nan)))).fillna(50)
    # EMAs
    for span, col in [(8,'ema8'),(20,'ema20'),(50,'ema50'),(200,'ema200')]:
        df[col] = c.ewm(span=span, adjust=False).mean()
    # MACD
    df['macd'] = c.ewm(span=12,adjust=False).mean() - c.ewm(span=26,adjust=False).mean()
    df['macd_sig'] = df['macd'].ewm(span=9,adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    # Bollinger
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    df['bb_upper'] = sma20 + 2*std20; df['bb_lower'] = sma20 - 2*std20; df['bb_mid'] = sma20
    # ATR
    hl = df['high']-df['low']
    hc = (df['high']-c.shift()).abs(); lc = (df['low']-c.shift()).abs()
    df['atr'] = pd.concat([hl,hc,lc],axis=1).max(axis=1).rolling(14).mean()
    # ADX
    pdm = df['high'].diff().clip(lower=0); ndm = (-df['low'].diff()).clip(lower=0)
    pdm[pdm<ndm]=0; ndm[ndm<pdm]=0
    pdi = 100*pdm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    ndi = 100*ndm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    dx  = (100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)).fillna(0)
    df['adx'] = dx.rolling(14).mean().fillna(0)
    df['plus_di'] = pdi.fillna(0); df['minus_di'] = ndi.fillna(0)
    # Supertrend (10,3)
    hl2 = (df['high']+df['low'])/2
    ub = (hl2 + 3*df['atr']).copy(); lb = (hl2 - 3*df['atr']).copy()
    st = pd.Series(index=df.index, dtype=float); st_dir = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if pd.isna(ub.iloc[i]) or pd.isna(lb.iloc[i]): continue
        ub.iloc[i] = min(ub.iloc[i], ub.iloc[i-1]) if c.iloc[i-1] <= ub.iloc[i-1] else ub.iloc[i]
        lb.iloc[i] = max(lb.iloc[i], lb.iloc[i-1]) if c.iloc[i-1] >= lb.iloc[i-1] else lb.iloc[i]
        prev_st = st.iloc[i-1] if not pd.isna(st.iloc[i-1]) else lb.iloc[i]
        if prev_st == ub.iloc[i-1]:
            st.iloc[i] = ub.iloc[i] if c.iloc[i] < ub.iloc[i] else lb.iloc[i]
            st_dir.iloc[i] = -1 if c.iloc[i] < ub.iloc[i] else 1
        else:
            st.iloc[i] = lb.iloc[i] if c.iloc[i] > lb.iloc[i] else ub.iloc[i]
            st_dir.iloc[i] = 1 if c.iloc[i] > lb.iloc[i] else -1
    df['st_dir'] = st_dir
    # Volume MA
    df['vol_ma20'] = v.rolling(20).mean()
    # Donchian
    df['dc_high'] = df['high'].rolling(20).max()
    df['dc_low']  = df['low'].rolling(20).min()
    # Stochastic RSI (14,3,3)
    rsi_min = df['rsi'].rolling(14).min(); rsi_max = df['rsi'].rolling(14).max()
    stoch_rsi = (df['rsi'] - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    df['stoch_k'] = stoch_rsi.fillna(0.5).rolling(3).mean()
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()
    return df.dropna(subset=['ema200','adx','st_dir']).copy()

# ── Backtest engine (direction-filtered) ──────────────────────────────
def backtest(df, sig_func, only_direction=0):
    """only_direction: 0=both, 1=longs only, -1=shorts only"""
    capital = INITIAL; position = 0.0; entry_price = 0.0
    sl_price = 0.0; direction = 0; trades = []
    for i in range(50, len(df)):
        row = df.iloc[i]; price = row['close']
        hi = row['high']; lo = row['low']
        if direction == 1 and position > 0 and lo <= sl_price:
            r = (sl_price-entry_price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append(r); position=0; direction=0
        elif direction == -1 and position > 0 and hi >= sl_price:
            r = (entry_price-sl_price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append(r); position=0; direction=0
        sig = sig_func(df, i)
        if only_direction != 0 and sig != 0 and sig != only_direction:
            sig = 0  # filter out wrong direction
        if direction == 1 and position > 0 and sig < 0:
            r = (price-entry_price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append(r); position=0; direction=0
        elif direction == -1 and position > 0 and sig > 0:
            r = (entry_price-price)/entry_price
            capital += r*capital - abs(capital*COST_PCT)
            trades.append(r); position=0; direction=0
        if direction == 0 and sig != 0:
            entry_price=price; direction=int(sig)
            sl_price = price*(1-SL_PCT) if sig>0 else price*(1+SL_PCT)
            capital -= capital*COST_PCT; position=capital/price
    if direction != 0 and position > 0:
        price = df.iloc[-1]['close']
        r = (price-entry_price)/entry_price if direction==1 else (entry_price-price)/entry_price
        capital += r*capital - abs(capital*COST_PCT); trades.append(r)
    n = len(trades); wins=[t for t in trades if t>0]; losses=[t for t in trades if t<=0]
    gw=sum(wins); gl=abs(sum(losses))
    pf = gw/gl if gl>0 else (999.0 if gw>0 else 0.0)
    return {'pnl': (capital-INITIAL)/INITIAL*100, 'n':n,
            'wr': len(wins)/n if n>0 else 0, 'pf': pf}

def avg_across(tickers, raw_data, sig_func, direction, cutoff):
    pnls=[]; wrs=[]; pfs=[]; ns=[]
    for t in tickers:
        if t not in raw_data: continue
        df = raw_data[t].tail(cutoff).reset_index(drop=True)
        if len(df) < 80: continue
        r = backtest(df, sig_func, only_direction=direction)
        if r['n'] > 0:
            pnls.append(r['pnl']); wrs.append(r['wr'])
            pfs.append(r['pf']); ns.append(r['n'])
    if not pnls: return {'pnl':0,'wr':0,'pf':0,'n':0}
    return {'pnl': sum(pnls)/len(pnls), 'wr': sum(wrs)/len(wrs),
            'pf': sum(pfs)/len(pfs), 'n': sum(ns)}

# ── LONG strategies (5) ──────────────────────────────────────────────
def L_macd_adx(df, i):          # previous best for crypto
    r=df.iloc[i]; p=df.iloc[i-1]
    if r['adx']<20: return 0
    if p['macd']<0 and r['macd']>=0 and r['plus_di']>r['minus_di']: return 1
    return 0

def L_trend_cont(df, i):        # previous best for stocks
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    if price>r['ema200'] and p['macd_hist']<0 and r['macd_hist']>=0 and r['adx']>15: return 1
    return 0

def L_supertrend(df, i):        # supertrend flip bullish + ADX
    r=df.iloc[i]; p=df.iloc[i-1]
    if p['st_dir']==-1 and r['st_dir']==1 and r['adx']>18: return 1
    return 0

def L_ema_ribbon(df, i):        # full bull EMA alignment + RSI momentum
    r=df.iloc[i]; price=r['close']
    if price>r['ema8']>r['ema20']>r['ema50'] and 52<=r['rsi']<=72 and r['adx']>15: return 1
    return 0

def L_stoch_oversold(df, i):    # stochastic RSI oversold bounce + trend
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    if p['stoch_k']<0.20 and r['stoch_k']>p['stoch_k'] and price>r['ema50']: return 1
    return 0

# ── SHORT strategies (6) ──────────────────────────────────────────────
def S_macd_adx(df, i):          # MACD cross below zero + ADX
    r=df.iloc[i]; p=df.iloc[i-1]
    if r['adx']<20: return 0
    if p['macd']>0 and r['macd']<=0 and r['minus_di']>r['plus_di']: return -1
    return 0

def S_trend_cont(df, i):        # trend continuation short (below EMA200)
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    if price<r['ema200'] and p['macd_hist']>0 and r['macd_hist']<=0 and r['adx']>15: return -1
    return 0

def S_supertrend(df, i):        # supertrend flip bearish + ADX
    r=df.iloc[i]; p=df.iloc[i-1]
    if p['st_dir']==1 and r['st_dir']==-1 and r['adx']>18: return -1
    return 0

def S_bb_rejection(df, i):      # BB upper band rejection + MACD turning down
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    # prev candle touched upper BB, this candle closes below mid + MACD turning neg
    prev_touched = p['close'] >= p['bb_upper'] * 0.99
    macd_turning = p['macd_hist']>0 and r['macd_hist']<p['macd_hist']
    if prev_touched and macd_turning and price < r['bb_mid'] and r['adx']>15: return -1
    return 0

def S_ema_bear_ribbon(df, i):   # full bear EMA alignment + RSI in bear zone
    r=df.iloc[i]; price=r['close']
    if price<r['ema8']<r['ema20']<r['ema50'] and 28<=r['rsi']<=50 and r['adx']>15: return -1
    return 0

def S_rsi_overbought(df, i):    # RSI crosses back below 70 from overbought + price below EMA20
    r=df.iloc[i]; p=df.iloc[i-1]
    if p['rsi']>=70 and r['rsi']<70 and r['close']<r['ema20'] and r['adx']>15: return -1
    return 0

def S_donchian_breakdown(df, i):  # new 20-period low + volume spike
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    vol_spike = r['volume'] > r['vol_ma20']*1.4
    if price < p['dc_low'] and vol_spike and r['adx']>18: return -1
    return 0

LONG_STRATS  = [('L_macd_adx',L_macd_adx),('L_trend_cont',L_trend_cont),
                ('L_supertrend',L_supertrend),('L_ema_ribbon',L_ema_ribbon),
                ('L_stoch_oversold',L_stoch_oversold)]

SHORT_STRATS = [('S_macd_adx',S_macd_adx),('S_trend_cont',S_trend_cont),
                ('S_supertrend',S_supertrend),('S_bb_rejection',S_bb_rejection),
                ('S_ema_bear_ribbon',S_ema_bear_ribbon),
                ('S_rsi_overbought',S_rsi_overbought),
                ('S_donchian_breakdown',S_donchian_breakdown)]

# ── Combined strategy factory ─────────────────────────────────────────
def make_hybrid(long_func, short_func):
    def hybrid(df, i):
        s = long_func(df, i)
        if s != 0: return s
        return short_func(df, i)
    return hybrid

# Previous best for comparison
def PREV_macd_adx_both(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]
    if r['adx']<20: return 0
    if p['macd']<0 and r['macd']>=0 and r['plus_di']>r['minus_di']:  return  1
    if p['macd']>0 and r['macd']<=0 and r['minus_di']>r['plus_di']:  return -1
    return 0

def PREV_trend_cont_both(df, i):
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    above=price>r['ema200']
    if above and p['macd_hist']<0 and r['macd_hist']>=0 and r['adx']>15:     return  1
    if not above and p['macd_hist']>0 and r['macd_hist']<=0 and r['adx']>15: return -1
    return 0

# ── Main ─────────────────────────────────────────────────────────────
def main():
    print('Fetching 62d data...')
    raw_data = {}
    for t in ALL_TICKERS:
        df = fetch(t, 62)
        if not df.empty and len(df) > 100:
            raw_data[t] = add_indicators(df)
    print(f'Ready: {len(raw_data)} tickers\n')

    for window_days, label in [(60,'60d'), (30,'30d'), (7,'7d')]:
        cutoff = window_days*24 + 50
        print(f'\n{"="*72}')
        print(f'WINDOW: {label}')
        print('='*72)

        for group_name, tickers in GROUPS.items():
            valid = [t for t in tickers if t in raw_data]
            if not valid: continue

            print(f'\n  [{group_name}]')

            # Step 1: find best long strategy
            print(f'    LONG candidates:')
            long_results = []
            for name, func in LONG_STRATS:
                m = avg_across(valid, raw_data, func, direction=1, cutoff=cutoff)
                long_results.append((name, func, m))
            long_results.sort(key=lambda x: -x[2]['pnl'])
            for name, _, m in long_results:
                print(f'      {name:<22} pnl={m["pnl"]:>7.1f}%  WR={m["wr"]*100:.0f}%  PF={m["pf"]:.2f}  n={m["n"]}')

            # Step 2: find best short strategy
            print(f'    SHORT candidates:')
            short_results = []
            for name, func in SHORT_STRATS:
                m = avg_across(valid, raw_data, func, direction=-1, cutoff=cutoff)
                short_results.append((name, func, m))
            short_results.sort(key=lambda x: -x[2]['pnl'])
            for name, _, m in short_results:
                print(f'      {name:<22} pnl={m["pnl"]:>7.1f}%  WR={m["wr"]*100:.0f}%  PF={m["pf"]:.2f}  n={m["n"]}')

            # Step 3: best long + best short combined
            best_l_name, best_l_func, best_l_m = long_results[0]
            best_s_name, best_s_func, best_s_m = short_results[0]
            hybrid = make_hybrid(best_l_func, best_s_func)

            pnls=[]; wrs=[]; pfs=[]; ns=[]
            for t in valid:
                if t not in raw_data: continue
                df = raw_data[t].tail(cutoff).reset_index(drop=True)
                if len(df)<80: continue
                r = backtest(df, hybrid, only_direction=0)
                pnls.append(r['pnl']); wrs.append(r['wr']); pfs.append(r['pf']); ns.append(r['n'])
            hybrid_pnl = sum(pnls)/len(pnls) if pnls else 0
            hybrid_wr  = sum(wrs)/len(wrs)   if wrs else 0
            hybrid_pf  = sum(pfs)/len(pfs)   if pfs else 0
            hybrid_n   = sum(ns)

            # Step 4: previous best
            prev_func = PREV_macd_adx_both if group_name == 'Crypto' else PREV_trend_cont_both
            prev_name = 'MACD_ADX_both' if group_name == 'Crypto' else 'TrendCont_both'
            pnls2=[]; wrs2=[]; pfs2=[]; ns2=[]
            for t in valid:
                if t not in raw_data: continue
                df = raw_data[t].tail(cutoff).reset_index(drop=True)
                if len(df)<80: continue
                r = backtest(df, prev_func, only_direction=0)
                pnls2.append(r['pnl']); wrs2.append(r['wr']); pfs2.append(r['pf']); ns2.append(r['n'])
            prev_pnl = sum(pnls2)/len(pnls2) if pnls2 else 0
            prev_wr  = sum(wrs2)/len(wrs2)   if wrs2 else 0
            prev_pf  = sum(pfs2)/len(pfs2)   if pfs2 else 0
            prev_n   = sum(ns2)

            delta = hybrid_pnl - prev_pnl
            beat  = 'BEATS' if delta > 0 else 'LOSES'

            print(f'\n    RESULT [{label}] {group_name}:')
            print(f'      Hybrid  ({best_l_name} + {best_s_name})')
            print(f'        pnl={hybrid_pnl:>7.1f}%  WR={hybrid_wr*100:.0f}%  PF={hybrid_pf:.2f}  n={hybrid_n}')
            print(f'      Prev    ({prev_name})')
            print(f'        pnl={prev_pnl:>7.1f}%  WR={prev_wr*100:.0f}%  PF={prev_pf:.2f}  n={prev_n}')
            print(f'      -> {beat} previous by {delta:+.1f}pp')

        # Grand summary
        print(f'\n  GRAND TOTAL [{label}] -- Hybrid vs Previous:')
        print(f'  {"Group":<14} {"Hybrid":>10} {"Previous":>10} {"Delta":>8}')
        print(f'  {"-"*46}')
        for group_name, tickers in GROUPS.items():
            valid = [t for t in tickers if t in raw_data]
            if not valid: continue
            # recompute quickly
            best_l_func = long_results[0][1] if group_name=='Crypto' else long_results[0][1]
            # (just use prev funcs for summary — full per-group already printed above)

if __name__ == '__main__':
    main()
