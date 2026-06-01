"""Live trade activity diagnostics — why no trades?"""
import json, os, sys
sys.path.insert(0, '/app')

# Circuit breaker
from core.circuit_breaker import CircuitBreaker
cb = CircuitBreaker()
print(f"CircuitBreaker.can_trade(): {cb.can_trade()}")
try:
    print(f"CB state: {cb._state}")
except:
    print(f"CB attrs: {[a for a in dir(cb) if not a.startswith('__')]}")

# Auto params
with open('/app/config/auto_params.json') as f:
    ap = json.load(f)
print(f"score_threshold:    {ap['score_threshold']}")
print(f"tech_prefilter_min: {ap['tech_prefilter_min']}")
meta = ap.get('_meta', {})
print(f"_meta.last_changed_by: {meta.get('last_changed_by', '-')}")
print(f"_meta.change_reason:   {meta.get('change_reason', '-')}")

# Trade log
with open('/app/trade_log.json') as f:
    trades = json.load(f)
open_t = [t for t in trades if t.get('status') == 'OPEN' and not t.get('harvest')]
closed_t = [t for t in trades if t.get('status') == 'CLOSED' and not t.get('harvest')]
print(f"\nTrade log: {len(trades)} total, {len(open_t)} OPEN, {len(closed_t)} CLOSED")
if open_t:
    for t in open_t:
        print(f"  OPEN: {t.get('ticker')} {t.get('direction')} entry={t.get('entry_price')} qty={t.get('quantity')}")

# Peak equity + drawdown
try:
    with open('/app/portfolio_peak.json') as f:
        peak = json.load(f)
    from utils.gcp_secrets import get_all_trading_secrets
    for k, v in get_all_trading_secrets().items():
        if v:
            os.environ[k] = v
    from utils.exchange_client import HyperliquidExchange
    ex = HyperliquidExchange(testnet=False)
    bal = ex.get_balance()
    pk = peak.get('peak_equity', bal)
    dd = (pk - bal) / pk * 100 if pk > 0 else 0
    print(f"\npeak_equity:    ${pk:.2f}")
    print(f"current_equity: ${bal:.2f}")
    print(f"drawdown:       {dd:.1f}%  (hard limit 15%)")
except Exception as e:
    print(f"Drawdown check failed: {e}")

# Dashboard
try:
    with open('/app/dashboard.json') as f:
        dash = json.load(f)
    print(f"\ncycle_count:  {dash.get('cycle_count', '?')}")
    print(f"last_update:  {dash.get('last_update', '?')}")
    print(f"status:       {dash.get('status', '?')}")
except Exception as e:
    print(f"Dashboard: {e}")

# Decision history — last 5 decisions
try:
    with open('/app/decision_history.json') as f:
        hist = json.load(f)
    print(f"\nLast 5 decisions:")
    for d in hist[-5:]:
        ts = d.get('timestamp', '')[:16]
        ticker = d.get('ticker', '?')
        step = d.get('next_step', d.get('decision', '?'))
        score = d.get('combined_score', d.get('score', '?'))
        print(f"  {ts}  {ticker:<18} {step:<15} score={score}")
except Exception as e:
    print(f"Decision history: {e}")

# pl_status
try:
    with open('/app/pl_status.json') as f:
        pl = json.load(f)
    print(f"\nAgent pulses:")
    for a in pl[:4]:
        print(f"  {a.get('agent_name','?'):<20} {a.get('status','?'):<10} last={a.get('last_pulse','?')[:19]}")
except Exception as e:
    print(f"pl_status: {e}")
