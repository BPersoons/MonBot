# Standard Operating Procedures (SOP) & Knowledge Vault

## 1. Deployment & CI/CD
**Goal**: Ensure zero-downtime updates with automated verification.

### Pre-Flight Checks
Before any deployment, run the local pre-flight suite to verify integrity:
```bash
python -m tests.pre_flight.check_imports
python -m tests.pre_flight.check_connections
```
*Note: `deploy.sh` now runs these automatically.*

### Deployment Command
Use the master script for all updates (Windows):
```bash
.\deploy.bat
```
This script handles:
1.  **Validation**: Pre-flight checks (Python imports, connections).
2.  **Testing**: Full execution of the `tests/run_tests.py` suite. The pipeline *will abort* if any test fails.
3.  **Build**: Docker image construction and push to Artifact Registry.
4.  **Deploy**: VM update and container restart.

### 🧪 Test-Driven Development (TDD) Mandate 
All future codebase modifications MUST include automated testing before triggering the `deploy.bat` pipeline.
- **Bug Fixes**: Require a regression test mirroring the exact failure conditions to prevent recurrence.
- **New Features**: Require scenario tests (e.g. `tests/test_scenarios.py`) validating the behavior. 
- The deployment script is the ultimate gatekeeper. Do not bypass the test suite locally.


### Rollback Strategy
If a deployment fails verification:
1.  Identify the last stable image tag in Artifact Registry.
2.  Update `docker-compose.prod.yml` on the VM to point to that tag.
3.  Run `docker-compose up -d`.

---

## 2. Monitoring & Verification
**Goal**: Continuous visual and functional validation.

### Visual Audit
The system uses a headless browser (Playwright) to verify `https://34.14.121.27.nip.io/webhook/dashboard` post-deployment.
- **Run Manually**: `python -m tests.verification.visual_audit`
- **Key Checks**:
    - HTTP 200 OK
    - "Swarm Health" section visibility
    - Absence of "undefined" or generic "Error" text

### Health Indicators
- **Supabase**: Check `swarm_health` table for `last_pulse` < 5 minutes.
- **Logs**: Check `logs.txt` or GCP Cloud Logging for `ERROR` level entries.

---

## 3. Infrastructure & Networking
### Supabase Connectivity
- Utilizing `DatabaseClient` with circuit breaker pattern.
- Connection issues fallback to local `data_cache.json`.

---

## 4. Critical Dependency Failures — Principle

When a critical external dependency is missing or misconfigured (unfunded wallet, bad secret, unreachable exchange), the right response is **never** to paper over it with a code workaround:

1. **Fail loudly once** — log a clear, actionable warning (what's missing, what the fix is). Send one Telegram alert.
2. **Disable only the affected subsystem** — set the relevant client/flag to `None` so subsequent cycles fast-fail silently rather than spamming logs and alerts.
3. **Require an operational fix** — the real fix is always external (fund the wallet, rotate the secret, fix the network). After fixing, restart the container; the subsystem re-initializes on startup.
4. **Document the fix in CLAUDE.md** — so the next incident is resolved in minutes, not hours.

**Never** mask errors with broad `except` blocks that hide the root cause, retry indefinitely without backoff, or leave the system appearing healthy while a critical path is silently broken.

### Known Critical Dependency Incidents

| Symptom | Root Cause | Fix |
|---|---|---|
| `User or API Wallet ... does not exist` on every trade | `HL_WALLET_ADDRESS` not funded/registered on Hyperliquid | Deposit USDC to the wallet on Hyperliquid, then `docker restart agent_trader_swarm` |

---

## 5. Optimization & Lessons Learned
- **Docker Networks**: Always define a custom bridge network (`trader_net`) for container-to-container communication.
- **GCP Secrets**: Prefer Secret Manager over `.env` files for production security.
- **Python Imports**: `validate_imports` prevented 3 failed deployments by catching missing dependencies early.
