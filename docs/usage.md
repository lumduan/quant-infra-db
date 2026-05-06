# Usage Guide

How to set up, operate, and troubleshoot the `quant-infra-db` stack.

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

## Docker Compose commands

```bash
docker compose up -d          # start the full stack
docker compose ps             # check status (should show healthy)
docker compose down           # stop (preserves data volumes)
docker compose down -v        # stop and destroy volumes (fresh start)
docker compose logs -f         # tail logs
docker compose restart         # restart all services

# Interactive database shells
docker exec -it quant-postgres psql -U postgres   # PostgreSQL
docker exec -it quant-mongo mongosh                # MongoDB
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
For MongoDB auth, include credentials in the URI:
`mongodb://admin:<pass>@localhost:27017/csm_logs`.

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

See [modules.md](modules.md) for the full API reference.

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

Each service has a healthcheck probe that runs every 30s with a 10s timeout,
3 retries, and a 10s start period.

| Service | Probe | Authenticated? |
|---|---|---|
| `quant-postgres` | `pg_isready -U postgres` | No |
| `quant-mongo` | `mongosh --eval "db.adminCommand('ping')"` | No |

The MongoDB healthcheck deliberately runs unauthenticated. `db.adminCommand('ping')`
is on MongoDB's auth-bypass list and returns `{ ok: 1 }` even with auth enabled,
keeping credentials out of `docker inspect` output. The auth path is exercised
separately by `scripts/backup.sh` and `scripts/restore.sh`.

```bash
# Quick status check
docker compose ps
# NAME             STATUS
# quant-postgres   Up X minutes (healthy)
# quant-mongo      Up X minutes (healthy)

# Detailed health status
docker inspect --format '{{.State.Health.Status}}' quant-postgres   # → healthy
docker inspect --format '{{.State.Health.Status}}' quant-mongo      # → healthy
```

## Backup

```bash
# Create a timestamped backup of PostgreSQL + MongoDB
bash scripts/backup.sh
```

Artefacts land in `./backups/` (gitignored):

- `pg_all_<UTC-timestamp>.sql` — full PostgreSQL dump (`pg_dumpall --clean --if-exists`)
- `mongo_<UTC-timestamp>/` — MongoDB dump (`mongodump`)

The script:

- Sources `.env` for `POSTGRES_PASSWORD`, `MONGO_INITDB_ROOT_USERNAME`,
  `MONGO_INITDB_ROOT_PASSWORD` and fails fast if any are missing.
- Refuses to run if either container is not reporting `healthy`.
- Removes partial artefacts on error via an `ERR` trap, so the `backups/` directory
  never accumulates corrupt dumps.
- Resolves the output directory from the script's location, so it works under
  `cron`, CI, or any working directory.

Recommended schedule: daily, before automated model runs. Retention is the
operator's responsibility.

## Restore

> **Destructive operation.** A restore drops `db_csm_set` / `db_gateway` and their
> contents, then replays the dump. MongoDB collections are dropped per
> `mongorestore --drop`.

```bash
# 1. List available backups
bash scripts/restore.sh --list

# 2. Restore both engines (interactive confirmation)
bash scripts/restore.sh --force 20260506_134812Z

# 3. Restore only one engine
bash scripts/restore.sh --postgres-only --force 20260506_134812Z
bash scripts/restore.sh --mongo-only    --force 20260506_134812Z

# 4. Non-interactive mode (cron, CI)
RESTORE_CONFIRM=restore bash scripts/restore.sh --force 20260506_134812Z
```

The script enforces three guardrails before touching data:

1. Both target containers must report `healthy`.
2. Non-empty target databases require `--force`.
3. With `--force` and a TTY, the operator must type `restore`. With no TTY,
   `RESTORE_CONFIRM=restore` must be set in the environment.

## Security scanning

```bash
uv run bandit -r src         # Static analysis for Python security issues
uv run pip-audit             # Check dependencies for known CVEs
```

Both run automatically on a weekly CI schedule (`.github/workflows/security.yml`).

## Troubleshooting

### `docker compose up` fails with "network quant-network not found"

Create the external network first:

```bash
docker network create quant-network
```

### Containers start but show `(unhealthy)`

Check logs for startup errors:

```bash
docker compose logs quant-postgres
docker compose logs quant-mongo
```

Common causes: port conflicts (another PostgreSQL/MongoDB on 5432/27017), stale
volumes, or missing `.env` variables.

### Init scripts didn't run

Init scripts in `/docker-entrypoint-initdb.d/` only execute on **first** container
start, when the data volume is empty. To force re-initialization:

```bash
docker compose down -v    # destroys data volumes
docker compose up -d      # recreates volumes, re-runs init scripts
```

### MongoDB connection refused despite healthy container

If `MONGO_INITDB_ROOT_USERNAME` and `MONGO_INITDB_ROOT_PASSWORD` are set in `.env`,
MongoDB enables authentication. The healthcheck ping works without auth, but
application connections must include credentials in the URI.

### Port 5432 or 27017 already in use

Stop the conflicting service, or override ports in `.env`:

```env
POSTGRES_PORT=5433
MONGO_PORT=27018
```

Then update `docker-compose.yml` port mappings to use the variables.

### Backup script fails with "container not healthy"

Ensure both containers are fully started and healthy:

```bash
docker compose ps    # both must show (healthy)
```

If a container just started, wait for the healthcheck to pass (up to 30s after
the start period).
