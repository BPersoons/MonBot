"""
One-time backlog grooming script.

Actions:
  1. Mark COMPLETED: items containing "Score Threshold" or "Execution Pipeline Bottleneck"
  2. Delete all PENDING items except a whitelist of 5 genuine strategic titles
  3. Reset "Latency Optimization" from IN_PROGRESS -> PENDING (stale status)
  4. Mark "Multi-Asset Correlation" and "Backup Data Pipeline" as IN_PROGRESS
  5. Print final summary

Run locally:   python scripts/groom_backlog.py
Run on VM:     sudo docker exec agent_trader_swarm python /app/scripts/groom_backlog.py
"""

import os
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("BacklogGroom")

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

# Titles to preserve from the PENDING delete sweep (exact substring match, case-insensitive)
WHITELIST = [
    "MEV Protection Layer",
    "Latency Optimization",
    "Multi-Asset Correlation",
    "Backup Data Pipeline",
    "Historical Backtest Engine",
]

# PENDING items whose titles contain these keywords -> mark COMPLETED
COMPLETE_KEYWORDS = [
    "Score Threshold",
    "Execution Pipeline Bottleneck",
]


def fetch_all(status: str) -> list:
    items = []
    offset = 0
    batch = 1000
    while True:
        res = (
            client.table("system_backlog")
            .select("id,title,status,priority")
            .eq("status", status)
            .order("id")
            .range(offset, offset + batch - 1)
            .execute()
        )
        if not res.data:
            break
        items.extend(res.data)
        if len(res.data) < batch:
            break
        offset += batch
    return items


def title_in_whitelist(title: str) -> bool:
    t = title.lower()
    return any(w.lower() in t for w in WHITELIST)


def title_matches_complete(title: str) -> bool:
    t = title.lower()
    return any(kw.lower() in t for kw in COMPLETE_KEYWORDS)


def run():
    # ── 1. Collect PENDING items ──────────────────────────────────────────────
    logger.info("Loading all PENDING backlog items...")
    pending = fetch_all("PENDING")
    logger.info(f"Total PENDING: {len(pending)}")

    to_complete_ids = []
    to_delete_ids = []

    for item in pending:
        item_id = item["id"]
        title = item.get("title", "")
        if title_matches_complete(title):
            to_complete_ids.append(item_id)
        elif not title_in_whitelist(title):
            to_delete_ids.append(item_id)

    logger.info(f"PENDING -> COMPLETED : {len(to_complete_ids)}")
    logger.info(f"PENDING -> DELETE    : {len(to_delete_ids)}")
    logger.info(f"PENDING -> keep      : {len(pending) - len(to_complete_ids) - len(to_delete_ids)}")

    # ── 2. Find IN_PROGRESS items to reset / promote ──────────────────────────
    logger.info("\nLoading IN_PROGRESS backlog items...")
    in_progress = fetch_all("IN_PROGRESS")
    logger.info(f"Total IN_PROGRESS: {len(in_progress)}")

    latency_ids = [i["id"] for i in in_progress if "latency optimization" in i.get("title", "").lower()]
    logger.info(f"IN_PROGRESS -> PENDING (Latency Optimization): {len(latency_ids)}")

    # ── 3. Confirm ────────────────────────────────────────────────────────────
    print(f"""
Summary of planned changes:
  Delete {len(to_delete_ids)} noise PENDING items
  Mark   {len(to_complete_ids)} PENDING items as COMPLETED (Score Threshold / Execution Pipeline Bottleneck)
  Reset  {len(latency_ids)} IN_PROGRESS item(s) -> PENDING (Latency Optimization)
  Mark   "Multi-Asset Correlation" and "Backup Data Pipeline" -> IN_PROGRESS (from PENDING whitelist)
""")
    confirm = input("Type 'yes' to proceed: ").strip().lower()
    if confirm != "yes":
        logger.info("Aborted.")
        return

    # ── 4. Delete noise items in batches of 100 ───────────────────────────────
    deleted = 0
    for i in range(0, len(to_delete_ids), 100):
        batch_ids = to_delete_ids[i : i + 100]
        try:
            client.table("system_backlog").delete().in_("id", batch_ids).execute()
            deleted += len(batch_ids)
            logger.info(f"Deleted {deleted}/{len(to_delete_ids)}...")
        except Exception as e:
            logger.error(f"Delete batch failed: {e}")

    # ── 5. Mark resolved items COMPLETED ─────────────────────────────────────
    for item_id in to_complete_ids:
        try:
            client.table("system_backlog").update({"status": "COMPLETED"}).eq("id", item_id).execute()
            logger.info(f"Marked COMPLETED: ID={item_id}")
        except Exception as e:
            logger.error(f"Failed to complete ID={item_id}: {e}")

    # ── 6. Reset Latency Optimization to PENDING ──────────────────────────────
    for item_id in latency_ids:
        try:
            client.table("system_backlog").update({"status": "PENDING"}).eq("id", item_id).execute()
            logger.info(f"Reset to PENDING: ID={item_id} (Latency Optimization)")
        except Exception as e:
            logger.error(f"Failed to reset ID={item_id}: {e}")

    # ── 7. Mark pickup items IN_PROGRESS ─────────────────────────────────────
    pickup_keywords = ["multi-asset correlation", "backup data pipeline"]
    for item in pending:
        title = item.get("title", "").lower()
        if any(kw in title for kw in pickup_keywords):
            try:
                client.table("system_backlog").update({"status": "IN_PROGRESS"}).eq("id", item["id"]).execute()
                logger.info(f"Marked IN_PROGRESS: ID={item['id']} — {item['title']}")
            except Exception as e:
                logger.error(f"Failed to update ID={item['id']}: {e}")

    # ── 8. Final summary ──────────────────────────────────────────────────────
    logger.info("\n--- Final backlog state ---")
    remaining = (
        client.table("system_backlog")
        .select("id,priority,title,status")
        .order("priority", desc=True)
        .limit(30)
        .execute()
    )
    for r in remaining.data:
        print(f"  ID={r['id']} P{r.get('priority', 0)} [{r.get('status')}] {r.get('title', '?')}")


if __name__ == "__main__":
    run()
