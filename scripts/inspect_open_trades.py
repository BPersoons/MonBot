"""Inspect open trades: qty, entry, partial_exits, trade_value."""
import json
trades = json.load(open('/app/trade_log.json'))
open_ts = [t for t in trades if t.get('status') in ('OPEN', 'PLACED')]
for t in open_ts:
    tkr = t.get('ticker', '?')
    qty = t.get('quantity', 0)
    entry = t.get('entry_price', 0)
    tv = t.get('trade_value', None)
    ptt = t.get('partial_tp1_taken', False)
    pex = t.get('partial_exits', [])
    realized = sum((p.get('pnl') or 0) for p in pex)
    print(f"{tkr:22s} qty={qty:>12.6f} entry=${entry:>10.4f} "
          f"notional=${entry*qty:>8.2f} tv={tv} "
          f"partial={ptt} realized=${realized:.2f} exits={len(pex)}")
    for p in pex:
        print(f"   partial: frac={p.get('fraction')} qty={p.get('qty')} "
              f"exit=${p.get('exit_price')} pnl=${p.get('pnl'):.2f} "
              f"reason={p.get('reason')} skipped={p.get('skipped', False)}")
