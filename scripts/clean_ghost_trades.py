"""Remove RECOVERED_ ghost records from trade_log.json with backup."""
import json, shutil, os
from datetime import datetime

src = "trade_log.json"
bak = f"trade_log.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

shutil.copy(src, bak)
print(f"Backup saved: {bak}")

with open(src) as f:
    trades = json.load(f)

before = len(trades)
clean = [t for t in trades if not t.get("id", "").startswith("RECOVERED_")]
removed = before - len(clean)

with open(src, "w") as f:
    json.dump(clean, f, indent=2)

print(f"Removed {removed} RECOVERED_ records. {len(clean)} trades remaining.")
