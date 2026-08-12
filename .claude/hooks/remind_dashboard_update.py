#!/usr/bin/env python3
"""PostToolUse hook: nudge Claude to refresh docs/masterplan_dashboard.html
whenever roadmap.json is edited (new/changed EXP, gate verdict, backlog item).
Non-blocking — only injects a reminder into context, never fails the edit."""
import json
import sys

data = json.load(sys.stdin)
if data.get("tool_name") not in ("Edit", "Write"):
    sys.exit(0)

file_path = data.get("tool_input", {}).get("file_path", "")
if not file_path.replace("\\", "/").endswith("roadmap.json"):
    sys.exit(0)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            "roadmap.json is zojuist gewijzigd. Werk docs/masterplan_dashboard.html "
            "bij met de verse gate-statussen/cijfers en publiceer opnieuw via de "
            "Artifact tool naar dezelfde URL, zodra deze wijziging is afgerond."
        ),
    }
}))
sys.exit(0)
