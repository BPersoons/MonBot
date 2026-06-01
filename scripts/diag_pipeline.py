import json
from collections import Counter

with open('/app/decision_history.json') as f:
    hist = json.load(f)

# Step distribution
steps = Counter(d.get('next_step', d.get('decision', '?')) for d in hist)
print('Decision step distribution (all 2000):')
for step, count in steps.most_common():
    print('  {:<20} {}'.format(step, count))

# Any BUILD_CASE or EXECUTE?
builds = [d for d in hist if d.get('next_step') in ('BUILD_CASE', 'EXECUTE', 'EXECUTE_NOW')]
print()
print('BUILD_CASE / EXECUTE decisions:', len(builds))
for d in builds[-10:]:
    print('  {} {} score={} dir={}'.format(
        d.get('timestamp','')[:16], d.get('ticker',''),
        round(d.get('combined_score', 0), 3), d.get('direction','')))

# High scores that went to MONITOR instead of advancing
monitors_high = [d for d in hist if d.get('next_step') == 'MONITOR'
                 and abs(d.get('combined_score', 0)) >= 0.18]
print()
print('MONITOR decisions with score >= 0.18 (were close but held back):')
for d in monitors_high[-15:]:
    print('  {} {:<22} score={:>6} dir={}'.format(
        d.get('timestamp','')[:16], d.get('ticker',''),
        round(d.get('combined_score', 0), 3), d.get('direction','')))

# Score trend: avg score by hour bucket
from datetime import datetime
hourly = {}
for d in hist:
    try:
        ts = d.get('timestamp','')[:13]
        score = abs(d.get('combined_score', d.get('score', 0)))
        if ts not in hourly:
            hourly[ts] = []
        hourly[ts].append(score)
    except: pass

print()
print('Avg abs score per hour (last 20h):')
for hour in sorted(hourly.keys())[-20:]:
    scores = hourly[hour]
    avg = sum(scores)/len(scores)
    n = len(scores)
    bar = '#' * int(avg * 100)
    print('  {}  avg={:.3f}  n={}  {}'.format(hour, avg, n, bar))

# Check circuit breaker state
import sys; sys.path.insert(0, '/app')
from core.circuit_breaker import CircuitBreaker
cb = CircuitBreaker()
print()
print('CircuitBreaker.can_trade():', cb.can_trade())
try:
    state = cb._read_state()
    print('CB state:', state)
except Exception as e:
    print('CB state error:', e)
