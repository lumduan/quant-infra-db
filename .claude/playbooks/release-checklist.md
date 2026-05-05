# Playbook — Release Checklist

Owned by [agents/release-manager.md](../agents/release-manager.md). Every step gated; no skipping.

## 1. Pre-flight

- [ ] Working tree clean: `git status` shows nothing.
- [ ] On the correct branch (`main`).
- [ ] `uv sync` is clean — no drift in `uv.lock`.
- [ ] `.env` is not staged and not in the working tree.

## 2. Quality Gate (must be 100% green)

- [ ] `uv run pytest -v`
- [ ] `uv run pytest --cov=src --cov-report=term-missing` — coverage ≥ 80%.
- [ ] `uv run mypy src tests` — clean.
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run ruff format --check .` — clean.

## 3. Docker Compose Verification

- [ ] `docker compose up -d` — stack starts cleanly.
- [ ] `docker compose ps` — both services show `healthy`.
- [ ] `docker exec -it quant-postgres psql -U postgres -c "SELECT extname FROM pg_extension WHERE extname='timescaledb'"` — extension present.
- [ ] `docker exec -it quant-mongo mongosh csm_logs --eval "show collections"` — collections present.
- [ ] DB connectivity smoke tests pass.

## 4. Version Bump

- [ ] Edit `pyproject.toml` `[project] version` per SemVer:
  - **MAJOR** for breaking changes (schema column removal, type change).
  - **MINOR** for backward-compatible features (new tables, collections, init scripts).
  - **PATCH** for backward-compatible fixes only.
- [ ] Run `uv lock` to refresh lockfile metadata.

## 5. CHANGELOG

- [ ] Add a new section `## [X.Y.Z] — YYYY-MM-DD`.
- [ ] Subsections: `Added`, `Changed`, `Fixed`, `Removed`, `Security`.
- [ ] Entries describe **user-visible** impact, not internal churn.
- [ ] Reference any breaking change with a "Migration" note.
- [ ] Include DB schema changes and Docker Compose changes.

## 6. Commit & Tag

- [ ] Commit version bump + CHANGELOG together: `chore(release): vX.Y.Z`.
- [ ] Tag locally: `git tag vX.Y.Z`.
- [ ] Push: `git push && git push --tags`.

## 7. Docker Smoke Test (if Python app image exists)

- [ ] `docker build -t <name>:vX.Y.Z .`
- [ ] `docker run --rm <name>:vX.Y.Z` — expected output.
- [ ] If applicable, health endpoint responds.

## 8. Announce

- [ ] Post release notes (CHANGELOG section) wherever the team consumes them.
- [ ] Close any milestone tracking the release.

## 9. Rollback Plan

- [ ] If critical regression: open a hotfix branch from the previous tag.
- [ ] Cut a `X.Y.Z+1` patch following this checklist.
