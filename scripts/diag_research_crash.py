"""Reproduce the ResearchAgent crash with full traceback."""
import sys, os, traceback, logging
sys.path.insert(0, '/app')
logging.basicConfig(level=logging.WARNING)

# Minimal setup to run research cycle
try:
    from agents.project_lead import ProjectLead
    # Use real ProjectLead init to get all dependencies
    pl = ProjectLead()
    print("ProjectLead initialized OK")
    result = pl.run_research_cycle(cycle_count=1, monitored_tickers=[])
    print(f"Proposals: {len(result.get('proposals', []))}")
    for p in result.get('proposals', []):
        print(f"  -> {p.get('ticker')} {p.get('direction')} {p.get('reason','')[:60]}")
except Exception as e:
    print(f"\nCRASH: {type(e).__name__}: {e}")
    traceback.print_exc()
