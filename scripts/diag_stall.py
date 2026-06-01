"""Diagnose waarom het systeem na 15:57 gisteren stopt met beslissingen."""
import json, sys
from datetime import datetime
sys.path.insert(0, '/app')

# 1. Ticker state — zijn alles in cooldown?
try:
    with open('/app/ticker_state.json') as f:
        ts = json.load(f)
    now_str = datetime.utcnow().isoformat()
    print('TICKER STATE (cooldowns):')
    frozen = 0
    for key, val in list(ts.items())[:30]:
        next_check = val.get('next_check', '')
        status = val.get('last_decision', '?')
        score = val.get('last_score', 0)
        print('  {:<30} status={:<10} next_check={}'.format(key[:30], status, next_check[:16]))
        if next_check > now_str:
            frozen += 1
    print(f'  ... {len(ts)} total entries, {frozen} still in cooldown')
except Exception as e:
    print('ticker_state error:', e)

# 2. Recent heartbeat log
print()
print('RECENT HEARTBEAT LOG (last 30 lines):')
try:
    with open('/app/logs/heartbeat.log') as f:
        lines = f.readlines()
    for line in lines[-30:]:
        print(' ', line.rstrip())
except Exception as e:
    print('heartbeat.log error:', e)

# 3. Dashboard — pipeline proposals
print()
print('DASHBOARD PIPELINE PROPOSALS:')
try:
    with open('/app/dashboard.json') as f:
        dash = json.load(f)
    proposals = dash.get('discovery_pipeline', {}).get('proposals', [])
    print(f'  {len(proposals)} proposals in pipeline')
    for p in proposals[:5]:
        print('  ticker={} dir={} reason={}'.format(
            p.get('ticker','?'), p.get('direction','?'), p.get('reason','?')[:60]))
    cycle = dash.get('cycle_count', '?')
    last = dash.get('last_update', '?')
    status = dash.get('status', '?')
    print(f'  cycle_count={cycle} last_update={last} status={status}')
except Exception as e:
    print('dashboard error:', e)

# 4. Market regime
print()
print('MARKET REGIME:')
try:
    with open('/app/market_regime.json') as f:
        mr = json.load(f)
    print('  regime={} direction={} adx={} atr_rank={}'.format(
        mr.get('regime','?'), mr.get('direction','?'),
        mr.get('adx','?'), mr.get('atr_rank','?')))
except Exception as e:
    print('market_regime error:', e)
