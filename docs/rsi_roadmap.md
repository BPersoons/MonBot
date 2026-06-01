# RSI (Recursive Self-Improvement) Roadmap

Tracks the implementation of autonomous self-improvement for the Agent Trader swarm.
The goal: move from **active** (human implements every change) to **reactive** (swarm learns and
deploys improvements autonomously; human has oversight but is not in the critical path).

---

## Current Status

| Phase | Name | Status | Deployed |
|---|---|---|---|
| 1 | Extended Parameter RSI | **LIVE** | 2026-03-23 |
| 2 | Shadow Trading Mode | **LIVE** | 2026-03-23 |
| 3 | CPO Auto-Execution | **LIVE** | 2026-03-23 |
| 4 | Code-Writing RSI | PLANNED | — |

---

## Phase 1 — Extended Parameter RSI

**Goal:** Move all hardcoded numeric parameters into a single auto-tunable config.
Swarm tunes itself within guardrails. Human is notified but not in the approval loop.

### Status: LIVE ✅

### What was built

| File | Change |
|---|---|
| `config/auto_params.json` | New — single source of truth for all tunable params. Volume-mounted so values survive deploys. |
| `utils/auto_params.py` | New — thread-safe reader/writer with bounds checking and drift guard (rejects changes > 30% from initial value). |
| `utils/cost_tracker.py` | New — daily cost/ROI snapshot: LLM cost, infra ($1/day), exchange fees, trading P&L, net ROI. Writes `cost_log.json`. |
| `utils/auditor.py` | Extended — `_tune_all_params()` now tunes `score_threshold`, `scan_universe_size`, and `tech_prefilter_min`. Uses both 20-trade (short) and 100-trade (long) windows; only tunes when both agree. Cost-aware: raises `tech_prefilter_min` if LLM cost > 20% of gross P&L and net ROI is negative. |
| `agents/project_lead.py` | Reads `score_threshold` and `tech_prefilter_min` live from `auto_params.json` each cycle. |
| `agents/research_agent.py` | Reads `scan_universe_size` live from `auto_params.json` each scan. |
| `agents/swarm_monitor.py` | New `_check_auto_param_changes()` — fires Telegram notification whenever `auto_params.json` is updated by the Auditor. |
| `agents/swarm_learner.py` | Reads `score_threshold` live from `auto_params.json` at cycle start. |

### Tunable parameters

| Param | Default | Bounds | Tuned by |
|---|---|---|---|
| `score_threshold` | 0.40 | 0.30–0.50 | Auditor (win rate) |
| `tech_prefilter_min` | 0.15 | 0.05–0.40 | Auditor (win rate + LLM cost) |
| `scan_universe_size` | 12 | 6–20 | Auditor (win rate) |
| `consecutive_loss_offboard` | 3 | 2–5 | (manual, future) |
| `drawdown_offboard_pct` | 5.0 | 2.0–10.0 | (manual, future) |

### Safety guardrails
- **Bounds**: every param has a hard min/max — Auditor cannot go outside them
- **Drift guard**: if any param moves > 30% from its initial value, update is rejected and logged
- **Two-window check**: both 20-trade and 100-trade windows must agree on direction before tuning
- **Telegram notification**: every change is visible to you immediately

### Observed behaviour (first ~1h live)
- `score_threshold`: 0.40 → 0.48 (win rate low ~25–39%, tightening entry criteria)
- `tech_prefilter_min`: 0.15 → 0.19 (LLM cost control)
- `scan_universe_size`: 12 → 9 (being more selective)

---

## Phase 2 — Shadow Trading Mode

**Goal:** Before any parameter change goes live, test it in paper trading mode for 4 hours.
If paper performance is clearly worse than live history → discard. Otherwise → promote.

### Status: LIVE ✅

### What was built

| File | Change |
|---|---|
| `utils/shadow_comparator.py` | New — records paper trades, finalizes P&L at test end using `dashboard.json` prices, compares win rate vs live history. Returns PROMOTE or DISCARD. |
| `utils/auto_params.py` | Extended — `start_shadow_test()`, `end_shadow_test()`, `get_shadow_state()`, `is_shadow_expired()`, `get_candidate_value()`. |
| `config/auto_params.json` | Added `shadow_mode: false` and `_shadow: {}` fields. |
| `agents/execution_agent.py` | Shadow intercept in `execute_order()`: when `shadow_mode=true`, writes paper trade to `shadow_trades.json` at current market price instead of placing real order on HL. |
| `agents/project_lead.py` | Uses `get_candidate_value()` — during shadow mode, pipeline runs with the *proposed* param value so the test actually validates the change. |
| `agents/research_agent.py` | Same: uses candidate `scan_universe_size` during shadow mode. |
| `utils/auditor.py` | `_tune_param()` now triggers a 4-hour shadow test instead of applying directly. `_check_shadow_progress()` runs every audit cycle; promotes/discards at expiry. |

### Shadow test flow

```
Auditor detects param should change
  ↓
_tune_param() → start_shadow_test(key, new_value, old_value, 4h)
  ↓ shadow_mode = true
Pipeline runs with candidate param value
ExecutionAgent → shadow_trades.json (no real orders)
  ↓ (4 hours)
_check_shadow_progress() sees test expired
  ↓
ShadowComparator.finalize_shadow_trades()  ← estimates P&L from dashboard.json prices
ShadowComparator.compare_performance()
  ↓
DISCARD: shadow win rate < live win rate - 10%  → change rejected, logged
PROMOTE: everything else (including no data)  → auto_params.update() applies change
  ↓
shadow_mode = false, shadow_trades.json cleared
```

### Verdict logic
- **DISCARD**: shadow win rate is clearly worse (> 10pp below live) — evidence of harm
- **PROMOTE**: otherwise — benefit of the doubt; drift guard is the hard safety limit
- INCONCLUSIVE resolves to PROMOTE to avoid permanently blocking the Auditor in low-traffic conditions

### Active test (as of deploy)
First shadow test running: `scan_universe_size: 9 → 8` | expires ~17:11 UTC 2026-03-23

---

## Phase 3 — CPO Auto-Execution of Safe Changes

**Goal:** CPO classifies backlog items and executes the safe subset (AUTO_PARAM changes)
autonomously, with a 1-hour Telegram veto window for you.

### Status: LIVE ✅

### What was built

| File | Change |
|---|---|
| `utils/auto_executor.py` | New — queues AUTO_PARAM changes; polls Telegram `getUpdates` for VETO replies; applies via `auto_params.update()` after 1h if no VETO. State persisted in `auto_exec_pending.json`. |
| `agents/product_owner.py` | Extended — LLM prompt now includes current tunable params + bounds; output schema includes `type` (`AUTO_PARAM`/`CODE_CHANGE`/`INFRA_CHANGE`), `param_key`, `proposed_value`. After creating a backlog task, calls `AutoExecutor.queue()` for AUTO_PARAM items. |
| `agents/swarm_monitor.py` | Extended — new Check 6 calls `AutoExecutor.check_pending()` every 5 min via `_check_auto_executor()`. |

### Auto-execution flow

```
CPO generates improvement idea
  ↓
LLM classifies: AUTO_PARAM / CODE_CHANGE / INFRA_CHANGE
  ↓ (AUTO_PARAM only)
Bounds check + shadow-mode gate (deferred if test active)
  ↓
auto_exec_pending.json updated
Telegram: "[CPO AutoExec] Proposing: scan_universe_size 9→8 ... reply VETO to block"
  ↓ (every 5 min — SwarmMonitor)
AutoExecutor.check_pending()
  → polls Telegram getUpdates for "VETO" reply
  → VETO received: change discarded, logged
  → 1h elapsed, no VETO: auto_params.update() → drift guard → live
```

### Safety chain
1. **Bounds check** — proposed value must be within `_bounds`
2. **Shadow-mode gate** — if a shadow test is active, change is deferred (not queued)
3. **1-hour human veto window** — Telegram veto message sent; reply `VETO` to cancel all pending
4. **Drift guard** — `auto_params.update()` rejects changes > 30% from initial value
5. **Shadow test** — applied change triggers a new shadow test on next Auditor cycle

### Key files

| File | Purpose |
|---|---|
| `auto_exec_pending.json` | Pending veto queue + Telegram offset (ephemeral, root dir) |
| `audit_log.txt` | APPLIED / VETOED events logged with timestamp |

### Dependencies
- Phase 1 ✅ (auto_params.json)
- Phase 2 ✅ (shadow gate — param changes go through shadow test before live)

---

## Phase 4 — Code-Writing RSI (Claude Code Integration)

**Goal:** For CODE_CHANGE backlog items, CPO generates a structured task spec and triggers
a Claude Code session that writes, tests, and deploys the change. Human retains veto.

### Prerequisites checklist (verify before starting)

- [ ] Phase 2 shadow test completed at least once (PROMOTED or DISCARDED — either is fine)
- [ ] Phase 3 CPO generated at least one `AUTO_PARAM` item that flowed through AutoExecutor
- [ ] At least one param change was auto-applied (veto window expired, change applied, no crash)
- [ ] No container crashes or restart loops in the past 7 days
- [ ] Telegram veto tested manually at least once (send VETO, confirm cancellation logged)
- [ ] `audit_log.txt` shows clean history — no runaway tuning or drift guard violations

### Status: PLANNED (requires Phase 3 stable for several weeks first)

### What to build

**A. Structured task spec** for CODE_CHANGE backlog items
```json
{
  "type": "CODE_CHANGE",
  "title": "...",
  "spec": "...",
  "files_to_modify": [...],
  "test_command": "python -m tests.pre_flight.check_imports",
  "validation": "..."
}
```

**B. Trigger mechanism** (webhook daemon or polling loop)

**C. Safety gates** (mandatory before any auto-deploy)
1. `check_imports` must pass
2. `check_connections` must pass
3. `ast.parse` on all modified files
4. Telegram notification + 30-min veto window
5. Auto-rollback if dashboard returns non-200 after deploy

### Hard limits — auto-generated code may NEVER
- Modify the deploy pipeline
- Change secrets handling
- Add new external API integrations
- Modify the circuit breaker

---

## Cost Model

The objective function is net ROI, not win rate in isolation:

```
Net ROI = Trading P&L - LLM costs - Infra costs - Exchange fees
```

**Phase 1** wired LLM cost into the audit loop via `cost_tracker.py`.
If `llm_cost > 20% of |trading_pnl|` and `net_roi < 0` → raise `tech_prefilter_min` to reduce wasteful LLM calls.

**Current cost estimates:**
| Cost | Estimate |
|---|---|
| GCP e2-medium VM | ~$1.00/day |
| Gemini API tokens | Tracked in `llm_usage.json`, ~$0.125/M tokens |
| HL trading fees | ~0.05% taker per leg |

---

## Key Files Reference

| File | Purpose |
|---|---|
| `config/auto_params.json` | Live tunable params — **check this to see current state** |
| `cost_log.json` | Daily cost/ROI snapshot |
| `shadow_trades.json` | Paper trades during active shadow test (ephemeral) |
| `audit_log.txt` | All auto-tune events with timestamps and reasons |
| `learning_report.json` | SwarmLearner diagnostics (funnel, bottlenecks) |
