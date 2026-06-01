"""
FINALE STRATEGIE — volledig advies voor implementatie.

Regime-aware: EMA200 + ADX bepalen automatisch wanneer long/short.
Drie asset-klassen: crypto, tech stocks, commodities.
Vergelijking: finale vs huidige agent.
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

# ── Data & indicators ────────────────────────────────────────────────
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
    d = c.diff()
    g = d.where(d>0,0).rolling(14).mean(); l = (-d.where(d<0,0)).rolling(14).mean()
    df['rsi'] = (100-(100/(1+g/l.replace(0,np.nan)))).fillna(50)
    for span, col in [(8,'ema8'),(20,'ema20'),(50,'ema50'),(200,'ema200')]:
        df[col] = c.ewm(span=span, adjust=False).mean()
    df['macd'] = c.ewm(span=12,adjust=False).mean() - c.ewm(span=26,adjust=False).mean()
    df['macd_sig'] = df['macd'].ewm(span=9,adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_sig']
    sma20 = c.rolling(20).mean(); std20 = c.rolling(20).std()
    df['bb_upper'] = sma20 + 2*std20; df['bb_lower'] = sma20 - 2*std20; df['bb_mid'] = sma20
    hl2 = df['high']-df['low']
    hc = (df['high']-c.shift()).abs(); lc = (df['low']-c.shift()).abs()
    df['atr'] = pd.concat([hl2,hc,lc],axis=1).max(axis=1).rolling(14).mean()
    pdm = df['high'].diff().clip(lower=0); ndm = (-df['low'].diff()).clip(lower=0)
    pdm[pdm<ndm]=0; ndm[ndm<pdm]=0
    pdi = 100*pdm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    ndi = 100*ndm.rolling(14).mean()/df['atr'].replace(0,np.nan)
    dx = (100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)).fillna(0)
    df['adx'] = dx.rolling(14).mean().fillna(0)
    df['plus_di'] = pdi.fillna(0); df['minus_di'] = ndi.fillna(0)
    # Stochastic RSI
    rsi_min = df['rsi'].rolling(14).min(); rsi_max = df['rsi'].rolling(14).max()
    df['stoch_k'] = ((df['rsi']-rsi_min)/(rsi_max-rsi_min).replace(0,np.nan)).fillna(0.5).rolling(3).mean()
    # Supertrend (10, 3)
    ub = ((df['high']+df['low'])/2 + 3*df['atr']).copy()
    lb = ((df['high']+df['low'])/2 - 3*df['atr']).copy()
    st_dir = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if pd.isna(ub.iloc[i]): continue
        ub.iloc[i] = min(ub.iloc[i], ub.iloc[i-1]) if c.iloc[i-1] <= ub.iloc[i-1] else ub.iloc[i]
        lb.iloc[i] = max(lb.iloc[i], lb.iloc[i-1]) if c.iloc[i-1] >= lb.iloc[i-1] else lb.iloc[i]
        st_dir.iloc[i] = (-1 if c.iloc[i] < ub.iloc[i] else 1) if st_dir.iloc[i-1]==-1 else (1 if c.iloc[i] > lb.iloc[i] else -1)
    df['st_dir'] = st_dir
    df['vol_ma20'] = v.rolling(20).mean()
    # Divergence helper
    df['rsi_10ago'] = df['rsi'].shift(10); df['close_10ago'] = c.shift(10)
    return df.dropna(subset=['ema200','adx','st_dir']).copy()

# ── Backtest engine ──────────────────────────────────────────────────
def backtest(df, sig_func, sl_pct=SL_PCT):
    capital = INITIAL; pos = 0.0; ep = 0.0; sl = 0.0; direction = 0
    long_trades=[]; short_trades=[]; regime_log=[]
    for i in range(50, len(df)):
        r=df.iloc[i]; price=r['close']; hi=r['high']; lo=r['low']
        if direction==1 and pos>0 and lo<=sl:
            pnl_r=(sl-ep)/ep; capital+=pnl_r*capital-abs(capital*COST_PCT)
            long_trades.append(pnl_r); pos=0; direction=0
        elif direction==-1 and pos>0 and hi>=sl:
            pnl_r=(ep-sl)/ep; capital+=pnl_r*capital-abs(capital*COST_PCT)
            short_trades.append(pnl_r); pos=0; direction=0
        sig = sig_func(df, i)
        if direction==1 and pos>0 and sig<0:
            pnl_r=(price-ep)/ep; capital+=pnl_r*capital-abs(capital*COST_PCT)
            long_trades.append(pnl_r); pos=0; direction=0
        elif direction==-1 and pos>0 and sig>0:
            pnl_r=(ep-price)/ep; capital+=pnl_r*capital-abs(capital*COST_PCT)
            short_trades.append(pnl_r); pos=0; direction=0
        if direction==0 and sig!=0:
            ep=price; direction=int(sig)
            sl=price*(1-sl_pct) if sig>0 else price*(1+sl_pct)
            capital-=capital*COST_PCT; pos=capital/price
            regime_log.append('L' if sig>0 else 'S')
    if direction!=0 and pos>0:
        price=df.iloc[-1]['close']
        pnl_r=(price-ep)/ep if direction==1 else (ep-price)/ep
        capital+=pnl_r*capital-abs(capital*COST_PCT)
        (long_trades if direction==1 else short_trades).append(pnl_r)

    def m(trades):
        if not trades: return {'n':0,'wr':0,'pf':0,'pnl_pct':0}
        wins=[t for t in trades if t>0]; losses=[t for t in trades if t<=0]
        gw=sum(wins); gl=abs(sum(losses))
        return {'n':len(trades),'wr':len(wins)/len(trades),
                'pf':gw/gl if gl>0 else (999 if gw>0 else 0),
                'pnl_pct':(capital-INITIAL)/INITIAL*100}
    return {
        'final': capital,
        'pnl_pct': (capital-INITIAL)/INITIAL*100,
        'n': len(long_trades)+len(short_trades),
        'long': m(long_trades), 'short': m(short_trades),
        'regime_log': regime_log,
    }

# ═══════════════════════════════════════════════════════════════════
# FINALE SIGNAALFUNCTIES
# ═══════════════════════════════════════════════════════════════════

def signal_crypto(df, i):
    """
    CRYPTO:
    LONG  — MACD zero-cross omhoog (ADX>20, +DI>-DI, boven EMA200)
           OF stoch-RSI oversold bounce boven EMA50
    SHORT — BB upper rejection (prev candle raakte upper, deze sluit <midlijn, MACD draait)
           OF trend-continuation short (onder EMA200, MACD-hist flip negatief)
    REGIME: EMA200 bepaalt voorkeur; ADX filtert chop
    """
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    above_200 = price > r['ema200']
    adx = r['adx']

    # --- LONG signalen ---
    # 1. MACD zero-cross in bull regime
    if (above_200 and adx > 20
            and p['macd'] < 0 and r['macd'] >= 0
            and r['plus_di'] > r['minus_di']):
        return 1

    # 2. Stoch-RSI oversold bounce boven EMA50 (dip-buy in uptrend)
    if (above_200 and r['stoch_k'] < 0.20
            and r['stoch_k'] > p['stoch_k']
            and price > r['ema50'] and adx > 15):
        return 1

    # --- SHORT signalen ---
    # 3. BB upper rejection (overbought afwijzing)
    prev_touched = p['close'] >= p['bb_upper'] * 0.99
    macd_turning  = p['macd_hist'] > 0 and r['macd_hist'] < p['macd_hist']
    if (prev_touched and macd_turning
            and price < r['bb_mid'] and adx > 15):
        return -1

    # 4. Trend-continuation short (bear regime)
    if (not above_200
            and p['macd_hist'] > 0 and r['macd_hist'] <= 0
            and adx > 15):
        return -1

    return 0


def signal_tech(df, i):
    """
    TECH STOCKS:
    LONG  — Supertrend flip bullish (ADX>18)
           OF trend-continuation long boven EMA200 (MACD-hist flip positief)
    SHORT — ALLEEN als prijs < EMA200: bearish divergentie (hogere prijs, lagere RSI)
           (tech shorts zijn zwak in bull market; regime-gate is verplicht)
    """
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    above_200 = price > r['ema200']
    adx = r['adx']

    # --- LONG ---
    # 1. Supertrend flip bullish
    if p['st_dir'] == -1 and r['st_dir'] == 1 and adx > 18:
        return 1

    # 2. Trend continuation long (boven EMA200, MACD hist flip)
    if (above_200
            and p['macd_hist'] < 0 and r['macd_hist'] >= 0
            and adx > 15):
        return 1

    # --- SHORT (alleen bear regime) ---
    if (not above_200
            and not pd.isna(r.get('close_10ago'))
            and price > r['close_10ago'] * 1.01     # hogere prijs
            and r['rsi'] < r['rsi_10ago'] - 3):      # lagere RSI = divergentie
        return -1

    return 0


def signal_commodities(df, i):
    """
    COMMODITIES:
    LONG  — Volledige EMA ribbon bullish (prijs>ema8>ema20>ema50) + RSI momentum zone + ADX
    SHORT — Supertrend flip bearish + ADX>18
           OF MACD zero-cross omlaag in bear regime
    BEIDE kanten werken: commodities hebben duidelijke trends in beide richtingen
    """
    r=df.iloc[i]; p=df.iloc[i-1]; price=r['close']
    above_200 = price > r['ema200']
    adx = r['adx']

    # --- LONG ---
    if (price > r['ema8'] > r['ema20'] > r['ema50']
            and 52 <= r['rsi'] <= 72
            and adx > 15):
        return 1

    # --- SHORT ---
    # 1. Supertrend flip bearish
    if p['st_dir'] == 1 and r['st_dir'] == -1 and adx > 18:
        return -1

    # 2. MACD zero-cross omlaag in bear regime
    if (not above_200 and adx > 20
            and p['macd'] > 0 and r['macd'] <= 0
            and r['minus_di'] > r['plus_di']):
        return -1

    return 0


def signal_agent_baseline(df, i):
    """Huidige strategie (RSI+EMA, beide richtingen)."""
    r=df.iloc[i]; price=r['close']; rsi=r['rsi']; e20=r['ema20']; e50=r['ema50']
    s=0.0
    if rsi>70: s-=0.4
    elif rsi>60: s+=0.2
    elif rsi<30: s+=0.4
    elif rsi<40: s-=0.2
    if price>e20>e50: s+=0.5
    elif price>e20: s+=0.3
    elif price<e20<e50: s-=0.5
    elif price<e20: s-=0.3
    s=max(-1,min(1,s))
    return 1 if s>0.3 else (-1 if s<-0.3 else 0)


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print('Fetching 62d data...')
    raw_data = {}
    for t in ALL_TICKERS:
        df = fetch(t, 62)
        if not df.empty and len(df) > 100:
            raw_data[t] = add_indicators(df)
    print(f'Ready: {len(raw_data)} tickers')

    SIGNAL_MAP = {
        'Crypto':      signal_crypto,
        'TechStocks':  signal_tech,
        'Commodities': signal_commodities,
    }

    for window_days, label in [(60,'60d'), (30,'30d'), (7,'7d')]:
        cutoff = window_days*24 + 50
        print(f'\n{"="*72}')
        print(f'FINALE STRATEGIE vs HUIDIGE AGENT -- {label}')
        print('='*72)

        total_final_pnl=[]; total_base_pnl=[]

        for group_name, tickers in GROUPS.items():
            valid=[t for t in tickers if t in raw_data]
            if not valid: continue
            sig_func = SIGNAL_MAP[group_name]

            f_pnls=[]; f_ls=[]; f_ss=[]; f_ns=[]
            b_pnls=[]; b_ns=[]

            per_ticker=[]
            for t in valid:
                df = raw_data[t].tail(cutoff).reset_index(drop=True)
                if len(df)<80: continue

                fr = backtest(df, sig_func)
                br = backtest(df, signal_agent_baseline)

                f_pnls.append(fr['pnl_pct']); f_ls.append(fr['long'])
                f_ss.append(fr['short']); f_ns.append(fr['n'])
                b_pnls.append(br['pnl_pct']); b_ns.append(br['n'])
                total_final_pnl.append(fr['pnl_pct'])
                total_base_pnl.append(br['pnl_pct'])

                # count L/S distribution
                ls = fr['regime_log']
                n_l = ls.count('L'); n_s = ls.count('S')
                per_ticker.append((t.split('-')[-1].split('/')[0],
                                   fr['pnl_pct'], br['pnl_pct'],
                                   n_l, n_s, fr['long']['wr'], fr['short']['wr']))

            avg_f = sum(f_pnls)/len(f_pnls) if f_pnls else 0
            avg_b = sum(b_pnls)/len(b_pnls) if b_pnls else 0
            # aggregate long/short stats
            agg_l_wr = sum(x['wr'] for x in f_ls if x['n']>0)/max(1,sum(1 for x in f_ls if x['n']>0))
            agg_s_wr = sum(x['wr'] for x in f_ss if x['n']>0)/max(1,sum(1 for x in f_ss if x['n']>0))
            agg_l_n  = sum(x['n'] for x in f_ls)
            agg_s_n  = sum(x['n'] for x in f_ss)

            delta = avg_f - avg_b
            beat  = 'BEATS' if delta>0 else 'LOSES'
            print(f'\n  [{group_name}]  Finale: {avg_f:+.1f}%  Baseline: {avg_b:+.1f}%  -> {beat} {delta:+.1f}pp')
            print(f'  Longs: {agg_l_n} trades  WR={agg_l_wr*100:.0f}%  |  '
                  f'Shorts: {agg_s_n} trades  WR={agg_s_s_wr:.0f}%' if False else
                  f'  Longs: {agg_l_n} trades  WR={agg_l_wr*100:.0f}%  |  '
                  f'Shorts: {agg_s_n} trades  WR={agg_s_wr*100:.0f}%')
            print(f'  {"Ticker":<10} {"Finale":>8} {"Baseline":>9} {"Longs":>7} {"Shorts":>8} {"L-WR":>7} {"S-WR":>7}')
            print(f'  {"-"*60}')
            for t_name,fp,bp,nl,ns,lwr,swr in sorted(per_ticker,key=lambda x:-x[1]):
                diff = fp-bp
                flag = ' +'if diff>0 else ''
                print(f'  {t_name:<10} {fp:>8.1f}% {bp:>8.1f}% {nl:>7} {ns:>8} '
                      f'{lwr*100:>6.0f}% {swr*100:>6.0f}%{flag}')

        # Grand totals
        gf = sum(total_final_pnl)/len(total_final_pnl) if total_final_pnl else 0
        gb = sum(total_base_pnl)/len(total_base_pnl)   if total_base_pnl else 0
        print(f'\n  {"="*60}')
        print(f'  GRAND TOTAL ({label}) over {len(total_final_pnl)} tickers')
        print(f'  Finale strategie:  {gf:>+7.1f}%  gemiddeld per ticker')
        print(f'  Huidige agent:     {gb:>+7.1f}%  gemiddeld per ticker')
        print(f'  Verbetering:       {gf-gb:>+7.1f}pp')
        mult = gf/gb if gb!=0 else float('inf')
        if gb < 0 and gf > 0:
            print(f'  -> Van verlies naar winst (oneindig beter)')
        else:
            print(f'  -> {abs(mult):.1f}x {"beter" if gf>gb else "slechter"}')

    # ── Regime breakdown: wanneer long vs short? ──────────────────────
    print(f'\n{"="*72}')
    print('REGIME LOGICA — wanneer long, wanneer short?')
    print('='*72)
    print("""
  CRYPTO:
    LONG  wanneer:  prijs > EMA200  EN  (MACD kruist nul omhoog + ADX>20 + +DI>-DI)
                    OF prijs > EMA200  EN  stoch-RSI < 0.20 (oversold dip-buy)
    SHORT wanneer:  vorige candle raakte BB-upper EN MACD draait omlaag EN prijs < midlijn
                    OF prijs < EMA200  EN  MACD-histogram flip negatief + ADX>15

  TECH STOCKS:
    LONG  wanneer:  supertrend flip bullish (ADX>18)
                    OF prijs > EMA200  EN  MACD-hist flip positief + ADX>15
    SHORT wanneer:  prijs < EMA200  EN  hogere prijs + lagere RSI (bearish divergentie)
                    (geen shorts in bull-regime — structureel slecht getest)

  COMMODITIES:
    LONG  wanneer:  prijs > ema8 > ema20 > ema50 (volledige bull ribbon)
                    EN RSI 52-72 (momentum, niet overbought) EN ADX>15
    SHORT wanneer:  supertrend flip bearish + ADX>18
                    OF prijs < EMA200  EN  MACD zero-cross omlaag + ADX>20

  SLEUTELREGEL:
    EMA200 = regime-grens. Erboven = bull-bias (voorkeur longs).
    Eronder = bear-bias (voorkeur shorts).
    ADX > 15-20 = trending markt. Eronder = chop -> geen trade.
""")

if __name__ == '__main__':
    main()
