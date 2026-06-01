import json

with open('/app/dashboard.json') as f:
    dash = json.load(f)
print('cycle_count:', dash.get('cycle_count', '?'))
print('last_update:', dash.get('last_update', '?'))
print('status:', dash.get('status', '?'))

with open('/app/config/auto_params.json') as f:
    ap = json.load(f)
print('score_threshold:', ap['score_threshold'])
print('tech_prefilter_min:', ap['tech_prefilter_min'])

with open('/app/trade_log.json') as f:
    trades = json.load(f)
open_t = [t for t in trades if t.get('status') == 'OPEN' and not t.get('harvest')]
print('open trades:', len(open_t))

with open('/app/decision_history.json') as f:
    hist = json.load(f)
recent = hist[-25:]
print('total decisions:', len(hist))
print('Last 25 decisions:')
above_threshold = []
for d in recent:
    ts = d.get('timestamp', '')[:16]
    ticker = d.get('ticker', '?')
    step = d.get('next_step', d.get('decision', '?'))
    score = round(d.get('combined_score', d.get('score', 0)), 3)
    direction = d.get('direction', '')
    flag = ' <-- ABOVE THRESHOLD' if abs(score) >= 0.20 else ''
    print('  {}  {:<22} {:<15} score={:>6}  {}{}'.format(ts, ticker, step, score, direction, flag))
    if abs(score) >= 0.20:
        above_threshold.append((ticker, score, step))

print()
print('Scores >= 0.20 (would pass threshold):', len(above_threshold))
for t, s, st in above_threshold:
    print('  {} score={} step={}'.format(t, s, st))

# Score distribution
all_scores = [abs(d.get('combined_score', d.get('score', 0))) for d in hist[-100:]]
if all_scores:
    buckets = {'<0.05': 0, '0.05-0.10': 0, '0.10-0.15': 0, '0.15-0.20': 0, '>=0.20': 0}
    for s in all_scores:
        if s < 0.05: buckets['<0.05'] += 1
        elif s < 0.10: buckets['0.05-0.10'] += 1
        elif s < 0.15: buckets['0.10-0.15'] += 1
        elif s < 0.20: buckets['0.15-0.20'] += 1
        else: buckets['>=0.20'] += 1
    print()
    print('Score distribution (last 100 decisions, absolute value):')
    for k, v in buckets.items():
        bar = '#' * v
        print('  {}:  {} ({})'.format(k, bar, v))
