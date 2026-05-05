# Playbook — Dependency Upgrade

Owned by [agents/dependency-manager.md](../agents/dependency-manager.md). All operations through `uv`.

## 1. Survey Current State

```bash
uv tree                # full tree
uv pip audit           # known CVEs
```

Capture the pre-upgrade `uv.lock` hash for reference.

## 2. Pick Scope

- **Single package**: `uv lock --upgrade-package <pkg>`.
- **All packages (minor/patch)**: `uv lock --upgrade`.
- **Major bump on a load-bearing dep**: (`psycopg2`, `pymongo`, `httpx`, `pydantic`) treat as its own focused PR.

## 3. Apply

```bash
uv lock --upgrade-package <pkg>
uv sync
```

## 4. Read Upstream CHANGELOG

- Skim the package's CHANGELOG / release notes for breaking changes.
- Note anything affecting:
  - Async API surface.
  - Pydantic model behavior.
  - pandas API (especially deprecation warnings).
  - FastAPI routing / dependencies (if applicable).
  - Type stubs (mypy errors after upgrade are usually here).
  - psycopg2 or pymongo API changes (DB connectivity impact).

## 5. Quality Gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest -v
```

Run integration markers too if present: `uv run pytest -m integration -v`.

## 6. DB Connectivity Check

After dependency upgrades that touch DB drivers (`psycopg2`, `pymongo`):

```bash
docker compose up -d
uv run python -c "
import psycopg2
conn = psycopg2.connect('postgresql://postgres:<pass>@localhost:5432/db_csm_set')
print(conn.cursor().execute('SELECT version()').fetchone())
"
```

## 7. Targeted Migration (only if needed)

- If breaking changes hit the code, apply migrations in the same PR.
- Document migration steps in commit body.

## 8. Security Recheck

- `uv pip audit` clean after upgrade.
- No new advisories introduced.

## 9. Commit

- One commit: `pyproject.toml` + `uv.lock` together.
- Conventional commit: `chore(deps): upgrade <pkg> to vX.Y.Z` (or `feat(deps):` for a major migration).
- Body: list of upgraded packages, key breaking changes, migration notes.

## 10. Don't

- Don't commit `uv.lock` without `pyproject.toml` (or vice versa).
- Don't bypass the quality gate.
- Don't bundle a dep upgrade with a feature PR — separate concerns.
- Don't pin to exact versions in `pyproject.toml` without a documented reason.
- Don't skip the DB connectivity check after upgrading DB drivers.
