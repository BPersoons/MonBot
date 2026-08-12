#!/usr/bin/env python3
import json, sys, subprocess

data = json.load(sys.stdin)
if data.get("tool_name") not in ("Edit", "Write"):
    sys.exit(0)

file_path = data.get("tool_input", {}).get("file_path", "")
if not file_path.endswith(".py"):
    sys.exit(0)

result = subprocess.run(
    ["python", "-m", "py_compile", file_path],
    capture_output=True, text=True
)
if result.returncode != 0:
    print(f"SYNTAX ERROR in {file_path}:\n{result.stderr.strip()}", file=sys.stderr)
    sys.exit(2)  # Blocks the action, Claude sees the error immediately

print(f"✓ Syntax OK: {file_path}")
