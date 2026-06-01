"""One-time fix: restore original entry_times for RECOVERED trades from their ghost-closed predecessors."""
import json

trades = json.load(open('/app/trade_log.json'))

# Build map: ticker -> earliest ghost-closed entry_time
earliest = {}
for t in trades:
    if (t.get('status') == 'CLOSED'
        and t.get('close_reason') in ('GHOST_POSITION_SYNC', 'EXTERNAL_CLOSURE')
        and t.get('entry_time')):
        ticker = t.get('ticker', '')
        et = t['entry_time']
        if ticker not in earliest or et < earliest[ticker]['entry_time']:
            earliest[ticker] = {
                'entry_time': et,
                'entry_fmt': t.get('entry_fmt', ''),
                'orig_id': t['id'],
                'timeframe': t.get('timeframe', '?'),
                'conviction': t.get('conviction', 0),
                'sl_pct': t.get('sl_pct'),
                'sl_stage': t.get('sl_stage'),
                'partial_tp1_taken': t.get('partial_tp1_taken'),
                'peak_price': t.get('peak_price'),
                'funding_rate': t.get('funding_rate'),
            }

patched = 0
for t in trades:
    if t.get('status') == 'OPEN' and t.get('id', '').startswith('RECOVERED_'):
        ticker = t.get('ticker', '')
        if ticker in earliest and earliest[ticker]['entry_time'] < t['entry_time']:
            old_et = t['entry_time']
            t['entry_time'] = earliest[ticker]['entry_time']
            t['entry_fmt'] = earliest[ticker]['entry_fmt']
            for fk in ('timeframe', 'conviction', 'sl_pct', 'sl_stage',
                        'partial_tp1_taken', 'peak_price', 'funding_rate'):
                if earliest[ticker].get(fk) is not None:
                    t[fk] = earliest[ticker][fk]
            patched += 1
            efmt = t['entry_fmt']
            oid = earliest[ticker]['orig_id']
            print(f'Patched {ticker}: entry_fmt={efmt} (from {oid})')

if patched:
    with open('/app/trade_log.json', 'w') as f:
        json.dump(trades, f, indent=4)
    print(f'Done: {patched} trades patched')
else:
    print('No trades needed patching')
