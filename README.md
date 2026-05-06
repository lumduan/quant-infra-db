# quant-infra-db

> Database infrastructure layer for the Quant Trading system — PostgreSQL + TimescaleDB + MongoDB via Docker Compose.

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)
[![Docker Publish](https://github.com/OWNER/REPO/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/docker-publish.yml)
[![Security Scan](https://github.com/OWNER/REPO/actions/workflows/security.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/security.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`quant-infra-db` provisions **PostgreSQL + TimescaleDB** and **MongoDB** through Docker Compose
on a shared Docker network `quant-network`, consumed by downstream strategy services
and the API Gateway.

> Full roadmap: [docs/plans/ROADMAP.md](docs/plans/ROADMAP.md)

## Architecture

```
docker compose up -d
  └── quant-postgres  (timescale/timescaledb:latest-pg16)
  │     ├── db_csm_set   — equity_curve, trade_history, backtest_log
  │     └── db_gateway   — daily_performance, portfolio_snapshot
  └── quant-mongo    (mongo:latest)
        └── csm_logs — backtest_results, model_params, signal_snapshots
```

All containers join the external network `quant-network` (created once per host).
Downstream services reach databases by hostname (`quant-postgres`, `quant-mongo`),
not by IP address.

## Prerequisites

- Docker Engine >= 24 with Docker Compose v2 (`docker compose`, not legacy `docker-compose`)
- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) >= 0.4
- >= 4 GB free RAM, >= 5 GB free disk

## Quick start

```bash
# 1. Clone
git clone https://github.com/OWNER/REPO.git
cd REPO

# 2. Create the shared Docker network (one-time per host)
docker network create quant-network

# 3. Configure credentials
cp .env.example .env
# Edit .env and set a strong POSTGRES_PASSWORD

# 4. Start the stack
docker compose up -d

# 5. Verify health
docker compose ps
# Both quant-postgres and quant-mongo should show (healthy)
```

## Connection strings

### Within quant-network (service-to-service)

```
# CSM-SET → PostgreSQL
postgresql://postgres:<pass>@quant-postgres:5432/db_csm_set

# Gateway → PostgreSQL
postgresql://postgres:<pass>@quant-postgres:5432/db_gateway

# CSM-SET logs → MongoDB
mongodb://quant-mongo:27017/csm_logs
```

### From the host (development)

```
# PostgreSQL
postgresql://postgres:<pass>@localhost:5432/db_csm_set
postgresql://postgres:<pass>@localhost:5432/db_gateway

# MongoDB
mongodb://localhost:27017/csm_logs
```

Replace `<pass>` with the value of `POSTGRES_PASSWORD` from your `.env` file.

## Python connectivity

```bash
# Install dependencies
uv sync --all-groups

# Run the connectivity smoke test
uv run python -m src.main
```

Example usage in code:

```python
from src.config import Settings
from src.db import create_postgres_pool, check_postgres_health, close_postgres_pool

settings = Settings()
pool = await create_postgres_pool(settings.csm_set_dsn)
healthy = await check_postgres_health(pool)
await close_postgres_pool(pool)
```

## Testing

```bash
# Unit tests (no Docker required)
uv run pytest tests/test_config.py -v

# Integration tests (requires healthy Docker Compose stack)
uv run pytest tests/test_postgres.py tests/test_mongo.py tests/test_infra.py -v

# Full test suite (integration tests skipped if Docker unavailable)
uv run pytest -v
```

Coverage must stay >= 80%. The threshold is enforced in CI and in `pyproject.toml`.

## Quality gate

```bash
uv run ruff check .               # Lint
uv run ruff format --check .      # Format check
uv run mypy src tests             # Type check
uv run pytest                     # Tests + coverage
```

Run all together:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

## Backup and restore

```bash
# Create a backup (PostgreSQL + MongoDB)
bash scripts/backup.sh

# Backups are written to ./backups/ (gitignored)
ls -la backups/
```

Backups include:

- `pg_all_<timestamp>.sql` — full PostgreSQL dump (`pg_dumpall`)
- `mongo_<timestamp>/` — MongoDB dump (`mongodump`)

Recommended schedule: daily, before automated model runs.

## Docker Compose commands

```bash
docker compose up -d          # start the full stack
docker compose ps             # check status (should show healthy)
docker compose down           # stop (preserves data volumes)
docker compose down -v        # stop and destroy volumes (fresh start)
docker compose logs -f         # tail logs
docker exec -it quant-postgres psql -U postgres   # interactive psql
docker exec -it quant-mongo mongosh                # interactive mongosh
```

## Directory structure

```text
.
├── docker-compose.yml              # PostgreSQL + MongoDB core services
├── init-scripts/                   # Run on first container start
│   ├── 01_create_databases.sql
│   ├── 02_enable_timescaledb.sql
│   ├── 03_schema_csm_set.sql
│   ├── 04_schema_gateway.sql
│   └── mongo-init.js
├── scripts/
│   └── backup.sh                   # Backup PostgreSQL + MongoDB
├── .env.example                    # Credentials template
├── src/                            # Python source (connectivity layer)
├── tests/                          # pytest suite
├── docs/
│   └── plans/
│       └── ROADMAP.md              # Master roadmap
├── .claude/                        # AI agent context & playbooks
├── .github/                        # CI/CD workflows, issue/PR templates
├── pyproject.toml                  # uv project config + tool settings
├── uv.lock                         # Locked dependency versions
└── README.md
```

## Security scanning

```bash
# Static analysis for common Python security issues
uv run bandit -r src

# Check dependencies for known CVEs
uv run pip-audit
```

Both run automatically on a weekly CI schedule (`.github/workflows/security.yml`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contribution guide,
conventional commit format, and quality gate expectations.

## License

MIT — see [LICENSE](LICENSE) for details.
