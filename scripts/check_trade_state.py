"""Check current trade_log state vs HL positions."""
import json, time

trades = json.load(open('/app/trade_log.json'))
open_trades = [t for t in trades if t.get('status') in ('OPEN', 'PLACED')]
print(f"OPEN trades in trade_log: {len(open_trades)}")
for t in open_trades:
    ticker = t.get('ticker', '?')
    tid = t.get('id', '?')[:35]
    print(f"  {ticker:25s} id={tid}")

print()
closed_recent = [t for t in trades
                 if t.get('status') == 'CLOSED'
                 and str(t.get('exit_time', '')) > '2026-04-09T14:00']
print(f"Recently CLOSED (after 14:00 UTC): {len(closed_recent)}")
for t in closed_recent:
    ticker = t.get('ticker', '?')
    reason = t.get('close_reason', '?')
    exit_t = str(t.get('exit_time', '?'))[:19]
    print(f"  {ticker:25s} reason={reason:30s} exit={exit_t}")
