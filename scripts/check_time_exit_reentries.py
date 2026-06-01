"""Check for TIME_EXIT closures followed by re-entries on same ticker."""
import json
from collections import defaultdict

trades = json.load(open('/app/trade_log.json'))
by_ticker = defaultdict(list)
for t in trades:
    by_ticker[t.get('ticker', '?')].append(t)

for tkr, ts in by_ticker.items():
    ts_sorted = sorted(ts, key=lambda x: x.get('entry_time', 0) or 0)
    for i, t in enumerate(ts_sorted):
        reason = t.get('close_reason', '') or ''
        if not reason.startswith('TIME_EXIT'):
            continue
        exit_str = str(t.get('exit_time', ''))[:19]
        entry_str = str(t.get('entry_fmt', ''))[:19]
        # find next trade with later entry
        follow = None
        for t2 in ts_sorted[i+1:]:
            if (t2.get('entry_time', 0) or 0) > (t.get('entry_time', 0) or 0):
                follow = t2
                break
        if follow:
            fstatus = follow.get('status', '?')
            fentry = str(follow.get('entry_fmt', ''))[:19]
            freason = follow.get('close_reason', '-')
            print(f"{tkr:22s} | closed {reason} @ {exit_str} (entered {entry_str})")
            print(f"{'':22s} -> re-entered @ {fentry} status={fstatus} close={freason}")
        else:
            print(f"{tkr:22s} | closed {reason} @ {exit_str} (entered {entry_str}) -> no re-entry")
