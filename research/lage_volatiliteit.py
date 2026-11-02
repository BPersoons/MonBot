"""Lage-volatiliteitseffect (idee 2026-11-02): levert een min-vol-fonds meer op dan de index
met dezelfde beta (index + kas)? Structurele premie (Blitz & van Vliet 2007, Frazzini & Pedersen
2014), geen richting voorspellen. Maandrendementen (regel 8: geen dagkoersen voor beta), kas = BIL.
Criterium zoals risicopotjes: het moet in BEIDE helften werken.

Uitkomst 02-11: 15 jaar +1,1 tot +1,4%/jr na beta, maar 1e helft (2011-2019) +3,8 tot +4,5%,
2e helft (2019-2026) -1,2 tot -2,3%. Gestopt. De UCITS-reeks (IQQ0.DE) is onbetrouwbaar
(volatiliteit hoger dan de index: datafout), alleen ter informatie.

    python research/lage_volatiliteit.py
"""
import sys, numpy as np, pandas as pd, yfinance as yf
sys.stdout.reconfigure(encoding="utf-8")
def maand(tk, start):
    d = yf.download(tk, start=start, auto_adjust=True, progress=False)["Close"]
    return d.resample("ME").last().pct_change().dropna()
def stats(rp, rm, rf, naam):
    df = pd.concat([rp, rm, rf], axis=1, join="inner").dropna(); df.columns = ["p","m","f"]
    ep, em = df.p - df.f, df.m - df.f
    beta = np.cov(ep, em)[0,1] / em.var()
    alpha = (ep - beta*em).mean()*12
    ann = lambda r: (1+r).prod()**(12/len(r)) - 1
    dd = lambda r: ((1+r).cumprod()/(1+r).cumprod().cummax()-1).min()
    mix = df.f + beta*em   # zelfde beta: index + kas
    print(f"{naam:34s} {df.index[0]:%Y-%m}..{df.index[-1]:%Y-%m} n={len(df)}  rend {ann(df.p):6.1%} vs index {ann(df.m):6.1%}  vol {df.p.std()*12**.5:5.1%} vs {df.m.std()*12**.5:5.1%}  daling {dd(df.p):6.1%} vs {dd(df.m):6.1%}  beta {beta:4.2f}  mix-zelfde-beta {ann(mix):6.1%}  alpha {alpha:+5.1%}/jr")
    return df
rf = maand("BIL", "2007-06-01")  # 1-3 mnd T-bills als kasrente
for p, m, start, naam in [("ACWV","ACWI","2011-10-01","MSCI ACWI Min Vol (VS-fonds)"),
                          ("USMV","SPY","2011-10-01","MSCI USA Min Vol (VS-fonds)"),
                          ("SPLV","SPY","2011-05-01","S&P 500 Low Vol (VS-fonds)")]:
    df = stats(maand(p,start), maand(m,start), rf, naam)
    h = len(df)//2
    for deel, idx in (("  1e helft", df.index[:h]), ("  2e helft", df.index[h:])):
        stats(df.p.loc[idx], df.m.loc[idx], df.f.loc[idx], naam[:20]+deel)
# koopbaar (UCITS, EUR): iShares Edge MSCI World Min Vol vs iShares Core MSCI World, kas = 0 (EUR) als ruwe benadering
z = pd.Series(0.0, index=maand("EUNL.DE","2013-01-01").index)
stats(maand("IQQ0.DE","2013-01-01"), maand("EUNL.DE","2013-01-01"), z, "UCITS World Min Vol vs World (EUR)")
