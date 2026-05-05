# Playbook — Code Review

For reviewing PRs / diffs. Read tests first; they document intent.

## 1. Skim Scope

- One logical change? If a PR mixes refactor + feature, ask for a split.
- Does the diff stay within the layer it claims to touch?
- For DB changes: are init-script changes accompanied by `docker-compose.yml` changes? They should be reviewed together.

## 2. Read Tests First

- Do the tests describe the **behavior** the feature claims?
- Are edge cases covered: empty input, None, out-of-range, error paths?
- Is there a regression test for any bug fixed?
- No mocked data structures; no real network in unit tests.
- DB connectivity tests marked as integration tests.

## 3. Read Code

- Standards check against [knowledge/coding-standards.md](../knowledge/coding-standards.md):
  - Full type annotations
  - Pydantic at boundaries
  - Logging not `print`
  - Module-specific exceptions, not bare `Exception`
  - File size budget respected
- DB-specific checks:
  - Init scripts: numbered, idempotent (`IF NOT EXISTS`), ordered by dependency.
  - Docker Compose: healthchecks present, named volumes, env vars from `.env`.
  - No real credentials committed.
- Cross-cutting suspects (auto-flag):
  - `requests` in async path → block.
  - Hard-coded paths or secrets → block.
  - Bare `except:` → block.
  - Missing input validation at boundaries → block.

## 4. Security Pass

- New external surface (HTTP route, CLI, file I/O on user input)?
- Missing auth on a non-public endpoint?
- Input validation present?
- Errors leaking internals to clients?
- `.env` in diff → block immediately.

## 5. Performance Pass

- New I/O — batched, timed out, retried?
- Data processing — streaming or vectorized where appropriate?
- New SQL queries — indexes in place?
- Large allocations — any obvious memory issues?

## 6. Docs

- Public functions have docstrings (Google style).
- Init scripts have header comments.
- CHANGELOG updated if user-visible.
- `README.md` updated if connection strings or setup steps changed.
- `docs/plans/ROADMAP.md` status updated if a task was completed.

## 7. Decide

- **Approve** if all blocks resolved.
- **Request changes** with concrete `file:line` references and a fix per finding.
- **Comment** for non-blocking suggestions, clearly labeled "non-blocking".

## 8. Don't

- Don't approve without reading tests.
- Don't approve a refactor that mixes in a feature.
- Don't nitpick formatting — ruff handles that.
- Don't ask for stylistic preferences as blocking changes.
- Don't approve if `.env` or credential files are in the diff.
