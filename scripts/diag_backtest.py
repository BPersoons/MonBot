"""Test wat de backtester + ResearchAgent filter nu retourneert."""
import sys, json
sys.path.insert(0, '/app')

# 1. Test backtester op BTC
print('=== AutoBacktester test (BTC/USDC, 7d) ===')
try:
    from utils.auto_backtester import AutoBacktester
    bt = AutoBacktester()
    df = bt.fetch_historical_data('BTC/USDC', timeframe='1h', days=7)
    print(f'Candles fetched: {len(df)}')
    if not df.empty:
        result = bt.run_simulation(df)
        print(f'Agent result: {result}')
        agent_pnl = result.get('total_pnl_pct', 0)
        print(f'Agent PnL: {agent_pnl:.2f}%')
        if agent_pnl > 0:
            print('-> PASS (positive PnL, research agent zou doorlaten)')
        else:
            print('-> FAIL (negatieve PnL, research agent FILTERT DIT UIT)')
except Exception as e:
    print(f'Backtester error: {e}')
    import traceback; traceback.print_exc()

# 2. Test op ZEC (was sterkste performer)
print()
print('=== AutoBacktester test (ZEC/USDC, 7d) ===')
try:
    bt2 = AutoBacktester()
    df2 = bt2.fetch_historical_data('ZEC/USDC', timeframe='1h', days=7)
    print(f'Candles fetched: {len(df2)}')
    if not df2.empty:
        result2 = bt2.run_simulation(df2)
        print(f'Agent result: {result2}')
        print(f'Agent PnL: {result2.get("total_pnl_pct", 0):.2f}%')
except Exception as e:
    print(f'ZEC error: {e}')

# 3. Check het VOLATILE regime threshold
print()
print('=== Regime threshold check ===')
try:
    with open('/app/market_regime.json') as f:
        mr = json.load(f)
    regime = mr.get('regime', 'NEUTRAL')
    with open('/app/config/auto_params.json') as f:
        ap = json.load(f)
    base_threshold = ap['score_threshold']
    # From project_lead.py _REGIME_THRESHOLD_MULT
    REGIME_MULT = {
        'TRENDING_BULL': 0.90,
        'TRENDING_BEAR': 1.10,
        'VOLATILE':      1.20,
        'RANGING':       1.00,
        'NEUTRAL':       1.00,
    }
    mult = REGIME_MULT.get(regime, 1.0)
    effective = base_threshold * mult
    print(f'Regime: {regime}')
    print(f'base score_threshold: {base_threshold}')
    print(f'regime multiplier: x{mult}')
    print(f'EFFECTIVE threshold: {effective:.3f}')
    if effective > 0.22:
        print('-> WAARSCHUWING: effectieve threshold is bijna zo hoog als de noodstop (0.25)!')
except Exception as e:
    print(f'Regime check error: {e}')

# 4. Research agent — wat zitten in recent proposals?
print()
print('=== ResearchAgent recente kandidaten ===')
try:
    with open('/app/dashboard.json') as f:
        dash = json.load(f)
    pipe = dash.get('discovery_pipeline', {})
    proposals = pipe.get('proposals', [])
    last_run = pipe.get('last_run', '?')
    print(f'Last research run: {last_run}')
    print(f'Current proposals: {len(proposals)}')
    # Market data summary
    md = dash.get('market_data', {})
    print(f'Market data tickers: {len(md)}')
except Exception as e:
    print(f'Dashboard error: {e}')
