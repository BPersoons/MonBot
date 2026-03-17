"""
One-time cleanup script for system_backlog and swarm_health tables.

Actions:
1. Mark idea #93 as COMPLETED (agents are embedded in ProjectLead)
2. Delete ghost swarm_health entries (Judge, ExecutionAgent, RiskManager, CPO)
3. Deduplicate PENDING backlog items by title similarity
"""

import logging
import os
from collections import defaultdict
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Load .env.adk explicitly for local scripts
load_dotenv(".env.adk")

from utils.db_client import DatabaseClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("BacklogCleanup")


def similarity(a: str, b: str) -> float:
    """Return similarity ratio between two strings (0-1)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def mark_idea_93_completed(db: DatabaseClient):
    """Step 1: Mark idea #93 as COMPLETED."""
    logger.info("=== Step 1: Mark idea #93 as COMPLETED ===")
    try:
        result = db.client.table("system_backlog").update({
            "status": "COMPLETED",
            "description": (
                "[RESOLVED] Architecture evolved - Judge agent removed, "
                "ExecutionAgent and RiskManager are embedded in ProjectLead. "
                "Original idea is outdated."
            )
        }).eq("id", 93).execute()

        if result.data:
            logger.info("Idea #93 marked as COMPLETED.")
        else:
            logger.warning("Idea #93 not found or already updated.")
    except Exception as e:
        logger.error(f"Error updating idea #93: {e}")


def clean_ghost_health_entries(db: DatabaseClient):
    """Step 2: Delete ghost/duplicate swarm_health entries."""
    logger.info("=== Step 2: Clean ghost swarm_health entries ===")
    ghost_names = ["Judge", "ExecutionAgent", "RiskManager", "CPO"]

    for name in ghost_names:
        try:
            result = db.client.table("swarm_health").delete().eq("agent_name", name).execute()
            if result.data:
                logger.info(f"Deleted ghost entry: {name}")
            else:
                logger.info(f"No entry found for: {name} (already clean)")
        except Exception as e:
            logger.error(f"Error deleting {name}: {e}")


def deduplicate_backlog(db: DatabaseClient):
    """Step 3: Deduplicate PENDING backlog items by title similarity."""
    logger.info("=== Step 3: Deduplicate PENDING backlog items ===")
    try:
        result = db.client.table("system_backlog").select("*").eq(
            "status", "PENDING"
        ).execute()
        items = result.data or []
        logger.info(f"Found {len(items)} PENDING items.")
    except Exception as e:
        logger.error(f"Error fetching backlog: {e}")
        return

    if not items:
        return

    # Group similar items together using title similarity
    SIMILARITY_THRESHOLD = 0.70
    groups = []  # list of lists of items
    assigned = set()

    # Sort by priority DESC so the highest-priority item is first in each group
    items.sort(key=lambda x: x.get("priority", 0) or 0, reverse=True)

    for i, item in enumerate(items):
        if item["id"] in assigned:
            continue

        group = [item]
        assigned.add(item["id"])
        title_i = item.get("title", "") or ""

        for j in range(i + 1, len(items)):
            other = items[j]
            if other["id"] in assigned:
                continue
            title_j = other.get("title", "") or ""
            if similarity(title_i, title_j) >= SIMILARITY_THRESHOLD:
                group.append(other)
                assigned.add(other["id"])

        if len(group) > 1:
            groups.append(group)

    # Mark duplicates (all except the first/highest-priority in each group)
    total_deduped = 0
    for group in groups:
        keeper = group[0]
        duplicates = group[1:]
        logger.info(
            f"Keeping #{keeper['id']} \"{keeper.get('title', '')[:60]}\" "
            f"(priority={keeper.get('priority', '?')}), "
            f"marking {len(duplicates)} duplicates as DEFERRED"
        )

        for dup in duplicates:
            try:
                db.client.table("system_backlog").update({
                    "status": "DEFERRED",
                    "description": (
                        f"[Deduplicated] Duplicate of #{keeper['id']}. "
                        f"Original: {dup.get('description', '')[:200]}"
                    )
                }).eq("id", dup["id"]).execute()
                total_deduped += 1
            except Exception as e:
                logger.error(f"Error deferring #{dup['id']}: {e}")

    logger.info(f"Deduplication complete: {total_deduped} items marked as DEFERRED.")
    logger.info(f"Duplicate groups found: {len(groups)}")


def main():
    db = DatabaseClient()
    if not db.is_available():
        logger.error("Database unavailable. Aborting.")
        return

    mark_idea_93_completed(db)
    clean_ghost_health_entries(db)
    deduplicate_backlog(db)

    # Final summary
    try:
        pending = db.client.table("system_backlog").select(
            "id", count="exact"
        ).eq("status", "PENDING").execute()
        logger.info(f"Remaining PENDING items: {pending.count}")
    except Exception as e:
        logger.info(f"Could not get final count: {e}")

    logger.info("=== Cleanup complete! ===")


if __name__ == "__main__":
    main()
