# Treasury Diagnostics

Show the current state of the treasury system: balances across all three locations, active proposals, and yield deployed.

## Arguments
Optional: `balances` | `proposals` | `yield` | `all` (default: all)

## Execution

Run via `gcloud compute ssh agent-trader-swarm-vm --zone=europe-west1-b --command='sudo docker exec agent_trader_swarm python3 -c "..."'`

### 1. Balances (`balances` or `all`)
```python
import sys, os, json; sys.path.insert(0, '/app'); os.chdir('/app')
from utils.gcp_secrets import get_all_trading_secrets
for k,v in get_all_trading_secrets().items():
    if v: os.environ[k]=v
from utils.treasury_executor import get_arb_usdc_balance, _TREASURY_WALLET
from utils.exchange_client import HyperliquidExchange
from agents.treasury_agent import TreasuryAgent
ex = HyperliquidExchange(testnet=False)
hl = ex.get_balance()
wallet = get_arb_usdc_balance(_TREASURY_WALLET)
agent = TreasuryAgent()
yield_bals = agent._get_yield_balances()
total_yield = sum(yield_bals.values())
total = hl + total_yield + wallet
print(f"HL balance:       ${hl:.2f}  ({hl/total*100:.1f}%)")
print(f"Treasury wallet:  ${wallet:.2f}")
print(f"--- Yield protocols ---")
for pid, bal in yield_bals.items():
    if bal > 0.01:
        print(f"  {pid}: ${bal:.2f}")
print(f"Total yield:      ${total_yield:.2f}  ({total_yield/total*100:.1f}%)")
print(f"Total portfolio:  ${total:.2f}")
```

### 2. Active proposals (`proposals` or `all`)
```python
import sys, os, json; sys.path.insert(0, '/app'); os.chdir('/app')
with open('/app/treasury_proposals.json') as f: props = json.load(f)
terminal = {'DEPLOYED','FAILED','REJECTED','COMPLETED'}
active = [p for p in props if p.get('status') not in terminal]
print(f"Active proposals: {len(active)}")
for p in active:
    print(f"  {p['id']} | {p['status']} | {p.get('title','')[:60]}")
recent = sorted([p for p in props if p.get('status') in terminal],
                key=lambda x: x.get('created_at',''), reverse=True)[:5]
print(f"\nRecent history ({len(recent)}):")
for p in recent:
    print(f"  {p['id']} | {p['status']} | {p.get('title','')[:60]}")
```

### 3. Yield / allocation (`yield` or `all`)
```python
import sys, os, json; sys.path.insert(0, '/app'); os.chdir('/app')
try:
    with open('/app/treasury_state.json') as f: state = json.load(f)
    alloc = state.get('allocation', {})
    print(f"Total portfolio: ${state.get('total_portfolio', 0):.2f}")
    print(f"Target HL: {alloc.get('effective_trade_pct', 30):.0f}% (${alloc.get('target_trade_usd', 0):.0f})")
    print(f"Reason: {alloc.get('reason', '—')}")
    opps = state.get('opportunities', [])
    print(f"\nTop yield opportunities ({len(opps)} total):")
    for o in opps[:5]:
        print(f"  {o['label']}: {o['apy']:.2f}% APY | auto={o.get('automated')} | {o['chain']}")
    print(f"\nLast updated: {state.get('timestamp','—')[:16]}")
except Exception as e:
    print(f"treasury_state.json not found or empty: {e}")
```

## Output Format

Present results in a structured summary:
- **Portfolio** table: HL | Aave | Wallet | Total (with % breakdown)
- **Proposals**: list active proposals with status + title; flag any stuck > 30 min in BRIDGED
- **Yield**: current best APY, target allocation, reason for current split

Flag anomalies:
- Any yield balance > 0 but no DEPLOYED proposal → proposal file may have been cleared
- Wallet USDC > $100 but no PENDING proposal → treasury agent not running or proposal TTL issue
- BRIDGED proposal > 2h old → deposit likely failed, check logs
- HL pct < (target - 10pp) → rebalance may be needed
- All yield balances = 0 but last treasury run > 2h ago → treasury run() may not be firing (check cycle count; frequent restarts reset cycle_count to 0)
