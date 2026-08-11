# Live Diagnostics

Run diagnostic checks on the live production container and report results.

## Arguments
$ARGUMENTS — optional: specific diagnostic to run (e.g. `margin`, `positions`, `kelly`, `balance`, `all`). Default: `all`.

## Execution

Run diagnostics via `gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker exec agent_trader_swarm python -c "..."'`

For complex scripts, use the existing diagnostic scripts in `/app/scripts/diag_*.py` if available, or write inline Python.

### Diagnostics to run (for `all` or individually):

#### 1. Balance (`balance`)
```python
import sys, os; sys.path.insert(0, '/app')
from utils.gcp_secrets import get_all_trading_secrets
for k,v in get_all_trading_secrets().items():
    if v: os.environ[k]=v
from utils.exchange_client import HyperliquidExchange
ex = HyperliquidExchange(testnet=False)
print(f"get_balance(): ${ex.get_balance():.2f}")
print(f"get_free_margin(): ${ex.get_free_margin():.2f}")
```

#### 2. Margin state (`margin`)
Run `/app/scripts/diag_margin.py` — shows accountValue, totalMarginUsed, totalNtlPos, withdrawable, free margin.

#### 3. Open positions (`positions`)
Run `/app/scripts/diag_positions_check.py` — shows HL positions, trade_log open trades, balance, portfolio peak.

#### 4. Kelly sizing (`kelly`)
Run `/app/scripts/diag_risk_sizing.py` — shows get_balance, get_free_margin, Kelly result with live bankroll.

#### 5. Drawdown (`drawdown`)
```python
import json
with open('portfolio_peak.json') as f: peak = json.load(f)
print(f"peak_equity: ${peak.get('peak_equity', 0):.2f}")
# Calculate current drawdown
import sys, os; sys.path.insert(0, '/app')
from utils.gcp_secrets import get_all_trading_secrets
for k,v in get_all_trading_secrets().items():
    if v: os.environ[k]=v
from utils.exchange_client import HyperliquidExchange
ex = HyperliquidExchange(testnet=False)
bal = ex.get_balance()
dd = (peak.get('peak_equity', bal) - bal) / peak.get('peak_equity', bal) * 100 if peak.get('peak_equity', 0) > 0 else 0
print(f"current_equity: ${bal:.2f}")
print(f"drawdown: {dd:.1f}% (limit: 15%)")
```

## Output format

Present results in a structured summary table. Flag any anomalies:
- get_free_margin = 0 when balance > 0 → likely all margin in use
- Drawdown > 10% → warn approaching limit
- Open positions in trade_log but not on HL → sync issue
- Peak equity significantly above current balance → may need reset
