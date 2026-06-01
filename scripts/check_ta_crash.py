import json

print("=== DECISION HISTORY (last 15) ===")
try:
    history = json.load(open("decision_history.json"))
    for d in history[-15:]:
        bs = d.get("breakdown", {})
        print(f"  {d.get('time','')} {d.get('ticker','?'):20s} score={d.get('score','?'):.3f} next={d.get('next_step','?'):12s} tech={bs.get('tech','?')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== PIPELINE EVENTS (last 5 errors) ===")
try:
    events = json.load(open("pipeline_events.json"))
    errors = [e for e in events if "error" in str(e.get("data",{})).lower() or e.get("event_type") == "ERROR"]
    for e in errors[-5:]:
        print(f"  {e.get('timestamp','')} {e.get('ticker','')} {e.get('event_type','')} {str(e.get('data',{}))[:100]}")
except Exception as e:
    print(f"  ERROR: {e}")
