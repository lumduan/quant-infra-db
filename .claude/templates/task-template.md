# Task: <short imperative title>

## Goal
_One sentence stating the user-visible outcome. Not the implementation._

## Context
_Why this task exists. Link any related plan (`docs/plans/ROADMAP.md` phase/task), prior PR, or memory entry. Note any constraints (deadline, dependency, freeze)._

## Acceptance Criteria
- [ ] <Observable behavior 1>
- [ ] <Observable behavior 2>
- [ ] New / updated test passes: `uv run pytest tests/<path> -v`
- [ ] Quality gate clean: `uv run ruff check . && uv run mypy src tests && uv run pytest`
- [ ] `docker compose up -d && docker compose ps` — all services `healthy`
- [ ] Docstring / init-script comment added or updated
- [ ] `docs/plans/ROADMAP.md` status updated if applicable

## Docker/DB Verification (if applicable)
```bash
docker compose up -d
docker compose ps
docker exec -it quant-postgres psql -U postgres -l
docker exec -it quant-mongo mongosh csm_logs --eval "show collections"
```

## Out of Scope
- _Explicitly listed; if it's not here and not in acceptance criteria, ask before doing it._

## Verification Commands
```bash
# Run the relevant tests
uv run pytest tests/<path> -v

# Full quality gate
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest -v

# Docker Compose smoke test
docker compose up -d && docker compose ps

# Backup smoke test
bash scripts/backup.sh
```

## Files Likely Touched
- `docker-compose.yml` (if Docker changes)
- `init-scripts/<file>.sql` (if schema changes)
- `src/<module>.py`
- `tests/<mirrored_path>.py`
- `docs/plans/ROADMAP.md` (if a task is completed)
- `README.md` (if setup steps change)

## Notes / Open Questions
- _Anything the implementer needs to clarify before starting._
