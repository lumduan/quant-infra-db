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

## Healthcheck verification

The Docker Compose definition wires healthchecks for both services. Each probe runs every
30s with a 10s timeout, allows 3 retries before flipping to `unhealthy`, and grants a 10s
`start_period` after container start.

- `quant-postgres` — `pg_isready -U postgres`
- `quant-mongo` — `mongosh --eval "db.adminCommand('ping')"`

Confirm both containers report `healthy`:

```bash
docker compose ps
# NAME             STATUS                       
# quant-postgres   Up X minutes (healthy)       
# quant-mongo      Up X minutes (healthy)       

docker inspect --format '{{.State.Health.Status}}' quant-postgres   # → healthy
docker inspect --format '{{.State.Health.Status}}' quant-mongo      # → healthy
```

The MongoDB healthcheck deliberately runs unauthenticated. `db.adminCommand('ping')` is on
MongoDB's auth-bypass list and returns `{ ok: 1 }` even with auth enabled, which keeps the
healthcheck command free of plaintext credentials in `docker inspect` output. The auth path
itself is exercised by `scripts/backup.sh` and `scripts/restore.sh`, which use the
`MONGO_INITDB_ROOT_*` credentials from `.env`.

## Backup

```bash
# Create a timestamped backup of PostgreSQL + MongoDB
bash scripts/backup.sh
```

Artefacts land in `./backups/` (gitignored):

- `pg_all_<UTC-timestamp>.sql` — full PostgreSQL dump (`pg_dumpall --clean --if-exists`)
- `mongo_<UTC-timestamp>/` — MongoDB dump (`mongodump --authenticationDatabase admin`)

The script:

- Sources `.env` for `POSTGRES_PASSWORD`, `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`
  and fails fast if any are missing.
- Refuses to run if either container is not reporting `healthy`.
- Removes partial artefacts on error via an `ERR` trap, so the `backups/` directory never
  accumulates corrupt dumps.
- Resolves the output directory from the script's location, so it works under `cron`, CI,
  or any working directory.

Recommended schedule: daily, before automated model runs. Retention is the operator's
responsibility (e.g. add `find backups/ -mtime +14 -delete` to a cron); the script does not
auto-prune.

## Restore

> **Destructive operation.** A restore drops `db_csm_set` / `db_gateway` and their
> contents, then replays the dump. MongoDB collections are dropped per `mongorestore --drop`.

```bash
# 1. List available backups
bash scripts/restore.sh --list
# 20260506_134812Z  postgres+mongo
# 20260505_134801Z  postgres+mongo

# 2. Restore both engines from a timestamp
bash scripts/restore.sh --force 20260506_134812Z
# Prompts: "Type 'restore' to proceed"

# 3. Restore only one engine (handy when a partial restore failed and you need
#    to retry just one side; cross-engine atomicity is not provided)
bash scripts/restore.sh --postgres-only --force 20260506_134812Z
bash scripts/restore.sh --mongo-only    --force 20260506_134812Z

# 4. Non-interactive (cron, CI): bypass the confirmation prompt explicitly
RESTORE_CONFIRM=restore bash scripts/restore.sh --force 20260506_134812Z
```

The script enforces three guardrails before touching data:

1. Both target containers must report `healthy`.
2. Non-empty target databases require `--force`.
3. With `--force` and a TTY, the operator must type `restore`. With no TTY (cron, CI),
   `RESTORE_CONFIRM=restore` must be set in the environment.

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
│   ├── backup.sh                   # Backup PostgreSQL + MongoDB
│   └── restore.sh                  # Restore from a timestamped backup
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
