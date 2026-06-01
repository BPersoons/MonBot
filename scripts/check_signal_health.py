import json, subprocess, re

print("=== RECENT DECISION HEALTH ===")
try:
    history = json.load(open("decision_history.json"))
    recent = history[-20:]
    null_scores = sum(1 for d in recent if d.get("score") is None or d.get("next_step") is None)
    print(f"Last 20 decisions: {len(recent)} total, {null_scores} with null score/next_step")
    for d in recent[-5:]:
        print(f"  {d.get('time','')} {d.get('ticker','?'):20s} score={d.get('score')} next={d.get('next_step','?')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== SWARM MONITOR ALERT STATE ===")
try:
    state = json.load(open("monitor_alert_state.json"))
    for k, v in sorted(state.items())[-10:]:
        print(f"  {k}: {v}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n=== CHECK SIGNAL HEALTH LAST RUN ===")
try:
    result = subprocess.run(
        ["python3", "-c", """
import json
h = json.load(open("decision_history.json"))
recent = h[-10:]
null_count = sum(1 for d in recent if d.get("score") is None)
print(f"Null scores in last 10: {null_count}")
"""],
        capture_output=True, text=True, timeout=10
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:200])
except Exception as e:
    print(f"  ERROR: {e}")
