# quant-infra-db — Overview

`quant-infra-db` is the database infrastructure layer for the Quant Trading system.
It provisions **PostgreSQL + TimescaleDB** and **MongoDB** through Docker Compose
on a shared Docker network `quant-network`, consumed by downstream strategy services
and the API Gateway.

## Architecture

```text
docker compose up -d
  └── quant-postgres  (timescale/timescaledb:latest-pg16)
  │     ├── db_csm_set   — equity_curve, trade_history, backtest_log
  │     └── db_gateway   — daily_performance, portfolio_snapshot
  └── quant-mongo    (mongo:latest)
        └── csm_logs — backtest_results, model_params, signal_snapshots
```

Both containers run on the external Docker bridge network `quant-network`, created
once per host:

```bash
docker network create quant-network
```

Downstream services reach databases by hostname (`quant-postgres`, `quant-mongo`),
not by IP address. Ports are exposed to the host (`5432`, `27017`) for local
development access only.

### Storage decisions

| Store | Engine | Purpose |
| --- | --- | --- |
| Time-series / equity data | PostgreSQL + TimescaleDB | Hypertables for `equity_curve`, `daily_performance`, `portfolio_snapshot`. Auto-partitioning by time, fast range queries. |
| Trade history | PostgreSQL | Relational table with indexes on `(strategy_id, time DESC)`. |
| Backtest params, logs, signals | MongoDB | Schema-less documents. Flexible JSON/BSON for varying backtest configs and signal shapes. |

## Data flow

```text
Strategy Services  ──→  quant-postgres  (db_csm_set)   — trade data, equity curves
                 │      quant-mongo     (csm_logs)      — backtest results, params, signals
                 │
API Gateway       ──→  quant-postgres  (db_gateway)    — aggregated daily performance
                                                         & portfolio snapshots
```

Strategy services **write** trade and equity data to `db_csm_set`, and log backtest
results, model parameters, and signal snapshots to `csm_logs`. The API Gateway
**reads** aggregated daily performance and portfolio snapshots from `db_gateway`.

## Key design decisions

**Async-first drivers.** All Python database I/O uses `asyncpg` (PostgreSQL) and
`motor` (MongoDB). Synchronous drivers (`psycopg2`, `pymongo`) are not used in
library code.

**Pydantic v2 at boundaries.** Configuration is loaded through a single
`pydantic-settings` `Settings` object. Database connection strings are computed
properties, never hard-coded.

**External Docker network.** `quant-network` is created once per host and shared
across all Quant Trading services. This avoids per-project network isolation and
enables hostname-based service discovery.

**Idempotent init scripts.** SQL scripts are numbered (`01_`, `02_`, ...) and use
`IF NOT EXISTS` everywhere. MongoDB init uses `db.createCollection()` which is
naturally idempotent. Scripts tolerate re-execution against a live database.

**TimescaleDB hypertables.** Time-series tables (`equity_curve`, `daily_performance`,
`portfolio_snapshot`) are converted to hypertables immediately after creation,
providing automatic time-based partitioning and optimized range queries.

**DOUBLE PRECISION over NUMERIC.** Chosen for performance on aggregate queries.
Precision is sufficient for financial calculations at this scale.

**Healthchecks on every service.** PostgreSQL uses `pg_isready`; MongoDB uses
`mongosh --eval "db.adminCommand('ping')"` (unauthenticated — `ping` is on
MongoDB's auth-bypass list, keeping credentials out of `docker inspect` output).

**Module-local exceptions.** Each subpackage defines its own exception classes in
`errors.py`, all inheriting from `DatabaseConnectionError`. No bare `raise
Exception(...)` anywhere.

## Python layer

The `src/` package is a thin connectivity layer (Phases 1–4). As the project grows,
Python services will follow a one-way module flow:

```text
External I/O  →  src/data        (fetch, normalize, persist)
              →  src/core        (business logic, computation)
              →  src/api         (HTTP endpoints)
              →  src/cli         (command-line entrypoints)
```

Entrypoint layers (`api/`, `cli/`, `main.py`) may import from `src/`; `src/`
modules must not import from entrypoint layers.

See [modules.md](modules.md) for the full module reference.

## Documentation map

| Document | Purpose |
| --- | --- |
| [overview.md](overview.md) | This page — architecture, data flow, design decisions |
| [usage.md](usage.md) | Setup, Docker commands, connection strings, backup/restore, troubleshooting |
| [modules.md](modules.md) | Python module reference, init scripts, operations scripts |
| [plans/ROADMAP.md](plans/ROADMAP.md) | Master roadmap with phase status and dependency map |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Contribution workflow, quality gates, commit conventions |
| [../CHANGELOG.md](../CHANGELOG.md) | Release changelog |
| [../SECURITY.md](../SECURITY.md) | Security policy and vulnerability reporting |
| [../.claude/knowledge/](../.claude/knowledge/) | AI agent knowledge base (architecture, standards, decisions) |

Phase-level design documents live in [plans/](plans/):

| Phase | Document |
| --- | --- |
| Phase 1 — Project Bootstrap | [plans/phase_1_project_bootstrap/](plans/phase_1_project_bootstrap/) |
| Phase 2 — PostgreSQL Setup | [plans/phase_2_postgre_db/phase_2_postgresql_setup.md](plans/phase_2_postgre_db/phase_2_postgresql_setup.md) |
| Phase 3 — MongoDB Setup | [plans/phase_3_mongodb/phase_3_mongodb_setup.md](plans/phase_3_mongodb/phase_3_mongodb_setup.md) |
| Phase 4 — Operations & Health Check | [plans/phase_4_operations_health_check/phase_4_operations_health_check.md](plans/phase_4_operations_health_check/phase_4_operations_health_check.md) |
