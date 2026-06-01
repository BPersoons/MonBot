import ccxt
hl = ccxt.hyperliquid()
hl.load_markets()
keywords = ['XYZ', 'WTIOIL', 'BRENT', 'SP500', 'COPPER', 'SNDK', 'GOLD', 'SILVER', 'CRCL']
for sym, mkt in sorted(hl.markets.items()):
    if any(k in sym.upper() for k in keywords):
        base = mkt.get("base", "?")
        mtype = mkt.get("type", "?")
        info_name = mkt.get("info", {}).get("name", "?")
        print(f"  {sym:40} base={base:15} type={mtype:6} info_name={info_name}")
