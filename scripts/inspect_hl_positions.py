"""Print raw HL positions to see what contracts values we get."""
import sys
sys.path.insert(0, '/app')
from utils.exchange_client import HyperliquidExchange
hl = HyperliquidExchange()
positions = hl.fetch_all_positions()
for p in positions:
    if float(p.get('contracts') or 0) == 0:
        continue
    sym = p.get('symbol')
    contracts = p.get('contracts')
    contractSize = p.get('contractSize')
    entry = p.get('entryPrice')
    notional = p.get('notional')
    side = p.get('side')
    szi = (p.get('info') or {}).get('szi')
    print(f"{sym:20s} side={side:5s} contracts={contracts} contractSize={contractSize} entry={entry} notional={notional} szi={szi}")
