# <type>(<scope>): <short imperative title>

> Conventional commit types: feat, fix, refactor, perf, test, docs, chore, build, ci, infra.
> Use `infra` for Docker Compose, init-script, and backup-script changes.

## Summary
_2-3 sentence overview. What changed and why. User impact in one line._

## Changes
- `docker-compose.yml` — <one-line description>
- `init-scripts/<file>.sql` — <one-line description>
- `src/<module>.py` — <one-line description>
- `tests/<path>.py` — <added regression / coverage for X>
- `scripts/<file>.sh` — <one-line description>
- `docs/...` — <updated section X>

## Technical Implementation
_For non-trivial changes: how the change is implemented, key design decisions, trade-offs. Skip if the diff is self-explanatory._

## DB Impact (if schema/Docker changes)
- [ ] Init scripts are idempotent (`IF NOT EXISTS`).
- [ ] Schema change is backward-compatible or has a documented migration path.
- [ ] Downstream consumers notified of breaking changes.

## Test Plan
- [ ] `uv run pytest -v` — full suite passes.
- [ ] `uv run mypy src tests` — clean.
- [ ] `uv run ruff check . && uv run ruff format --check .` — clean.
- [ ] `uv run pytest --cov=src --cov-report=term-missing` — coverage ≥ 80%.
- [ ] `docker compose up -d && docker compose ps` — both services `healthy`.
- [ ] `docker exec -it quant-postgres psql -U postgres -l` — expected databases present.
- [ ] `docker exec -it quant-mongo mongosh csm_logs --eval "show collections"` — expected collections present.
- [ ] `bash scripts/backup.sh` — backup artifacts created.
- [ ] Python connectivity smoke test passes for both PostgreSQL and MongoDB.
- [ ] Manual verification: <script run, curl, browser click-through>.

## Risk & Rollback
- **Risk level**: low / medium / high.
- **Blast radius**: _which modules / containers / downstream services can be affected if this is wrong_.
- **Rollback**: revert this PR (`git revert <sha>`). For Docker/volume changes, `docker compose down -v` may be needed.

## Docs / Changelog
- [ ] CHANGELOG entry added (if user-visible).
- [ ] Public docstrings or init-script comments updated.
- [ ] README updated (if connection strings or setup steps changed).
- [ ] `docs/plans/ROADMAP.md` status updated (if a task was completed).

## Related
- Closes #<issue>
- Plan: `docs/plans/<file>.md`
- Memory: `.claude/memory/recurring-bugs.md` (if a regression class)

---
Co-authored-by: Claude
