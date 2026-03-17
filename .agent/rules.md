# Antigravity Optimizations & Best Practices

## 1. Token Efficiency (Zero-Yapping)
- **Extreme Brevity:** Never use conversational filler ("Here is the code...", "I understand...", "Sure!"). Start immediately with the solution or the tool call.
- **Direct Execution:** If a solution is obvious, execute it immediately using tool calls instead of explaining it first.
- **Concise Artifacts:** Keep markdown artifacts strictly to the point without redundant explanations.

## 2. Autonomy & Proactiveness
- **Self-Correction:** If a command or script fails, examine the logs and fix it yourself. Do NOT stop and ask the user for help unless you have exhausted 3 retry attempts or the fix requires a destructive action (like dropping a database table).
- **Parallel Execution:** Batch read operations (e.g., viewing multiple files) and write operations concurrently when safe to do so.
- **Test-Driven:** Before declaring a task finished, run a validation command (e.g., `python check_issues.py` or a dedicated test script) to prove the fix works locally.

## 3. Workflow Best Practices
- **Absolute Paths:** Always use absolute paths in tool calls to prevent ambiguity.
- **Incremental Verification:** When refactoring, verify syntax and imports incrementally.
- **Context Management:** Only read files that are strictly necessary. Do not traverse large log files without using `grep` or `search_logs.py`. Use `grep_search` to pinpoint symbols instead of guessing file contents.