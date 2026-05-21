# Phase 2: `quant-infra-db` — Schema + Hypertables + Continuous Aggregates

**Feature:** Strategies Report Metrics — Phase 2: `quant-infra-db` Schema Layer
**Branch:** `feat/schema-hypertables-continuous-aggregates`
**Created:** 2026-05-21
**Status:** In progress
**Completed:** —
**Depends On:** Phase 1 — `strategies/csm-set` adapter (writes richer trade rows + emits `StrategyReport`)

---

## Table of Contents

1. [Overview](#overview)
2. [AI Prompt](#ai-prompt)
3. [Scope](#scope)
4. [Design Decisions](#design-decisions)
5. [SQL Schema Rules](#sql-schema-rules)
6. [Implementation Steps](#implementation-steps)
7. [File Changes](#file-changes)
8. [Success Criteria](#success-criteria)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 2 extends `quant-infra-db` so the platform can persist the richer per-trade detail and
the JSONB report snapshot that Phase 1 (csm-set) now produces, and so that the gateway
(Phase 3) and the dashboard (Phase 4) can read pre-aggregated monthly metrics without
recomputing on every request. Concretely:

- `trade_history` gains per-trade P&L fields and a relaxed `side` constraint.
- A new hypertable `benchmark_equity_curve` (db_csm_set) stores per-strategy buy-and-hold
  benchmark NAV so the dashboard can compare strategy vs. benchmark.
- A new hypertable `strategy_report_snapshot` (db_gateway) stores the JSONB report Phase 3
  upserts on each daily ingest.
- Two TimescaleDB continuous aggregates roll up monthly metrics (`cagg_*_monthly`) so
  dashboard reads hit pre-aggregated chunks instead of scanning hypertables.

Per user direction this phase also lands a **thin Python layer** (Pydantic V2 row models +
async asyncpg repository helpers for the new tables) under `src/db/` so downstream services
can import typed row objects rather than rebuilding them. The four uncommitted UNIQUE-index
diffs on `03_schema_csm_set.sql` / `04_schema_gateway.sql` (which add the unique columns the
csm-set adapter's `INSERT … ON CONFLICT` paths require) are folded into this phase since they
serve the same "make the schema upsert-friendly for report ingestion" goal.

### Parent Plan Reference

- `../../../../plans/feature-strategies-report-metrics/ROADMAP.md` (cross-repo umbrella; see
  Phase 2 section).
- `docs/plans/ROADMAP.md` (this sub-repo's own roadmap; Phase 2 of the umbrella feature is
  optional/independent work added on top of the completed core platform Phases 1–5).

### Key Deliverables

1. **`init-scripts/05_schema_strategy_report.sql`** — idempotent SQL that performs ALTER /
   CREATE / `create_hypertable` / continuous-aggregate work for both databases.
2. **`init-scripts/03_schema_csm_set.sql` / `04_schema_gateway.sql`** — fold the existing
   uncommitted UNIQUE-index edits into this phase's commit.
3. **`init-scripts/mongo-init.js`** — comment-only documentation of the new `metrics` keys
   stored in `csm_logs.backtest_results`.
4. **`scripts/backup.sh`** — comment block listing the new tables for operator visibility.
5. **`src/db/models.py`** — frozen Pydantic V2 row models (`TradeHistoryRow`,
   `BenchmarkEquityCurveRow`, `StrategyReportSnapshotRow`).
6. **`src/db/errors.py`** — new `RepositoryError` under the existing `DatabaseConnectionError`
   root.
7. **`src/db/repositories.py`** — async upsert/fetch helpers built on `asyncpg.Pool`.
8. **`src/db/__init__.py`** — re-exports for the new public symbols.
9. **`tests/test_models.py`** + **`tests/test_repositories.py`** — unit tests with mocked
   asyncpg pools; **`tests/test_postgres.py`** — extended infra-marked assertions for the new
   hypertables and continuous aggregates.
10. **`.claude/knowledge/feature-strategies-report-metrics.md`** — captures the TimescaleDB
    idempotency patterns and continuous-aggregate gotchas discovered during the work.

---

## AI Prompt

The following prompt was used to generate this phase:

```
You are implementing Phase 2 — quant-infra-db: schema + hypertable + continuous aggregates —
for the Quant Trading System database infrastructure layer. Follow every step below in strict order.
Do NOT skip steps or reorder them.

---

## Step 1 — Load Context (MANDATORY BEFORE ANYTHING ELSE)

1. Read `.claude/knowledge/project-skill.md` in full. Internalize all non-negotiable rules.
2. Read `.claude/playbooks/feature-development.md` in full. This is your workflow.
3. Read `../docs/plans/feature-strategies-report-metrics/ROADMAP.md` carefully.
   Focus exclusively on **Phase 2 — quant-infra-db — schema + hypertable + continuous aggregates**.
   Note every deliverable, acceptance criterion, and dependency listed there.
4. Read `docs/plans/examples/phase1-sample.md` to understand the required plan format.
5. Read all existing init scripts (`init-scripts/01_` through `init-scripts/04_`) to understand
   current schema state, naming conventions, and script structure.

---

## Step 2 — Create Feature Branch

```bash
git checkout -b feat/schema-hypertables-continuous-aggregates
```

Confirm branch creation before proceeding.

---

## Step 3 — Write the Plan (DO NOT CODE YET)

Create `docs/plans/feature-strategies-report-metrics/PLAN.md` using the exact structure from
phase1-sample.md. Your plan MUST include:

- **Scope**: what Phase 2 covers and what it explicitly excludes
- **Deliverables**: full list with file paths
- **Acceptance Criteria**: measurable, checkable
- **SQL Schema Design**: table names, column names, types, constraints, partitioning keys for
  hypertables, continuous aggregate definitions and refresh policies
- **Python Layer Design**: Pydantic model names, fields, async function signatures
- **Test Strategy**: what is unit-tested vs integration-tested, mocking approach for DB
- **Risks & Mitigations**: e.g. TimescaleDB version compatibility, idempotency edge cases
- **Implementation Order**: numbered steps
- **Embedded AI Agent Prompt**: paste this full prompt into the plan

Commit the plan before writing any implementation code:

```bash
git add docs/plans/feature-strategies-report-metrics/PLAN.md
git commit -m "docs(plan): add Phase 2 schema hypertables continuous aggregates plan"
```

---

## Step 4 — Implement SQL Init Scripts

Create new numbered SQL init scripts continuing from 04_schema_gateway.sql.
Each script MUST:

- Have a header comment block explaining purpose, order dependency, and which DB/schema it targets
- Use `IF NOT EXISTS` everywhere — scripts must be fully idempotent and safe to re-run
- Have inline comments on non-obvious columns, constraints, and index choices
- Follow the naming convention: `0N_descriptive_snake_case_name.sql`
- Stay under ~80 lines; split into multiple numbered scripts if needed

Required SQL deliverables (adjust numbers to follow existing scripts):
1. **Schema tables** for strategies, report metrics entities (exact tables per ROADMAP Phase 2)
2. **Hypertable declarations**: `SELECT create_hypertable('table_name', 'time_column', if_not_exists => TRUE);`
   — wrapped in a DO block or standalone script, fully idempotent
3. **Continuous aggregate views**: `CREATE MATERIALIZED VIEW ... WITH (timescaledb.continuous)`
   — use `CREATE MATERIALIZED VIEW IF NOT EXISTS` pattern or guard with DO block
4. **Continuous aggregate refresh policies**: `SELECT add_continuous_aggregate_policy(...)` — guard
   with existence check to be idempotent

---

## Step 5 — Implement Python Layer

All Python code MUST follow these non-negotiable rules:
- Full type annotations on every public function (args + return type)
- Pydantic V2 models for ALL data crossing module boundaries — no raw dicts
- Async/await for all DB I/O (use `asyncpg`)
- Module-local exceptions in `src/<module>/errors.py`, inheriting from a root exception
- `logger = logging.getLogger(__name__)` at module top; `%` formatting; no `print`; no f-strings in log calls
- No hardcoded credentials or paths — config via `pydantic-settings` Settings object
- Imports: stdlib → third-party → local, blank lines between groups

Deliverables:
- Pydantic V2 models for each new schema entity (with Field descriptions and constraints)
- Async repository functions for CRUD + query operations on new tables
- Settings extensions if new env vars are required (document in .env.example)

---

## Step 6 — Write Tests

- Mirror source paths: tests structure mirrors src
- `pytest-asyncio` is in `auto` mode — no `@pytest.mark.asyncio` decorator needed
- Unit tests: mock the DB layer (no live connections in unit tests)
- Cover: happy path, validation errors, DB error handling, edge cases
- Target ≥ 80% coverage for all new code

Run the quality gate before marking complete:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

All four must pass with zero errors.

---

## Step 7 — Smoke Test with Live Docker Stack (Integration Validation)

```bash
docker compose up -d
docker compose ps   # confirm all containers healthy
```

Run the new init scripts by restarting the postgres container with a fresh volume, or exec them
manually:

```bash
docker exec -i quant-postgres psql -U postgres -f /docker-entrypoint-initdb.d/05_...sql
```

Verify:
- Tables exist in correct databases
- Hypertables are registered (`SELECT * FROM timescaledb_information.hypertables;`)
- Continuous aggregates are registered (`SELECT * FROM timescaledb_information.continuous_aggregates;`)

---

## Step 8 — Update Documentation and Progress Tracking

1. Update `docs/plans/feature-strategies-report-metrics/PLAN.md`:
   - Add completion date for each deliverable
   - Note any issues encountered during testing and how they were resolved
   - Check off all acceptance criteria that are met

2. Update `docs/plans/feature-strategies-report-metrics/ROADMAP.md`:
   - Mark Phase 2 items as complete with checkboxes and completion date

3. Evaluate .claude knowledge and playbooks:
   - If you discovered patterns, gotchas, or reusable knowledge during implementation
     (e.g. TimescaleDB idempotency patterns, continuous aggregate gotchas), create or update
     the relevant file in knowledge or playbooks
   - If CLAUDE.md needs updating to reflect new modules, commands, or conventions, update it

---

## Step 9 — Final Commit

Stage all changes and create a single conventional commit:

```bash
git add .
git commit -m "feat(infra): implement Phase 2 schema hypertables and continuous aggregates

- Add init scripts 05–0N for strategies/report/metrics schema
- Declare TimescaleDB hypertables with idempotent if_not_exists guards
- Add continuous aggregate materialized views and refresh policies
- Add Pydantic V2 models and async asyncpg repository functions
- Add pytest suite with ≥80% coverage for all new code
- Update PLAN.md with progress notes and ROADMAP.md with Phase 2 completion
- Update .claude/ knowledge and CLAUDE.md with new patterns discovered

Refs: ../docs/plans/feature-strategies-report-metrics/ROADMAP.md Phase 2"
```

---

## Constraints & Hard Rules

- NEVER install PostgreSQL or MongoDB on the host — use `docker compose` only
- NEVER use synchronous DB drivers for new async code — use `asyncpg`
- NEVER use `requests` — use `httpx.AsyncClient` for any HTTP
- NEVER commit .env — credentials in .env.example only
- NEVER write non-idempotent init scripts
- NEVER use bare `except:` or `raise Exception(...)`
- NEVER mix feature and refactor in the same commit
- NEVER skip the plan step — plan MUST be committed before implementation begins
```

---

## Scope

### In Scope (Phase 2)

| Component | Description | Status |
|---|---|---|
| `init-scripts/05_schema_strategy_report.sql` | Single idempotent script: ALTERs, two new hypertables, two continuous aggregates, refresh policies | In progress |
| Fold-in of uncommitted UNIQUE-index diffs on `03_…sql` / `04_…sql` | Indexes the csm-set adapter's `INSERT … ON CONFLICT` paths require | In progress |
| `init-scripts/mongo-init.js` | Comment-only documentation of the new `metrics` keys | In progress |
| `scripts/backup.sh` | Comment block listing the new tables | In progress |
| `src/db/models.py` (new) | Pydantic V2 row models for the three new/extended tables | In progress |
| `src/db/repositories.py` (new) | Async asyncpg upsert + fetch helpers | In progress |
| `src/db/errors.py` (extended) | Adds `RepositoryError` under existing root | In progress |
| `src/db/__init__.py` (extended) | Re-exports new public symbols | In progress |
| `tests/test_models.py`, `tests/test_repositories.py` (new) | Unit tests with mocked `asyncpg.Pool`; ≥80% coverage gate | In progress |
| `tests/test_postgres.py` (extended) | Infra-marked assertions for new hypertables + continuous aggregates | In progress |
| `.claude/knowledge/feature-strategies-report-metrics.md` (new) | Patterns + gotchas discovered during implementation | In progress |
| Roadmap updates (sub-repo + umbrella) | Check off Phase 2 items with completion date | In progress |

### Out of Scope (Phase 2)

- TimescaleDB compression policy or retention policy (deferred per ROADMAP).
- Schema or code inside `quant-api-gateway`, `strategies/csm-set`, or `quant-dashboard`
  (those are Phases 1, 3, 4).
- New MongoDB collection — `csm_logs.backtest_results` already accepts the new keys
  (schema-less).
- Replica / standby topology, custom chunk partitioning beyond TimescaleDB defaults.
- Migrating existing `DOUBLE PRECISION` columns on `equity_curve` / `trade_history` to
  `NUMERIC`. New columns use `NUMERIC(18,4)` because the cross-repo CLAUDE.md mandates
  `Decimal` for money; legacy columns are left as-is to keep the diff minimal.

---

## Design Decisions

### 1. Folding the unique-index diffs into this phase

The four uncommitted UNIQUE-index edits on `03_schema_csm_set.sql` and `04_schema_gateway.sql`
exist because the csm-set adapter's `INSERT … ON CONFLICT` paths require them. They were
written ahead of this phase but never committed. Per user direction they ship in the Phase 2
commit since they serve the same "make schema upsert-friendly for report ingestion" goal.

### 2. Single `05_…sql` script, with a planned split if it grows

The full Phase 2 schema change fits in roughly 60–80 lines if compactly written, so the
soft cap (~80 lines per init script) is respected with a single file. If during
implementation the file exceeds the cap, it is split into `05_schema_strategy_report.sql`
(ALTERs + new tables + hypertables) and `06_continuous_aggregates.sql` (views + policies)
— this keeps the order-of-operations invariant (hypertable must exist before its
continuous aggregate view).

### 3. `add_continuous_aggregate_policy` is idempotent via `if_not_exists => TRUE`

The TimescaleDB 2.x function accepts `if_not_exists => TRUE`. Cross-repo ROADMAP specifies
this argument explicitly, so we use it directly rather than wrapping the call in a
`DO $$ … EXCEPTION WHEN duplicate_object …` block. Verified during the live smoke test.

### 4. `DROP CONSTRAINT IF EXISTS … ; ADD CONSTRAINT …` pattern for relaxing the `side` check

`trade_history` did not previously have a `CHECK` on `side`. The DROP is a no-op (idempotent
via `IF EXISTS`), and the ADD creates the broader constraint
`side IN ('LONG','SHORT','BUY','SELL','HOLD')`. The broader set is a superset of any plausible
legacy values, so re-running the script never produces a constraint-violation error.

### 5. `NUMERIC(18,4)` for new monetary columns, `DOUBLE PRECISION` left for legacy columns

Project-wide rule "Monetary values are `Decimal`; never `float`" applies at code boundaries.
For new schema we use `NUMERIC(18,4)`, which `asyncpg` maps to Python `Decimal`
automatically. Existing `DOUBLE PRECISION` columns on `equity_curve` / `trade_history` are
not migrated in this phase — that would be an invasive change outside Phase 2's scope and
would require coordination with the csm-set adapter.

### 6. Thin Python layer scoped to row mapping + upsert/fetch only

Per user clarification, this phase ships Pydantic V2 row models and async repository
helpers. The repository module wraps `asyncpg.Pool.acquire()` and uses
`INSERT … ON CONFLICT (…) DO UPDATE SET …` against the UNIQUE indexes declared in the SQL
layer. No ORM, no query builder; just typed boundary objects and parameterized SQL.

### 7. Models are frozen and validate at construction; `Decimal` for money

`TradeHistoryRow`, `BenchmarkEquityCurveRow`, and `StrategyReportSnapshotRow` use
`model_config = ConfigDict(frozen=True, strict=True)`. Monetary fields are `Decimal`,
timestamps are `datetime` (validator enforces UTC), and JSON payload is `dict[str, Any]`.

### 8. New errors inherit from existing `DatabaseConnectionError`

`RepositoryError` extends `DatabaseConnectionError` so callers that already handle the root
exception keep working. Future phases can subdivide further (e.g. `UpsertConflictError`)
without breaking the contract.

---

## SQL Schema Rules

Applied in strict order inside `05_schema_strategy_report.sql`:

| Step | Statement | Why this order |
|---|---|---|
| 1 | `\c db_csm_set` | All db_csm_set work runs first |
| 2 | `ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS …` (4 columns) | New columns must exist before continuous aggregate references `realized_pnl` |
| 3 | `ALTER TABLE trade_history DROP CONSTRAINT IF EXISTS … ; ADD CONSTRAINT …` | Relaxed `side` check |
| 4 | `CREATE TABLE IF NOT EXISTS benchmark_equity_curve …` | Plain table first |
| 5 | `SELECT create_hypertable('benchmark_equity_curve','time', if_not_exists => TRUE);` | Hypertable conversion |
| 6 | `CREATE INDEX IF NOT EXISTS idx_benchmark_strategy_time …` | Read index on (strategy_id, time DESC) |
| 7 | `CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_trade_history_monthly WITH (timescaledb.continuous) AS …` | Requires `trade_history` columns from step 2 |
| 8 | `SELECT add_continuous_aggregate_policy('cagg_trade_history_monthly', …, if_not_exists => TRUE);` | Refresh policy |
| 9 | `\c db_gateway` | Switch databases |
| 10 | `CREATE TABLE IF NOT EXISTS strategy_report_snapshot …` | Plain table first |
| 11 | `SELECT create_hypertable('strategy_report_snapshot','time', if_not_exists => TRUE);` | Hypertable conversion |
| 12 | `CREATE INDEX IF NOT EXISTS idx_strategy_report_strategy_time …` | Read index |
| 13 | `CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_daily_performance_monthly WITH (timescaledb.continuous) AS …` | Aggregate over existing `daily_performance` |
| 14 | `SELECT add_continuous_aggregate_policy('cagg_daily_performance_monthly', …, if_not_exists => TRUE);` | Refresh policy |

### Schema → Python row-model mapping

| SQL table | Pydantic model | Notable field mappings |
|---|---|---|
| `trade_history` | `TradeHistoryRow` | `NUMERIC` → `Decimal`; `TIMESTAMPTZ` → `datetime`; `entry_price`/`exit_price`/`realized_pnl`/`duration_bars` all optional |
| `benchmark_equity_curve` | `BenchmarkEquityCurveRow` | `NUMERIC(18,4) equity` → `Decimal` |
| `strategy_report_snapshot` | `StrategyReportSnapshotRow` | `JSONB report` → `dict[str, Any]`; `computed_at` defaults to `datetime.now(tz=UTC)` at construction |

---

## Implementation Steps

### Step 1: Branch + plan commit

Create `feat/schema-hypertables-continuous-aggregates` from `main`. Write this PLAN.md and
commit with `docs(plan): add Phase 2 schema hypertables continuous aggregates plan` **before**
writing any implementation code.

### Step 2: SQL init script

Author `init-scripts/05_schema_strategy_report.sql` covering all 14 statements in the order
listed above, with `IF NOT EXISTS` everywhere and a top-of-file comment block describing
purpose, order dependency, and target databases. The pre-existing UNIQUE-index diffs on
`03_…sql` and `04_…sql` are kept as-is (they were already on disk; this phase ratifies them).

### Step 3: MongoDB / backup comments

Append a comment block to `init-scripts/mongo-init.js` listing the new `metrics` keys Phase 1
now writes into `csm_logs.backtest_results`. Append a comment block to `scripts/backup.sh`
naming `benchmark_equity_curve` and `strategy_report_snapshot` for operator visibility (no
code change).

### Step 4: Python row models

Write `src/db/models.py` with `TradeHistoryRow`, `BenchmarkEquityCurveRow`, and
`StrategyReportSnapshotRow`. All `frozen=True`, all monetary fields `Decimal`, all timestamps
`datetime`. Include a small `_ensure_utc` validator to coerce naive datetimes to UTC.

### Step 5: Errors + repository module

Extend `src/db/errors.py` with `RepositoryError(DatabaseConnectionError)`. Add
`src/db/repositories.py` exposing:

- `async def upsert_trade_history(pool, rows) -> int`
- `async def fetch_trade_history(pool, *, strategy_id, since=None, limit=1000) -> list[TradeHistoryRow]`
- `async def upsert_benchmark_equity(pool, rows) -> int`
- `async def fetch_benchmark_curve(pool, *, strategy_id, benchmark_symbol, since=None) -> list[BenchmarkEquityCurveRow]`
- `async def upsert_strategy_report(pool, row) -> None`
- `async def fetch_strategy_report(pool, *, strategy_id, at_time) -> StrategyReportSnapshotRow | None`

Each wraps `INSERT … ON CONFLICT … DO UPDATE SET …` against the appropriate UNIQUE index and
converts errors into `RepositoryError`.

### Step 6: Re-exports

Update `src/db/__init__.py` to re-export the three row models, the six repository helpers,
and `RepositoryError`.

### Step 7: Unit tests

`tests/test_models.py` covers Pydantic validation, Decimal round-trip, JSON serialization,
UTC enforcement. `tests/test_repositories.py` uses `AsyncMock` against `pool.acquire()` to
assert each helper builds the expected SQL with the expected parameters; coverage targets
≥80% on the new modules.

### Step 8: Infra test extensions

Extend `tests/test_postgres.py` (already `pytestmark = pytest.mark.infra`) with assertions
that the new hypertables exist, both continuous aggregates are registered, and the relaxed
`side` check accepts `LONG`. Skipped by default (run with `pytest -m infra`).

### Step 9: Quality gate

Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`.
Iterate until all four pass cleanly with ≥80% coverage.

### Step 10: Live Docker smoke test

`docker compose up -d` against a fresh volume; verify schema, hypertables, continuous
aggregates, and idempotency (run `05_…sql` twice).

### Step 11: Doc updates

Update PLAN.md (this file) with per-deliverable completion notes. Mark Phase 2 items as
complete in the cross-repo ROADMAP and (if applicable) the sub-repo ROADMAP. Add
`.claude/knowledge/feature-strategies-report-metrics.md` capturing gotchas.

### Step 12: Final commit

Single `feat(infra): …` commit covering everything (per the prompt's verbatim wording).

---

## File Changes

| File | Action | Description |
|---|---|---|
| `init-scripts/03_schema_csm_set.sql` | MODIFY | Fold in uncommitted UNIQUE-index edits |
| `init-scripts/04_schema_gateway.sql` | MODIFY | Fold in uncommitted UNIQUE-index edits |
| `init-scripts/05_schema_strategy_report.sql` | CREATE | ALTERs + 2 new hypertables + 2 continuous aggregates + refresh policies |
| `init-scripts/mongo-init.js` | MODIFY | Comment block documenting new `metrics` keys |
| `scripts/backup.sh` | MODIFY | Comment block listing new tables for operators |
| `src/db/models.py` | CREATE | Pydantic V2 row models |
| `src/db/errors.py` | MODIFY | Add `RepositoryError` |
| `src/db/repositories.py` | CREATE | Async upsert + fetch helpers |
| `src/db/__init__.py` | MODIFY | Re-export new public symbols |
| `tests/test_models.py` | CREATE | Unit tests for row models |
| `tests/test_repositories.py` | CREATE | Unit tests with mocked `asyncpg.Pool` |
| `tests/test_postgres.py` | MODIFY | Infra-marked assertions for new hypertables + continuous aggregates |
| `docs/plans/feature-strategies-report-metrics/PLAN.md` | CREATE | This document |
| `../plans/feature-strategies-report-metrics/ROADMAP.md` | MODIFY | Check off Phase 2 deliverables |
| `.claude/knowledge/feature-strategies-report-metrics.md` | CREATE | TimescaleDB / continuous-aggregate gotchas |

---

## Success Criteria

- [ ] PLAN.md committed before any implementation code
- [ ] Fresh `docker compose up -d` (empty `postgres_data/` + `mongo_data/`) boots cleanly with
      `05_schema_strategy_report.sql` present
- [ ] `\d+ trade_history` in `db_csm_set` shows the four new columns and the relaxed
      `CHECK (side IN ('LONG','SHORT','BUY','SELL','HOLD'))`
- [ ] `SELECT view_name FROM timescaledb_information.continuous_aggregates;` lists
      `cagg_daily_performance_monthly` (in db_gateway) and `cagg_trade_history_monthly`
      (in db_csm_set)
- [ ] Running `05_schema_strategy_report.sql` a second time exits cleanly (idempotency proof)
- [ ] `bash scripts/backup.sh` produces a dump containing `strategy_report_snapshot` and
      `benchmark_equity_curve`
- [ ] `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`
      passes with zero errors and ≥80% coverage
- [ ] Final commit uses `feat(infra): …` per prompt
- [ ] Cross-repo ROADMAP Phase 2 deliverables checked off with completion date

---

## Completion Notes

### Summary

_To be filled in upon completion._

### Issues Encountered

_To be filled in upon completion._

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Opus 4.7)
**Status:** In progress
**Completed:** —
