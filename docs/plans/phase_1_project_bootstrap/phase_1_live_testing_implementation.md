# Phase 1: Live Testing Implementation — Project Bootstrap

**Feature:** Phase 1 — Project Bootstrap Live Testing Master Plan Implementation
**Branch:** `feature/phase-1-live-testing-plan`
**Created:** 2026-05-06
**Status:** Draft — pending review
**Depends on:** None (this is the foundation phase)
**Downstream consumers:** All later roadmap phases

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Verification](#verification)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

This plan implements all Phase 1 deliverables for the `quant-infra-db` project — transforming the
`python-template` skeleton into a working Docker Compose database infrastructure stack
(PostgreSQL + TimescaleDB + MongoDB) on the shared `quant-network`, with init scripts, Python
connectivity layer, operational tooling, and a comprehensive test suite.

The implementation satisfies the validation requirements defined in the
[Phase 1 Live Testing Master Plan](PLAN.md) and delivers all items from
[ROADMAP.md](../ROADMAP.md) Phase 1 sections 1.1–4.3.

### Parent Plan Reference

- `docs/plans/phase_1_project_bootstrap/PLAN.md` — Master live-testing plan (the "what to validate")
- `docs/plans/ROADMAP.md` — Master roadmap (the "what to build")

### Key Deliverables

1. **Project bootstrap** — Rename from `python-template` to `quant-infra-db`, add dependencies, update configs
2. **`docker-compose.yml`** — PostgreSQL + TimescaleDB + MongoDB stack with healthchecks, volumes, network
3. **`init-scripts/`** — 5 idempotent init scripts (4 SQL + 1 JS) creating databases, extensions, schemas, hypertables, collections
4. **`src/`** — Python connectivity layer (Pydantic Settings, asyncpg client, motor client)
5. **`scripts/backup.sh`** — PostgreSQL + MongoDB backup script
6. **`tests/`** — Unit + integration test suite (config, connectivity, schema, infra)
7. **Documentation** — Updated README.md, CHANGELOG.md, ROADMAP.md checkboxes

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are tasked with implementing the "Phase 1 — Project Bootstrap Live Testing Master Plan" for the quant-infra-db project. Follow these steps:

1. **Preparation**
   - Read `.claude/knowledge/project-skill.md` to understand all hard architectural and workflow rules.
   - Study `.claude/playbooks/feature-development.md` for the required development workflow.
   - Carefully review `docs/plans/phase_1_project_bootstrap/PLAN.md`, focusing on the "Phase 1 — Project Bootstrap Live Testing Master Plan".
   - Reference the format in `docs/plans/examples/phase1-sample.md` for your implementation plan.

2. **Planning**
   - Before writing any code, create a detailed implementation plan as a Markdown file at `docs/plans/phase_1_project_bootstrap/{phase_name_of_phase}.md`.
   - Your plan must:
     - Clearly outline the steps, deliverables, and test strategy for Phase 1.
     - Include the full prompt you received for this task.
     - Follow the structure and style of the provided example.
   - Commit this plan before proceeding.

3. **Implementation**
   - After the plan is committed, implement the required code, tests, and documentation to fulfill the Phase 1 live testing plan.
   - Ensure all work strictly follows the standards in `.claude/knowledge/project-skill.md` and `.claude/playbooks/feature-development.md`.
   - As you progress, update `docs/plans/phase_1_project_bootstrap/PLAN.md` and your phase plan file with progress notes, checklist updates, completion dates, and any issues encountered.

4. **Completion**
   - When all deliverables are complete, update documentation with final notes and mark all relevant checklist items as done.
   - Commit all changes in a single, conventional commit, referencing the files changed, rationale, and validation performed.

**Key constraints:**
- All code must be async, type-safe, and use Pydantic for validation/config.
- All infra must be managed via Docker Compose, with strict `.env`/secret hygiene.
- Testing, CI, and documentation standards are mandatory.
- The implementation plan must be committed before any code changes.
- All documentation and code must follow the project's conventions and structure.

**Deliverables:**
- `docs/plans/phase_1_project_bootstrap/{phase_name_of_phase}.md` (implementation plan, including this prompt)
- Updated `docs/plans/phase_1_project_bootstrap/PLAN.md` and phase plan file with progress notes
- All code, tests, and documentation required for Phase 1 live testing
- A single, well-documented commit

Begin by producing the implementation plan as described above.
```

---

## Scope

### In Scope

| Component | Description |
|---|---|
| Project bootstrap | Rename `pyproject.toml`, add `asyncpg`, `motor`, `pydantic`, `pydantic-settings`, `httpx` deps |
| `docker-compose.yml` | PostgreSQL + TimescaleDB + MongoDB, healthchecks, named volumes, external `quant-network` |
| Init scripts (5 files) | `01_create_databases.sql`, `02_enable_timescaledb.sql`, `03_schema_csm_set.sql`, `04_schema_gateway.sql`, `mongo-init.js` |
| Python connectivity | `src/config.py` (Pydantic Settings), `src/db/postgres.py` (asyncpg), `src/db/mongo.py` (motor), `src/db/errors.py` |
| Backup script | `scripts/backup.sh` — `pg_dumpall` + `mongodump` |
| Test suite | `tests/test_config.py`, `tests/test_postgres.py`, `tests/test_mongo.py`, `tests/test_infra.py`, `tests/conftest.py` updates |
| Documentation | `README.md` rewrite, `CHANGELOG.md` update, `ROADMAP.md` checkbox updates, `.env.example` update |

### Out of Scope

- `scripts/restore.sh` — deferred; can be added as a follow-up
- `tests/infra/` directory with full WS1-WS6 coverage — the PLAN.md specifies an extensive infra test suite; this implementation delivers the core connectivity and schema tests; full WS1-WS6 automation is a follow-up
- CI workflow changes (`infra-smoke.yml`, `quality-gate.yml`) — existing `ci.yml` already covers quality gate
- `docs/operations/baselines.md` and `docs/operations/runbook.md` — deferred to follow-up
- `scripts/live_smoke.sh` — deferred
- `scripts/regenerate_fixtures.py` — deferred
- Image pinning (keep `latest` tags for now per existing design)
- Secret scanning in CI (gitleaks/trufflehog) — deferred

---

## Design Decisions

### 1. `asyncpg` for PostgreSQL, `motor` for MongoDB

Per the project's Hard Rule #1 (async-first I/O), all database drivers must be async.
- **PostgreSQL**: `asyncpg` — the standard async PostgreSQL driver for Python. `psycopg2` is sync and forbidden in library code per project rules.
- **MongoDB**: `motor` — the official async MongoDB driver (wraps `pymongo` with async API via Tornado).

### 2. Pydantic Settings as single config entry point

Per Hard Rule #6, all configuration flows through a single `Settings` object using `pydantic-settings`.
- `SecretStr` for `postgres_password` — prevents accidental logging/printing
- `frozen=True` — prevents mutation at runtime
- DSN properties compute connection strings on demand

### 3. Init script design: ordered, idempotent, DDL-only

- Scripts numbered `01_` through `04_` encode dependency order (databases → extension → schemas)
- All use `IF NOT EXISTS` / `CREATE TABLE IF NOT EXISTS` for idempotency
- SQL scripts target specific databases via `\c` meta-commands
- MongoDB init script uses `db.getSiblingDB()` pattern
- No `DROP` statements — init scripts are additive only

### 4. Docker Compose: external network, named volumes, healthchecks

- `quant-network` is external (created once per host via `docker network create`)
- Named volumes (`postgres_data`, `mongo_data`) for persistence
- Healthchecks: `pg_isready` for PostgreSQL, `mongosh --eval "db.adminCommand('ping')"` for MongoDB
- `restart: always` on both services
- Container names pinned to `quant-postgres` and `quant-mongo` (not Compose-generated)

### 5. Schema design matches ROADMAP.md specifications

Tables and collections follow the roadmap exactly:

| Database | Table | Type | Key columns |
|---|---|---|---|
| `db_csm_set` | `equity_curve` | Hypertable | `strategy_id`, `time`, `equity` |
| `db_csm_set` | `trade_history` | Regular | `strategy_id`, `time`, `symbol`, `quantity`, `price` |
| `db_csm_set` | `backtest_log` | Regular | `strategy_id`, `run_id`, `config` (JSONB), `summary` (JSONB) |
| `db_gateway` | `daily_performance` | Hypertable | `strategy_id`, `time`, `daily_return`, `cumulative_return` |
| `db_gateway` | `portfolio_snapshot` | Hypertable | `strategy_id`, `time`, `positions` (JSONB), `total_equity` |

| Database | Collection | Key indexes |
|---|---|---|
| `csm_logs` | `backtest_results` | `{strategy_id: 1, created_at: -1}` |
| `csm_logs` | `model_params` | `{strategy_id: 1, created_at: -1}` |
| `csm_logs` | `signal_snapshots` | `{strategy_id: 1, created_at: -1}` |

### 6. Test strategy: unit + integration split

- **Unit tests** (`tests/test_config.py`): Config model validation, DSN generation, SecretStr behavior — no Docker required
- **Integration tests** (`tests/test_postgres.py`, `tests/test_mongo.py`, `tests/test_infra.py`): Require healthy Docker Compose stack; use `pytest` markers to allow skipping when Docker is unavailable
- Tests use real connections, not mocks

### 7. Single conventional commit at completion

All changes land in one commit following the Conventional Commits format. This keeps the history clean and makes the Phase 1 bootstrap auditable as a unit.

---

## Implementation Steps

### Step 1: Project bootstrap & dependency setup

Update `pyproject.toml`:
- Rename `name` from `python-template` to `quant-infra-db`
- Update `description`, `keywords`, `classifiers` to reflect quant-infra-db
- Add runtime dependencies: `pydantic>=2`, `pydantic-settings>=2`, `asyncpg>=0.29`, `motor>=3.5`, `httpx>=0.27`
- Add `pytest-asyncio` to dev dependencies (already present)
- Register `infra` pytest marker

Update `.env.example`:
- Add `POSTGRES_PASSWORD=your_strong_password_here`
- Add `MONGO_INITDB_ROOT_USERNAME=admin`
- Add `MONGO_INITDB_ROOT_PASSWORD=your_strong_password_here`
- Add DB host/port variables

Update `README.md`:
- Replace `python-template` content with `quant-infra-db` content
- Document prerequisites (Docker, uv, Python >= 3.12)
- Document the `docker network create quant-network` precondition
- Document `cp .env.example .env` + edit password step
- Document `docker compose up -d` and verification steps
- Document connection strings for both databases
- Document backup/restore workflow

Update `CHANGELOG.md`:
- Add Phase 1 entries under `[Unreleased]`

### Step 2: Docker Compose stack

Create `docker-compose.yml`:
- `quant-postgres` service: `timescale/timescaledb:latest-pg16`, port 5432, healthcheck, named volume, init-scripts bind mount, env vars
- `quant-mongo` service: `mongo:latest`, port 27017, healthcheck, named volume, init-script bind mount, env vars
- External network `quant-network`
- Named volumes: `postgres_data`, `mongo_data`

### Step 3: Init scripts

Create `init-scripts/01_create_databases.sql`:
- `CREATE DATABASE db_csm_set`
- `CREATE DATABASE db_gateway`

Create `init-scripts/02_enable_timescaledb.sql`:
- `CREATE EXTENSION IF NOT EXISTS timescaledb` on both databases

Create `init-scripts/03_schema_csm_set.sql`:
- `equity_curve` hypertable (strategy_id, time TIMESTAMPTZ, equity DOUBLE PRECISION)
- `trade_history` table (strategy_id, time TIMESTAMPTZ, symbol, quantity, price, side)
- `backtest_log` table (strategy_id, run_id, config JSONB, summary JSONB, created_at TIMESTAMPTZ)
- Indexes on `(strategy_id, time DESC)` for all timeseries tables

Create `init-scripts/04_schema_gateway.sql`:
- `daily_performance` hypertable (strategy_id, time TIMESTAMPTZ, daily_return, cumulative_return)
- `portfolio_snapshot` hypertable (strategy_id, time TIMESTAMPTZ, positions JSONB, total_equity DOUBLE PRECISION)
- Indexes

Create `init-scripts/mongo-init.js`:
- Use `db.getSiblingDB('csm_logs')`
- Create collections: `backtest_results`, `model_params`, `signal_snapshots`
- Create compound indexes on `{strategy_id: 1, created_at: -1}` for each collection

### Step 4: Python connectivity layer

Create `src/config.py`:
- `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", frozen=True)`
- Fields: `postgres_password: SecretStr`, `postgres_host: str = "localhost"`, `postgres_port: int = 5432`, `mongo_host: str = "localhost"`, `mongo_port: int = 27017`
- Properties: `csm_set_dsn`, `gateway_dsn`, `mongo_uri`

Create `src/db/errors.py`:
- `DatabaseConnectionError` — root exception for DB module
- `PostgresConnectionError(DatabaseConnectionError)`
- `MongoConnectionError(DatabaseConnectionError)`

Create `src/db/postgres.py`:
- `create_postgres_pool(dsn: str) -> asyncpg.Pool` — creates connection pool
- `check_postgres_health(pool: asyncpg.Pool) -> bool` — runs `SELECT 1`
- `close_postgres_pool(pool: asyncpg.Pool) -> None` — graceful shutdown

Create `src/db/mongo.py`:
- `create_mongo_client(uri: str) -> AsyncIOMotorClient` — creates client
- `check_mongo_health(client: AsyncIOMotorClient) -> bool` — runs `ping`
- `close_mongo_client(client: AsyncIOMotorClient) -> None` — graceful shutdown

Create `src/db/__init__.py`:
- Public re-exports of all functions and error classes

Update `src/main.py`:
- Replace template hello-world with connectivity smoke test
- Load settings, connect to both databases, print health status

### Step 5: Backup script

Create `scripts/backup.sh`:
- Create timestamped backup directory under `./backups/`
- Run `pg_dumpall -U postgres` against `localhost:5432`
- Run `mongodump` against `localhost:27017`
- Report artefact paths and sizes
- Error handling for missing containers or failed dumps

### Step 6: Test suite

Update `tests/conftest.py`:
- Add `settings` fixture (loads Settings from `.env`)
- Add `postgres_pool` fixture (creates/destroys asyncpg pool)
- Add `mongo_client` fixture (creates/destroys motor client)
- Add `infra` marker registration
- Add `docker_required` skip decorator

Create `tests/test_config.py`:
- `test_settings_loads_from_env` — Settings loads from `.env`
- `test_secret_str_not_exposed` — `repr(settings)` does not leak password
- `test_frozen_settings` — mutation raises error
- `test_csm_set_dsn` — DSN string is correctly formatted
- `test_gateway_dsn` — DSN string is correctly formatted
- `test_mongo_uri` — URI string is correctly formatted
- `test_default_hosts` — defaults are `localhost`

Create `tests/test_postgres.py`:
- `test_connect_to_csm_set` — connect, `SELECT 1`, assert result
- `test_connect_to_gateway` — connect, `SELECT 1`, assert result
- `test_timescaledb_extension_present` — check extension in both DBs
- `test_hypertables_exist` — check `equity_curve`, `daily_performance`, `portfolio_snapshot` are hypertables
- `test_schema_tables_exist` — check all expected tables

Create `tests/test_mongo.py`:
- `test_connect_and_ping` — `ping` returns `ok: 1`
- `test_collections_exist` — `csm_logs` has expected collections
- `test_indexes_exist` — indexes on `backtest_results` match spec
- `test_document_round_trip` — insert, find, delete

Create `tests/test_infra.py`:
- `test_docker_compose_ps_healthy` — shell out to `docker compose ps` and check for healthy
- `test_network_quant_network_exists` — `docker network ls` includes `quant-network`

### Step 7: Update documentation

Update `docs/plans/ROADMAP.md`:
- Mark Phase 1 items as `[x]` Complete
- Update "Current status" section

Update `docs/plans/phase_1_project_bootstrap/PLAN.md`:
- Add completion notes referencing this implementation plan
- Mark relevant checklist items

Update `docs/plans/phase_1_project_bootstrap/phase_1_live_testing_implementation.md` (this plan):
- Add completion notes with issues encountered

### Step 8: Quality gate and commit

Run the full quality gate:
```bash
uv sync --all-groups
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest
```

Commit all changes in a single conventional commit.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `pyproject.toml` | MODIFY | Rename project, add deps, register infra marker |
| `.env.example` | MODIFY | Add DB credentials and host/port variables |
| `README.md` | MODIFY | Rewrite for quant-infra-db with setup instructions |
| `CHANGELOG.md` | MODIFY | Add Phase 1 entries |
| `docker-compose.yml` | CREATE | PostgreSQL + MongoDB stack with healthchecks |
| `init-scripts/01_create_databases.sql` | CREATE | Create `db_csm_set` and `db_gateway` |
| `init-scripts/02_enable_timescaledb.sql` | CREATE | Enable TimescaleDB extension on both DBs |
| `init-scripts/03_schema_csm_set.sql` | CREATE | Schema for `db_csm_set` (3 tables) |
| `init-scripts/04_schema_gateway.sql` | CREATE | Schema for `db_gateway` (2 tables) |
| `init-scripts/mongo-init.js` | CREATE | MongoDB collections and indexes for `csm_logs` |
| `scripts/backup.sh` | CREATE | PostgreSQL + MongoDB backup script |
| `src/config.py` | CREATE | Pydantic Settings model |
| `src/db/__init__.py` | CREATE | Public re-exports |
| `src/db/postgres.py` | CREATE | asyncpg connection pool and health check |
| `src/db/mongo.py` | CREATE | motor client and health check |
| `src/db/errors.py` | CREATE | DB module exceptions |
| `src/main.py` | MODIFY | Connectivity smoke test |
| `tests/conftest.py` | MODIFY | Shared fixtures (settings, DB pools, infra marker) |
| `tests/test_config.py` | CREATE | Settings model unit tests |
| `tests/test_postgres.py` | CREATE | PostgreSQL integration tests |
| `tests/test_mongo.py` | CREATE | MongoDB integration tests |
| `tests/test_infra.py` | CREATE | Docker Compose infra tests |
| `docs/plans/ROADMAP.md` | MODIFY | Mark Phase 1 complete |
| `docs/plans/phase_1_project_bootstrap/PLAN.md` | MODIFY | Add progress notes |
| `docs/plans/phase_1_project_bootstrap/phase_1_live_testing_implementation.md` | CREATE | This plan document |

---

## Success Criteria

- [ ] `pyproject.toml` name is `quant-infra-db` with all required dependencies
- [ ] `docker compose up -d` from fresh clone reaches `(healthy)` for both services
- [ ] `psql` connects to `db_csm_set` and `db_gateway` with TimescaleDB extension active
- [ ] `mongosh` connects to `csm_logs` and lists expected collections with indexes
- [ ] All init scripts are idempotent (re-run produces zero errors)
- [ ] `uv run python -m src.main` reports healthy connectivity to both databases
- [ ] `bash scripts/backup.sh` produces non-empty backup artefacts
- [ ] `uv run ruff check .` exits 0
- [ ] `uv run ruff format --check .` exits 0
- [ ] `uv run mypy src tests` exits 0
- [ ] `uv run pytest` exits 0 with coverage >= 80%
- [ ] README.md commands are executable verbatim on a fresh clone
- [ ] `docker compose ps` shows `quant-postgres` and `quant-mongo` as `healthy`

---

## Verification

### Local verification

```bash
# 1. Quality gate (no Docker needed)
uv sync --all-groups
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest tests/test_config.py  # unit tests only

# 2. Full stack test
docker network create quant-network 2>/dev/null || true
cp .env.example .env  # edit POSTGRES_PASSWORD if needed
docker compose up -d
# Wait for healthy, then:
docker compose ps  # both should show (healthy)

# 3. Database connectivity
docker exec quant-postgres psql -U postgres -d db_csm_set -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"
docker exec quant-mongo mongosh csm_logs --eval "db.getCollectionNames()"

# 4. Python connectivity
uv run python -m src.main

# 5. Integration tests (requires healthy stack)
uv run pytest tests/test_postgres.py tests/test_mongo.py tests/test_infra.py -v

# 6. Full test suite
uv run pytest

# 7. Backup
bash scripts/backup.sh
ls -la backups/

# 8. Cleanup
docker compose down
```

### CI verification

The existing `.github/workflows/ci.yml` runs on every PR and covers:
- `ruff check .`
- `ruff format --check .`
- `mypy src tests`
- `pytest -v --cov=src --cov-fail-under=80`

The `docker-publish.yml` and `security.yml` workflows are unaffected by these changes.

---

## Completion Notes

*To be filled during and after implementation.*
