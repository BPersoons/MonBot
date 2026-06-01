"""Dump raw HL positions to stdout, using gcp secret loader."""
import sys
sys.path.insert(0, '/app')
import os
from utils.gcp_secrets import get_all_trading_secrets
secrets = get_all_trading_secrets()
for k, v in secrets.items():
    if v:
        os.environ[k] = v
from utils.exchange_client import HyperliquidExchange
hl = HyperliquidExchange()
positions = hl.fetch_all_positions()
for p in positions:
    if float(p.get('contracts') or 0) == 0:
        continue
    sym = p.get('symbol')
    contracts = p.get('contracts')
    contract_size = p.get('contractSize')
    entry = p.get('entryPrice')
    notional = p.get('notional')
    side = p.get('side')
    info = p.get('info') or {}
    szi = info.get('szi')
    print(f"{sym:22s} side={side:5s} contracts={contracts} contractSize={contract_size} entry={entry} notional={notional} szi={szi}")
