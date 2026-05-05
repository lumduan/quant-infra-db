# Architecture

`quant-infra-db` is a Docker Compose-based database infrastructure stack for the Quant Trading system. This document describes the topology, data flow, and structural conventions.

## Stack overview

```
docker compose up -d
  └── quant-postgres  (timescale/timescaledb:latest-pg16)
  │     ├── db_csm_set   — equity_curve, trade_history, backtest_log
  │     └── db_gateway   — daily_performance, portfolio_snapshot
  └── quant-mongo    (mongo:latest)
        └── csm_logs — backtest_results, model_params, signal_snapshots
```

Both containers run on the external Docker network `quant-network`, created once per host:

```bash
docker network create quant-network
```

Downstream services (strategy services, API Gateway) reach databases by hostname (`quant-postgres`, `quant-mongo`), not by IP address.

## Data flow

```
Strategy Services  ──→  quant-postgres  (db_csm_set)   — trade data, equity curves
                 │      quant-mongo     (csm_logs)      — backtest results, params, signals
                 │
API Gateway       ──→  quant-postgres  (db_gateway)    — aggregated daily performance
                                                         & portfolio snapshots
```

Data flows **into** the databases from strategy services (writers) and **out to** the API Gateway (reader of `db_gateway`). Strategy services also read their own data back from `db_csm_set` and `csm_logs`.

## Top-level layout

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Core services definition (PostgreSQL + MongoDB). |
| `init-scripts/` | SQL and JS scripts that Docker runs on first container start. Numbered for ordering. |
| `scripts/` | Utility scripts (`backup.sh`, connectivity smoke tests). |
| `src/` | Thin Python package — connectivity clients, any future adapters. |
| `tests/` | pytest suite mirroring `src/` structure. |
| `docs/` | Design docs, plans, architecture decisions. |
| `.claude/` | Agent, knowledge, memory, playbook, and template config. |
| `.github/` | CI/CD workflows, issue/PR templates. |

## Module boundaries (Python layer)

When Python services or adapters are added, the one-way data flow applies:

```
External I/O  →  src/data        (fetch, normalize, persist — e.g. psycopg2, pymongo)
              →  src/core        (business logic, computation)
              →  src/api         (expose results over HTTP, if applicable)
              →  src/cli         (command-line entrypoints, if applicable)
```

Direction is one-way: lower layers must not import from higher ones. Application entrypoints (`api/`, `cli/`, `main.py`) may import `src/`; `src/` modules must not import from entrypoint layers.

## Storage decisions

| Store | Engine | Purpose |
|---|---|---|
| Time-series / equity data | PostgreSQL + TimescaleDB | Hypertables for `equity_curve`, `daily_performance`, `portfolio_snapshot`. Auto-partitioning by time, fast range queries. |
| Trade history | PostgreSQL | Relational table with indexes on `(strategy_id, time DESC)`. |
| Backtest params, logs, signals | MongoDB | Schema-less documents. Flexible JSON/BSON for varying backtest configs and signal shapes. |
| Python-side columnar workloads | Parquet (PyArrow) | For any future analytical workloads that benefit from columnar reads. |

Partition large datasets by date or key where read patterns benefit. Document any new storage choice in `docs/` with the rationale.

## Configuration

- Database credentials via `.env` (gitignored); `.env.example` provides the template.
- `docker-compose.yml` reads `${POSTGRES_PASSWORD}` from the environment.
- For Python-side config: use `pydantic-settings` for validated, typed settings. No hard-coded paths — base paths come from a single `Settings` object.
- Sensible defaults for local development; override in production via env.

## Cross-cutting conventions

- All Python I/O is async at boundaries; sync internal compute is fine.
- Errors: module-specific exceptions defined in each subpackage's `errors.py`, inheriting from a single root exception.
- Logging: `logging.getLogger(__name__)`; no `print` in library code.
- Time zone: always store as UTC (PostgreSQL `TIMESTAMPTZ`); localize at presentation boundaries only.
- Docker healthchecks are required on every service definition.
- Init scripts are numbered and idempotent — they must tolerate being re-run.
