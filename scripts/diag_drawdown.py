"""Drawdown + capital audit diagnostic."""
import sys, os, json, datetime
sys.path.insert(0, "/app")

from utils.gcp_secrets import get_all_trading_secrets
for k, v in get_all_trading_secrets().items():
    if v:
        os.environ[k] = v

# ── Peak file ─────────────────────────────────────────────────────────────────
try:
    with open("portfolio_peak.json") as f:
        peak_data = json.load(f)
    peak_eq = peak_data.get("peak_equity", 0)
    ts = peak_data.get("updated_at", 0)
    peak_dt = datetime.datetime.utcfromtimestamp(ts).isoformat() if ts else "unknown"
    print(f"Peak equity:    ${peak_eq:.2f}  (last updated: {peak_dt})")
except Exception as e:
    print(f"Peak file error: {e}")
    peak_eq = 0

# ── Circuit breaker ───────────────────────────────────────────────────────────
try:
    with open("cb_state.json") as f:
        cb = json.load(f)
    print(f"CircuitBreaker: paused={cb.get('paused')}, reason={cb.get('reason', 'none')}")
except Exception:
    print("CircuitBreaker: not paused (no cb_state.json)")

# ── Live balance ──────────────────────────────────────────────────────────────
from utils.exchange_client import HyperliquidExchange
ex = HyperliquidExchange(testnet=False)
bal = ex.get_balance()
free = ex.get_free_margin()
print(f"HL balance:     ${bal:.2f}")
print(f"Free margin:    ${free:.2f}")

# ── Yield balances ────────────────────────────────────────────────────────────
try:
    from utils.treasury_executor import get_total_yield_balance, _TREASURY_WALLET
    yield_bal = get_total_yield_balance(_TREASURY_WALLET)
    print(f"Yield deployed: ${yield_bal:.2f}")
    total_portfolio = bal + yield_bal
except Exception as e:
    yield_bal = 0
    total_portfolio = bal
    print(f"Yield deployed: $0.00 (fetch failed: {e})")

print(f"Total portfolio:${total_portfolio:.2f}")

# ── Drawdown ──────────────────────────────────────────────────────────────────
if peak_eq > 0:
    dd = (peak_eq - total_portfolio) / peak_eq * 100
    print(f"Drawdown:       {dd:.1f}% (limit: 15%)")
    print(f"Trades blocked: {dd >= 15.0}")

# ── Trade log P&L audit ───────────────────────────────────────────────────────
print("\n── Trade P&L audit ──────────────────────────────────────────────────────")
try:
    with open("trade_log.json") as f:
        raw = json.load(f)
    trades = list(raw.values()) if isinstance(raw, dict) else raw
    closed = [
        t for t in trades
        if t.get("status") == "CLOSED"
        and t.get("pnl") is not None
        and not str(t.get("id", "")).startswith("RECOVERED_")
        and not t.get("harvest")
    ]
    open_trades = [t for t in trades if t.get("status") == "OPEN" and not t.get("harvest")]

    total_pnl   = sum(t.get("pnl", 0) or 0 for t in closed)
    total_fees  = sum(t.get("fee", 0) or 0 for t in closed)
    wins        = [t for t in closed if (t.get("pnl") or 0) > 0]
    losses      = [t for t in closed if (t.get("pnl") or 0) <= 0]
    wr          = len(wins) / len(closed) * 100 if closed else 0

    print(f"Closed trades:  {len(closed)}  ({len(wins)} wins / {len(losses)} losses, WR={wr:.1f}%)")
    print(f"Total realized P&L: ${total_pnl:+.2f}")
    print(f"Total fees paid:    ${total_fees:.2f}")
    print(f"Net after fees:     ${total_pnl - total_fees:+.2f}")
    print(f"Open trades:    {len(open_trades)}")

    # Biggest wins/losses
    if closed:
        best  = max(closed, key=lambda t: t.get("pnl") or 0)
        worst = min(closed, key=lambda t: t.get("pnl") or 0)
        print(f"Best trade:     ${best.get('pnl', 0):+.2f} ({best.get('ticker','?')} {best.get('exit_time','')[:10]})")
        print(f"Worst trade:    ${worst.get('pnl', 0):+.2f} ({worst.get('ticker','?')} {worst.get('exit_time','')[:10]})")

    # Implied starting capital
    implied_start = total_portfolio - total_pnl + total_fees
    print(f"\nImplied starting capital: ${implied_start:.2f}")
    print(f"  (current ${total_portfolio:.2f} - realized P&L ${total_pnl:+.2f} + fees ${total_fees:.2f})")

except Exception as e:
    print(f"Trade log error: {e}")
