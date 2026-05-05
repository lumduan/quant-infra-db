# Issue Templates

Two flavors. Pick one and delete the other.

---

## Bug

### Title
`bug(<scope>): <short imperative description>`

### Reproduction
Smallest steps to reproduce. Prefer a code snippet or shell command runnable on a fresh checkout.

```bash
uv sync
docker compose up -d
uv run python -c "<minimal repro>"
```

For DB issues:
```bash
docker compose up -d
docker exec -it quant-postgres psql -U postgres -d db_csm_set -c "<query>"
```

### Expected
_What should have happened._

### Actual
_What actually happened. Include the full traceback if any._

### Environment
- Git SHA: `git rev-parse HEAD`
- Python: `uv run python --version`
- Docker: `docker --version && docker compose version`
- Docker status: `docker compose ps`
- OS: <macOS / Ubuntu / Windows>
- Key deps: `uv tree | grep -E "<relevant packages>"`

### Logs / Artifacts
```
<paste relevant log lines from `docker compose logs`, redact any secrets>
```

### Related
- Memory: any recurring bug class? Link to `.claude/memory/recurring-bugs.md` section if so.
- Recent commits: `git log -p -S<symbol> -- <file>`.

---

## Feature

### Title
`feat(<scope>): <short imperative description>`

### Problem
_What user-visible problem are we solving? Who feels it?_

### Proposal
_What should the user be able to do? Describe the behavior, not the implementation. Include shape of inputs and outputs if it's a new table, collection, or API._

### Roadmap Alignment
_Which phase/task in `docs/plans/ROADMAP.md` does this address?_

### DB Impact (if applicable)
- New tables / collections?
- Schema changes to existing objects?
- Migration required for existing data?

### Alternatives Considered
- <Option A — why not chosen>
- <Option B — why not chosen>

### Acceptance Criteria
- [ ] <Observable behavior 1>
- [ ] <Observable behavior 2>
- [ ] Tests cover happy path + edge cases.
- [ ] Init scripts are idempotent (if DB changes).
- [ ] `docker compose up -d` succeeds with all services healthy.
- [ ] Public API has docstring + example (if applicable).
- [ ] CHANGELOG entry.
- [ ] `docs/plans/ROADMAP.md` updated.

### Out of Scope
- _Explicit non-goals._

### Stakeholders
- Requested by: <name / role>
- Affected modules: <`init-scripts/...`, `docker-compose.yml`, `src/...`>
