# Module Reference

API documentation for the Python connectivity layer, init scripts, and operations
scripts.

## `src/config.py` — Settings

Configuration via `pydantic-settings`, loaded from environment variables and `.env`.

```python
from src.config import Settings

settings = Settings()  # _env_file = ".env", _env_file_encoding = "utf-8"
```

### Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `postgres_password` | `SecretStr` | (required) | PostgreSQL superuser password |
| `postgres_host` | `str` | `"localhost"` | PostgreSQL hostname |
| `postgres_port` | `int` | `5432` | PostgreSQL port |
| `postgres_user` | `str` | `"postgres"` | PostgreSQL user |
| `mongo_host` | `str` | `"localhost"` | MongoDB hostname |
| `mongo_port` | `int` | `27017` | MongoDB port |
| `mongo_username` | `str` | `""` | MongoDB root username (optional) |
| `mongo_password` | `SecretStr` | `""` | MongoDB root password (optional) |

### Computed properties

```python
@property
def csm_set_dsn(self) -> str:
    """Connection string for the db_csm_set database."""

@property
def gateway_dsn(self) -> str:
    """Connection string for the db_gateway database."""

@property
def mongo_uri(self) -> str:
    """MongoDB URI. Includes auth credentials only when both
    mongo_username and mongo_password are non-empty."""
```

### Validators

- `postgres_password` must not be empty — raises `ValueError` if blank.

### Notes

- `Settings` is frozen (`model_config = {"frozen": True}`) — fields cannot be
  mutated after construction.
- `SecretStr` values are masked in `repr()` output.

## `src/db/postgres.py` — PostgreSQL Module

Async PostgreSQL operations using `asyncpg`.

```python
from src.db import (
    create_postgres_pool,
    check_postgres_health,
    close_postgres_pool,
)
```

### `create_postgres_pool(dsn: str) -> asyncpg.Pool`

Create an asyncpg connection pool.

- **Args:** `dsn` — PostgreSQL connection string.
- **Returns:** `asyncpg.Pool` with `min_size=1, max_size=4`.
- **Raises:** `PostgresConnectionError` if pool creation fails.

### `check_postgres_health(pool: asyncpg.Pool) -> bool`

Check PostgreSQL health by executing `SELECT 1`.

- **Args:** `pool` — an active asyncpg connection pool.
- **Returns:** `True` if the query returns `1`, `False` on any error.
- **Does not raise** — failures are caught and return `False`.

### `close_postgres_pool(pool: asyncpg.Pool) -> None`

Gracefully close the connection pool.

- **Args:** `pool` — an asyncpg pool to close.

## `src/db/mongo.py` — MongoDB Module

Async MongoDB operations using `motor` (async driver).

```python
from src.db import (
    create_mongo_client,
    check_mongo_health,
    close_mongo_client,
)
```

### `create_mongo_client(uri: str) -> AsyncIOMotorClient`

Create a Motor async MongoDB client.

- **Args:** `uri` — MongoDB connection URI.
- **Returns:** `AsyncIOMotorClient`.

### `check_mongo_health(client: AsyncIOMotorClient) -> bool`

Check MongoDB health via `admin.command("ping")`.

- **Args:** `client` — an active Motor client.
- **Returns:** `True` if ping returns `ok == 1.0`.
- **Raises:** `MongoConnectionError` on failure.

### `close_mongo_client(client: AsyncIOMotorClient) -> None`

Close the MongoDB client.

- **Args:** `client` — a Motor client to close.

## `src/db/errors.py` — Error Hierarchy

Module-local exceptions, all inheriting from a single root.

```
DatabaseConnectionError(Exception)
├── PostgresConnectionError(DatabaseConnectionError)
└── MongoConnectionError(DatabaseConnectionError)
```

### Usage

```python
from src.db.errors import (
    DatabaseConnectionError,
    PostgresConnectionError,
    MongoConnectionError,
)

try:
    pool = await create_postgres_pool(dsn)
except PostgresConnectionError:
    logger.error("postgres unavailable")
```

All three exception types are re-exported from `src.db`.

## `src/main.py` — Entrypoint

Async smoke test that checks connectivity to all databases.

```
1. Connects to db_csm_set (PostgreSQL) → runs SELECT 1
2. Connects to db_gateway (PostgreSQL) → runs SELECT 1
3. Connects to csm_logs (MongoDB) → runs ping
4. Exits 0 if all healthy, exits 1 if any database is unreachable
```

Run via:

```bash
uv run python -m src.main
```

## `init-scripts/` — Database Initialization

Mounted to PostgreSQL's `/docker-entrypoint-initdb.d/`. Scripts execute
alphabetically on first container start only (when the data volume is empty).
All scripts are idempotent.

| Script | Database | Purpose |
|---|---|---|
| `01_create_databases.sql` | postgres (admin) | Creates `db_csm_set` and `db_gateway` using `\gexec` for idempotency |
| `02_enable_timescaledb.sql` | db_csm_set, db_gateway | Enables TimescaleDB extension on both databases |
| `03_schema_csm_set.sql` | db_csm_set | Creates `equity_curve` (hypertable), `trade_history`, `backtest_log` |
| `04_schema_gateway.sql` | db_gateway | Creates `daily_performance` (hypertable), `portfolio_snapshot` (hypertable) |
| `mongo-init.js` | csm_logs | Creates collections `backtest_results`, `model_params`, `signal_snapshots` with indexes |

### Schema reference — `db_csm_set`

| Table | Type | Key columns |
|---|---|---|
| `equity_curve` | Hypertable (time) | `time`, `strategy_id`, `equity` |
| `trade_history` | Regular | `id` (PK), `time`, `strategy_id`, `symbol`, `side`, `quantity`, `price`, `commission` |
| `backtest_log` | Regular | `id` (PK), `run_id` (UNIQUE), `strategy_id`, `started_at`, `finished_at`, `config` (JSONB), `summary` (JSONB) |

### Schema reference — `db_gateway`

| Table | Type | Key columns |
|---|---|---|
| `daily_performance` | Hypertable (time) | `time`, `strategy_id`, `daily_return`, `cumulative_return`, `total_value`, `cash_balance`, `max_drawdown`, `sharpe_ratio`, `metadata` (JSONB) |
| `portfolio_snapshot` | Hypertable (time) | `time`, `total_portfolio`, `weighted_return`, `combined_drawdown`, `active_strategies`, `allocation` (JSONB) |

### MongoDB collections — `csm_logs`

| Collection | Index |
|---|---|
| `backtest_results` | `{strategy_id: 1, created_at: -1}` |
| `model_params` | `{strategy_id: 1, version: -1}` |
| `signal_snapshots` | `{strategy_id: 1, date: -1}` |

## `scripts/` — Operations Scripts

### `backup.sh`

Creates timestamped backups of both databases.

- **Requires:** Docker, healthy containers, `.env` credentials.
- **Output:** `backups/pg_all_<UTC>.sql` + `backups/mongo_<UTC>/`.
- **Safety:** Pre-flight health checks; ERR trap removes partial artefacts.

### `restore.sh`

Restores databases from a timestamped backup.

- **Usage:** `scripts/restore.sh [--list|--force] [--postgres-only|--mongo-only] <timestamp>`
- **Flags:**
  - `--list` — list available backup timestamps.
  - `--force` — required when target databases are non-empty.
  - `--postgres-only` / `--mongo-only` — restore only one engine.
- **Safety:** Three-layer guard: container health + non-empty check + interactive confirmation.
- **Non-interactive:** Set `RESTORE_CONFIRM=restore` in the environment.
- **PostgreSQL:** Strips `DROP/CREATE ROLE postgres` lines from the dump to avoid
  conflicting with the live role, then replays with `ON_ERROR_STOP=1`.
- **MongoDB:** Copies the BSON dump into the container and runs `mongorestore --drop`.
