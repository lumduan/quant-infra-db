# Recurring Bugs

Bugs that have appeared more than once. Each entry: **Symptom → Root cause → Fix → Prevention test**. Append new entries; never silently delete history.

---

_No recurring bugs recorded yet. Add entries below as patterns emerge._

---

## Template (copy this for each entry)

### N. Short descriptive name

- **Symptom**: what the user or logs showed.
- **Root cause**: the underlying issue.
- **Fix**: what resolved it (code change, config change, dependency bump, Docker command).
- **Prevention**: test or check that would catch this before merge next time.

### Common DB-infra suspects (watch list)

These are not yet confirmed recurring bugs, but are the most likely failure modes:

- **Container not healthy**: `docker compose ps` shows `unhealthy`. Suspects: `pg_isready` timing, `quant-network` not created, `.env` missing.
- **Init script re-run fails**: Docker restarts and init scripts error because they assume first-run state. Fix: make everything idempotent.
- **Stale volumes**: `docker compose down` then `up` reuses old volumes with incompatible data. Fix: `docker compose down -v` when schemas change.
- **Hostname resolution**: downstream service can't resolve `quant-postgres`. Fix: verify both containers are on `quant-network`.

---

> **Add new entries below this line. Keep the format consistent.**
