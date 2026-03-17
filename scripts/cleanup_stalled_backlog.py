"""
Cleanup script: bulk-delete duplicate backlog items created by CPO about the stalled pipeline.

Keeps:
  - Items with unique topics (MEV, Latency, etc.)
  - The two P10 umbrella items (ID 1539, 1414) — marks them COMPLETED

Deletes all PENDING items whose titles match known duplicate patterns.

Run via VM: sudo docker exec agent_trader_swarm python /app/scripts/cleanup_stalled_backlog.py
Or locally: python scripts/cleanup_stalled_backlog.py
"""

import os
import re
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("BacklogCleanup")

# ── Load env ──────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(".env.adk")
except ImportError:
    pass

try:
    from supabase import create_client
except ImportError:
    logger.error("supabase-py not installed. Run: pip install supabase")
    sys.exit(1)

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
if not url or not key:
    logger.error("SUPABASE_URL / SUPABASE_KEY not set.")
    sys.exit(1)

client = create_client(url, key)

# ── Duplicate patterns — any PENDING item whose title matches is deleted ──────
DUPLICATE_PATTERNS = [
    # ProjectLead / buy conversion
    r"projectlead.*buy",
    r"projectlead.*decision",
    r"projectlead.*conversion",
    r"projectlead.*buys",
    r"diagnose.*projectlead",
    r"analyze.*projectlead",
    r"unblock.*projectlead",
    r"optimize.*projectlead",
    r"review.*projectlead",
    r"tune.*projectlead",
    r"rectif.*projectlead",
    r"resolve.*projectlead",
    # Risk Manager
    r"risk manager.*activ",
    r"risk manager.*initializ",
    r"risk manager.*inactiv",
    r"risk manager.*reactiv",
    r"risk manager.*startup",
    r"risk manager.*idle",
    r"risk manager.*critical",
    r"risk manager.*boot",
    r"activate.*risk manager",
    r"initializ.*risk manager",
    r"reactivat.*risk manager",
    r"operationaliz.*risk manager",
    # Scout
    r"scout.*scan",
    r"scout.*ticker",
    r"scout.*inactiv",
    r"scout.*idle",
    r"scout.*zero",
    r"scout.*discrepanc",
    r"scout.*scanning",
    r"reactivat.*scout",
    r"investigat.*scout",
    r"rectif.*scout",
    r"debug.*scout",
    # Auditor
    r"auditor.*reactiv",
    r"auditor.*stall",
    r"auditor.*revit",
    r"auditor.*inactiv",
    r"auditor.*dormant",
    r"auditor.*idle",
    r"reactivat.*auditor",
    r"investigat.*auditor",
    r"restore.*auditor",
    r"reviv.*auditor",
    # Narrator
    r"narrator.*activ",
    r"narrator.*initializ",
    r"initializ.*narrator",
    r"activate.*narrator",
    # Execution Agent
    r"execution agent.*stall",
    r"execution agent.*reactiv",
    r"execution agent.*idle",
    r"reactivat.*execution",
    r"diagnose.*execution",
    r"investigat.*execution",
    # Heartbeat
    r"heartbeat.*cycle.*progress",
    r"root cause.*heartbeat",
    # Generic pipeline stall (but not the P10 umbrella item by ID)
    r"trading pipeline.*stall",
    r"pipeline.*bottleneck",
    r"pipeline.*stall",
    r"stalled.*pipeline",
    r"pipeline.*handoff",
    r"system.*health.*check.*coordinated",
    r"full system.*inter-agent",
    r"system.*trading.*halt",
    r"core agent.*stale.*pulse",
    r"core.*support.*agent",
    r"zero.*buy",
    r"0 buys",
    r"buys=0",
]

COMPILED = [re.compile(p, re.IGNORECASE) for p in DUPLICATE_PATTERNS]

# Items to preserve regardless (mark COMPLETED instead of delete)
UMBRELLA_IDS = {1539, 1414}

def matches_duplicate(title: str) -> bool:
    for pattern in COMPILED:
        if pattern.search(title):
            return True
    return False

def run():
    logger.info("Loading all PENDING backlog items...")

    # Fetch in batches (Supabase default limit is 1000)
    all_items = []
    offset = 0
    batch = 1000
    while True:
        res = client.table("system_backlog") \
            .select("id,title,status,priority") \
            .eq("status", "PENDING") \
            .order("id") \
            .range(offset, offset + batch - 1) \
            .execute()
        if not res.data:
            break
        all_items.extend(res.data)
        if len(res.data) < batch:
            break
        offset += batch

    logger.info(f"Total PENDING items: {len(all_items)}")

    to_delete = []
    to_complete = []

    for item in all_items:
        item_id = item["id"]
        title = item.get("title", "")

        if item_id in UMBRELLA_IDS:
            to_complete.append(item_id)
        elif matches_duplicate(title):
            to_delete.append(item_id)

    logger.info(f"Items to DELETE: {len(to_delete)}")
    logger.info(f"Items to mark COMPLETED: {len(to_complete)}")

    if not to_delete and not to_complete:
        logger.info("Nothing to clean up.")
        return

    # Confirm
    print(f"\nAbout to DELETE {len(to_delete)} duplicate items and COMPLETE {len(to_complete)} umbrella items.")
    confirm = input("Type 'yes' to proceed: ").strip().lower()
    if confirm != "yes":
        logger.info("Aborted.")
        return

    # Delete in batches of 100
    deleted = 0
    for i in range(0, len(to_delete), 100):
        batch_ids = to_delete[i:i + 100]
        try:
            client.table("system_backlog").delete().in_("id", batch_ids).execute()
            deleted += len(batch_ids)
            logger.info(f"Deleted {deleted}/{len(to_delete)}...")
        except Exception as e:
            logger.error(f"Delete batch failed: {e}")

    # Mark umbrella items as COMPLETED
    for item_id in to_complete:
        try:
            client.table("system_backlog").update({"status": "COMPLETED"}).eq("id", item_id).execute()
            logger.info(f"Marked ID={item_id} as COMPLETED")
        except Exception as e:
            logger.error(f"Failed to complete ID={item_id}: {e}")

    logger.info(f"\nDone. Deleted={deleted}, Completed={len(to_complete)}")

    # Show what remains
    remaining = client.table("system_backlog").select("id,priority,title,status") \
        .order("priority", desc=True).limit(20).execute()
    logger.info("\nRemaining top backlog items:")
    for r in remaining.data:
        print(f"  ID={r['id']} P{r.get('priority',0)} [{r.get('status')}] {r.get('title','?')}")

if __name__ == "__main__":
    run()
