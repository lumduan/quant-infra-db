# Phase 2: PostgreSQL & TimescaleDB Setup

**Feature:** PostgreSQL Logical Databases, TimescaleDB Extension, and Initial Schema
**Branch:** `feature/phase-2-postgresql-setup`
**Created:** 2026-05-06
**Status:** Complete
**Completed:** 2026-05-06
**Depends On:** Phase 1 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [Scope](#scope)
3. [Design Decisions](#design-decisions)
4. [Database Schema](#database-schema)
5. [Implementation Steps](#implementation-steps)
6. [File Changes](#file-changes)
7. [Success Criteria](#success-criteria)
8. [Verification](#verification)
9. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 2 provisions two logical PostgreSQL databases (`db_csm_set`, `db_gateway`), enables the
TimescaleDB extension in both, and creates the initial table schema including hypertables and
indexes for time-series data.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — Phase 2 sections 2.1–2.4

### Key Deliverables

1. **`init-scripts/01_create_databases.sql`** — Idempotent database creation via psql `\gexec`
2. **`init-scripts/02_enable_timescaledb.sql`** — TimescaleDB extension in both databases
3. **`init-scripts/03_schema_csm_set.sql`** — `equity_curve`, `trade_history`, `backtest_log`
4. **`init-scripts/04_schema_gateway.sql`** — `daily_performance`, `portfolio_snapshot`
5. **`tests/test_postgres.py`** — Integration tests for connectivity, extensions, hypertables, schema

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `01_create_databases.sql` | Idempotent creation of `db_csm_set` and `db_gateway` | Complete |
| `02_enable_timescaledb.sql` | Enable TimescaleDB extension in both databases | Complete |
| `03_schema_csm_set.sql` | Tables: `equity_curve` (hypertable), `trade_history`, `backtest_log` | Complete |
| `04_schema_gateway.sql` | Tables: `daily_performance` (hypertable), `portfolio_snapshot` (hypertable) | Complete |
| Idempotency hardening | All scripts use `IF NOT EXISTS`, `if_not_exists => TRUE`, or `\gexec` | Complete |
| Integration tests | Connectivity, extension presence, hypertables, table and column validation | Complete |
| Schema documentation | ROADMAP.md updated to match actual implementation | Complete |

### Out of Scope

- MongoDB collections and indexes (Phase 3)
- Health check configuration (Phase 4)
- Backup scripts (Phase 4)
- Python connectivity layer beyond existing smoke tests

---

## Design Decisions

### 1. Idempotent database creation via `\gexec`

PostgreSQL does not support `CREATE DATABASE IF NOT EXISTS`. The project uses psql's `\gexec`
meta-command, which sends the result of a SELECT as a SQL command to the server. When the
database already exists, `WHERE NOT EXISTS` returns no rows and no `CREATE` is attempted.

Alternatives considered and rejected:
- **PL/pgSQL `EXCEPTION WHEN duplicate_database`**: Swallows all errors silently, not just the
  duplicate case.
- **dblink extension**: Requires installing an extension first, adds unnecessary complexity.
- **`\gexec`**: Available since PostgreSQL 9.6 — the project uses pg16. Clean, no dependencies.

### 2. `DOUBLE PRECISION` over `NUMERIC`

All numeric columns use `DOUBLE PRECISION` (IEEE 754 64-bit float) rather than `NUMERIC`
(arbitrary precision). This is appropriate for financial time-series where:
- 15–17 significant digits are sufficient for P&L calculations
- Floating-point arithmetic is significantly faster for aggregate queries
- TimescaleDB compression works better with fixed-width types

### 3. `equity` over `nav`

The `equity_curve` table uses the column name `equity` rather than `nav` (Net Asset Value).
"Equity" is semantically broader — it encompasses total account value (open positions + cash),
while NAV is fund-specific. This naming accommodates both single-strategy and portfolio-level
equity tracking.

### 4. `daily_return` + `cumulative_return` over `daily_pnl`

The `daily_performance` table separates daily delta (`daily_return`) from running total
(`cumulative_return`). This avoids recomputing cumulative values from daily P&L and allows
independent validation of each metric.

### 5. Schema split: `03_` (CSM-SET) and `04_` (Gateway)

Scripts are numbered by domain and dependency order:
- `01_` — Databases (no dependencies)
- `02_` — Extensions (depends on databases)
- `03_` — CSM-SET schema (depends on extensions)
- `04_` — Gateway schema (depends on extensions)

Docker runs init scripts alphabetically on first container start.

### 6. Named indexes

All indexes use explicit names (`idx_equity_curve_strategy_time`, etc.) rather than
auto-generated names. This makes index management, monitoring, and migration scripts
more readable and deterministic.

---

## Database Schema

### `db_csm_set`

| Table | Type | Key columns | Description |
|---|---|---|---|
| `equity_curve` | Hypertable (time) | `time`, `strategy_id`, `equity` | Daily equity per strategy |
| `trade_history` | Regular | `id`, `time`, `strategy_id`, `symbol`, `side`, `quantity`, `price` | Every executed trade |
| `backtest_log` | Regular | `id`, `run_id` (unique), `strategy_id`, `started_at`, `config`, `summary` | Backtest run metadata |

### `db_gateway`

| Table | Type | Key columns | Description |
|---|---|---|---|
| `daily_performance` | Hypertable (time) | `time`, `strategy_id`, `daily_return`, `cumulative_return`, `sharpe_ratio` | Daily per-strategy performance |
| `portfolio_snapshot` | Hypertable (time) | `time`, `total_portfolio`, `weighted_return`, `allocation` | Cross-strategy combined snapshot |

---

## Implementation Steps

### Step 1: Harden `01_create_databases.sql`

Replaced bare `CREATE DATABASE` statements with the `\gexec` idempotent pattern.

### Step 2: Update ROADMAP.md

Corrected all Phase 2 SQL code blocks to match the actual init scripts:
- `equity` not `nav`, `daily_return` + `cumulative_return` not `daily_pnl`
- `DOUBLE PRECISION` not `NUMERIC`
- Added `IF NOT EXISTS`, `if_not_exists => TRUE`, named indexes

### Step 3: Create Phase 2 plan document

This file. Records design decisions, schema reference, and verification steps.

### Step 4: Quality gate

All four quality gate commands pass: ruff check, ruff format, mypy, pytest.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `init-scripts/01_create_databases.sql` | MODIFY | Idempotent via `\gexec` pattern |
| `docs/plans/ROADMAP.md` | MODIFY | Schema blocks corrected to match actual init scripts; status updated |
| `docs/plans/phase_2_postgre_db/phase_2_postgresql_setup.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `docker compose up -d` → both containers healthy
- [x] `db_csm_set` and `db_gateway` exist
- [x] TimescaleDB extension enabled in both databases
- [x] `equity_curve`, `daily_performance`, `portfolio_snapshot` are hypertables
- [x] All five tables present with correct columns
- [x] Named indexes present on all time-series tables
- [x] All init scripts are idempotent (re-runnable without error)
- [x] `uv run pytest -v` passes
- [x] `uv run ruff check .` passes
- [x] `uv run mypy src tests` passes

---

## Verification

### Docker Compose

```bash
docker compose down -v       # fresh start
docker compose up -d         # bring up stack
docker compose ps            # both services (healthy)
```

### Database verification

```bash
# List databases
docker exec -it quant-postgres psql -U postgres -l

# Check TimescaleDB extension
docker exec -it quant-postgres psql -U postgres -d db_csm_set \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';"
docker exec -it quant-postgres psql -U postgres -d db_gateway \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';"

# List hypertables
docker exec -it quant-postgres psql -U postgres -d db_csm_set \
  -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
docker exec -it quant-postgres psql -U postgres -d db_gateway \
  -c "SELECT hypertable_name FROM timescaledb_information.hypertables;"
```

### Test suite

```bash
uv run pytest tests/test_postgres.py tests/test_infra.py -v
```

### Quality gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

---

## Completion Notes

### Summary

Phase 2 was already functionally complete — init scripts existed and tests passed. This phase
focused on hardening (idempotency for `01_create_databases.sql`) and documentation (correcting
ROADMAP.md schema blocks to match actual implementation, creating this plan document).

### Issues Encountered

1. **`01_create_databases.sql` was not idempotent** — The original script used bare
   `CREATE DATABASE` which fails on re-run. Fixed with the `\gexec` pattern. PostgreSQL
   does not support `CREATE DATABASE IF NOT EXISTS`, so conditional execution via psql
   meta-commands is the standard approach.

2. **ROADMAP.md schema drift** — The roadmap specified different column names (`nav` vs
   `equity`, `daily_pnl` vs `daily_return` + `cumulative_return`) and types (`NUMERIC` vs
   `DOUBLE PRECISION`) compared to the actual init scripts. The code was treated as
   authoritative per project guidance and the roadmap was updated to match.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Code)
**Status:** Complete
**Completed:** 2026-05-06
