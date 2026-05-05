# Stack Decisions

Why each tool was chosen. One-liner per decision; rationale captures the trade-off.

## Database Infrastructure

- **Docker Compose** — single-command reproducible stack; no host-level database installs. Trade-off: adds Docker as a dependency on every developer machine.
- **PostgreSQL 16** — battle-tested relational database; strong SQL standard compliance; rich extension ecosystem. Trade-off: heavier than SQLite for very small datasets.
- **TimescaleDB** — hypertable auto-partitioning on time columns; time-series queries (range, downsampling, continuous aggregates) without manual partition management. Trade-off: adds a startup extension to every logical database.
- **MongoDB** — schema-less document store for backtest configs, model parameters, and signal snapshots where shape varies per strategy. Trade-off: no joins; denormalization required.
- **`quant-network` (Docker bridge)** — containers communicate by hostname, not IP. One network shared by all strategy services and the API Gateway. Trade-off: external network must be created once per host.

## Package & Runtime

- **uv** — fastest resolver, deterministic locks, single binary. Replaces pip / poetry / conda. Trade-off: newer than poetry, smaller community knowledge base.
- **Python 3.11+** — required for typing improvements (`Self`, better generics) and asyncio performance gains. Trade-off: forecloses use on older infra.

## Web / API (when applicable)

- **FastAPI** — async-native, OpenAPI for free, Pydantic-native, mature. Trade-off: opinionated about Pydantic versions; we accept that as a feature.
- **uvicorn** — lightweight ASGI server, official FastAPI pairing.

## Data (Python layer, when applicable)

- **pandas + PyArrow / Parquet** — columnar storage for structured data, zero-copy interop, fast partitioned reads.
- **numpy** — numeric foundation under pandas.

## Python Database Drivers

- **psycopg2** — PostgreSQL adapter for Python connectivity smoke tests and any future adapters. Trade-off: sync; consider `asyncpg` if async DB access is needed.
- **pymongo** — official MongoDB driver for Python connectivity tests.

## Validation / Config

- **pydantic v2** — speed + ergonomics for data validation.
- **pydantic-settings** — env-driven config; no hidden globals.

## HTTP

- **httpx** — async HTTP everywhere. `requests` is forbidden in library code (sync, blocks the event loop).

## Quality Tooling

- **pytest + pytest-asyncio** — standard, mature, async-native.
- **mypy** — strict type checking on `src/`.
- **ruff** — single tool replaces flake8 + isort + black; fast.
- **pre-commit** — local quality gate before commit.
- **bandit** — static analysis for common Python security issues.
- **pip-audit** — dependency CVE scanning.

## Containerization

- **Docker** — multi-stage builds, reproducible runtime, CI/CD ready.
- **Python slim images** — small attack surface, fast pulls.

## What We Deliberately Don't Use

- `requests` — sync; replaced by `httpx`.
- `poetry` / `pip-tools` — replaced by `uv`.
- `conda` / `mamba` — replaced by `uv`.
- `flake8` / `isort` / `black` — replaced by `ruff`.
- Host-installed PostgreSQL or MongoDB — use Docker Compose instead.

---

> Update this document when adding or removing a significant dependency.
> Keep entries short — name, one-line reason, one-line trade-off.
