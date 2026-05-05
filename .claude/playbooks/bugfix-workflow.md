# Playbook — Bugfix Workflow

Reproduce → test → fix → prevent. Owned by [agents/bug-investigator.md](../agents/bug-investigator.md).

## 1. Reproduce

- Build the smallest possible repro: a unit test, a script, or a `pytest -k` invocation.
- For DB issues: reproduce with `docker exec` commands or a short Python connectivity script.
  ```bash
  docker exec -it quant-postgres psql -U postgres -d db_csm_set -c "SELECT ..."
  docker exec -it quant-mongo mongosh csm_logs --eval "..."
  ```
- Confirm the trace matches the user's report.
- If the bug is non-deterministic, run repeatedly to confirm flakiness.

## 2. Failing Test First

- Add a regression test under `tests/` mirroring the buggy module's path.
- Name it after the **buggy behavior**, not the fix.
- Run it and confirm it **fails** for the right reason.

## 3. Investigate

- Read the traceback bottom-up; first frame inside `src/` is the suspect.
- `git log -p -S<symbol> -- src/<file>.py` to find the introducing change.
- Check the cross-cutting suspects:
  - Type mismatches or missing validation.
  - Empty / None input not handled.
  - Docker container not running or not healthy (`docker compose ps`).
  - Init-script not idempotent (fails on re-run).
  - Network not created (`docker network ls | grep quant-network`).
  - Volume data stale after schema change (`docker compose down -v` needed).
  - `.env` missing or misconfigured.
  - Sync `requests` in async path.

## 4. Fix

- Smallest diff that makes the test pass.
- No drive-by refactors.
- Type-annotate any new code.
- For init-script fixes: ensure the fix is idempotent.

## 5. Quality Gate

```bash
uv run ruff check . && uv run ruff format . && uv run mypy src tests && uv run pytest -v
```

For DB-infra fixes:
```bash
docker compose up -d && docker compose ps
```

## 6. Memory

- If this matches a known recurring class, append a one-liner to [memory/recurring-bugs.md](../memory/recurring-bugs.md).
- If it's a new pattern that's likely to recur, add it as a new section there.
- If it's a one-off, no memory entry needed.

## 7. Commit

- `fix(<scope>): <short imperative description>`.
- Body explains: what was wrong, what changed, regression test name.
- Follow [agents/git-commit-reviewer.md](../agents/git-commit-reviewer.md) conventions.

## 8. Don't

- Don't delete the failing test to make CI green.
- Don't `except Exception: pass` to hide it.
- Don't ship a fix without the regression test.
- Don't bundle unrelated cleanup with the fix commit.
- Don't fix a DB issue without verifying `docker compose up -d` still works.
