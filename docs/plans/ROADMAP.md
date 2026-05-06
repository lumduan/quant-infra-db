# quant-infra-db — Roadmap

The `infra-db` project is the database infrastructure layer for the entire Quant Trading system.
It runs **PostgreSQL + TimescaleDB** and **MongoDB** through Docker Compose
on a shared Docker network `quant-network`, so every Strategy Service and the API Gateway can connect to it.

---

## Status legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[-]` | Skipped / deferred |

---

## Phase 1 — Project Bootstrap 🏗️

> **Goal:** Set up the project skeleton and the base Docker Compose stack so that `docker compose up -d` works on a fresh clone with no extra configuration.

### 1.1 Project structure

- [x] Create the project folder `infra-db/`
- [x] Create `README.md` describing the overview, install steps, and connection strings
- [x] Create `.env.example` — template for credentials (no real values)
- [x] Create `.gitignore`:
  - Do not commit the real `.env`
  - Do not commit `backups/`
- [-] Push the project to GitHub (private repository) — deferred, repo already exists

**Exit criteria:** project skeleton is complete; no real credentials are present in the repository.

### 1.2 Docker Compose — Core services

- [x] Create `docker-compose.yml` with the core services:
  ```yaml
  services:
    postgres:
      image: timescale/timescaledb:latest-pg16
      container_name: quant-postgres
      restart: always
      environment:
        POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      ports:
        - "5432:5432"
      volumes:
        - postgres_data:/var/lib/postgresql/data
        - ./init-scripts:/docker-entrypoint-initdb.d

    mongodb:
      image: mongo:latest
      container_name: quant-mongo
      restart: always
      ports:
        - "27017:27017"
      volumes:
        - mongo_data:/data/db
        - ./init-scripts/mongo-init.js:/docker-entrypoint-initdb.d/mongo-init.js

  volumes:
    postgres_data:
    mongo_data:
  ```
- [x] Verify: `docker compose up -d` → both containers start with no error

**Exit criteria:** `docker compose ps` shows `postgres` and `mongodb` with status `Up`.

### 1.3 Docker network `quant-network`

- [x] Create the external network before running compose:
  ```bash
  docker network create quant-network
  ```
- [x] Add network configuration to `docker-compose.yml` so every container joins `quant-network`:
  ```yaml
  networks:
    default:
      name: quant-network
      external: true
  ```
- [x] Document the network creation command in `README.md` (one-time setup per host)
- [x] Verify: a container in another service can ping `quant-postgres` and `quant-mongo` by hostname

**Exit criteria:** containers communicate via hostname; no IP address required.

---

## Phase 2 — PostgreSQL & TimescaleDB Setup 🐘

> **Goal:** Create per-service logical databases with the TimescaleDB extension enabled and an initial schema.

### 2.1 Create logical databases

- [x] Create init script `init-scripts/01_create_databases.sql`:
  ```sql
  CREATE DATABASE db_csm_set;
  CREATE DATABASE db_gateway;
  ```
- [x] Verify: `docker exec -it quant-postgres psql -U postgres -l`
  → both `db_csm_set` and `db_gateway` appear in the list

**Exit criteria:** both databases are created automatically after `docker compose up`.

### 2.2 Enable the TimescaleDB extension

- [x] Create init script `init-scripts/02_enable_timescaledb.sql`:
  ```sql
  \c db_csm_set
  CREATE EXTENSION IF NOT EXISTS timescaledb;

  \c db_gateway
  CREATE EXTENSION IF NOT EXISTS timescaledb;
  ```
- [x] Verify: `SELECT extname, extversion FROM pg_extension WHERE extname = 'timescaledb';`
  inside both `db_csm_set` and `db_gateway`
- [x] Record the TimescaleDB version in `README.md`

**Exit criteria:** the `timescaledb` extension is available in both databases.

### 2.3 Schema for `db_csm_set`

- [x] Create init script `init-scripts/03_schema_csm_set.sql`
- [x] Table `equity_curve` — daily equity per strategy (TimescaleDB hypertable):
  ```sql
  \c db_csm_set

  CREATE TABLE IF NOT EXISTS equity_curve (
      time        TIMESTAMPTZ NOT NULL,
      strategy_id TEXT        NOT NULL,
      equity      DOUBLE PRECISION NOT NULL
  );
  SELECT create_hypertable('equity_curve', 'time', if_not_exists => TRUE);
  CREATE INDEX IF NOT EXISTS idx_equity_curve_strategy_time
      ON equity_curve (strategy_id, time DESC);
  ```
- [x] Table `trade_history` — every trade record:
  ```sql
  CREATE TABLE IF NOT EXISTS trade_history (
      id          SERIAL      PRIMARY KEY,
      time        TIMESTAMPTZ NOT NULL,
      strategy_id TEXT        NOT NULL,
      symbol      TEXT        NOT NULL,
      side        TEXT        NOT NULL,
      quantity    DOUBLE PRECISION NOT NULL,
      price       DOUBLE PRECISION NOT NULL,
      commission  DOUBLE PRECISION DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS idx_trade_history_strategy_time
      ON trade_history (strategy_id, time DESC);
  ```
- [x] Table `backtest_log` — metadata for each backtest run:
  ```sql
  CREATE TABLE IF NOT EXISTS backtest_log (
      id          SERIAL      PRIMARY KEY,
      run_id      TEXT        UNIQUE NOT NULL,
      strategy_id TEXT        NOT NULL,
      started_at  TIMESTAMPTZ NOT NULL,
      finished_at TIMESTAMPTZ,
      config      JSONB,
      summary     JSONB
  );
  ```
- [x] Verify: insert sample rows → queries return them correctly

**Exit criteria:** schema is in place; `equity_curve` is a TimescaleDB hypertable.

### 2.4 Schema for `db_gateway`

- [x] Create init script `init-scripts/04_schema_gateway.sql`
- [x] Table `daily_performance` — daily performance from every strategy (TimescaleDB hypertable):
  ```sql
  \c db_gateway

  CREATE TABLE IF NOT EXISTS daily_performance (
      time            TIMESTAMPTZ NOT NULL,
      strategy_id     TEXT        NOT NULL,
      daily_return    DOUBLE PRECISION,
      cumulative_return DOUBLE PRECISION,
      total_value     DOUBLE PRECISION,
      cash_balance    DOUBLE PRECISION,
      max_drawdown    DOUBLE PRECISION,
      sharpe_ratio    DOUBLE PRECISION,
      metadata        JSONB
  );
  SELECT create_hypertable('daily_performance', 'time', if_not_exists => TRUE);
  CREATE INDEX IF NOT EXISTS idx_daily_performance_strategy_time
      ON daily_performance (strategy_id, time DESC);
  ```
- [x] Table `portfolio_snapshot` — combined snapshot across all strategies for a given date (TimescaleDB hypertable):
  ```sql
  CREATE TABLE IF NOT EXISTS portfolio_snapshot (
      time              TIMESTAMPTZ NOT NULL,
      total_portfolio   DOUBLE PRECISION NOT NULL,
      weighted_return   DOUBLE PRECISION,
      combined_drawdown DOUBLE PRECISION,
      active_strategies INTEGER,
      allocation        JSONB
  );
  SELECT create_hypertable('portfolio_snapshot', 'time', if_not_exists => TRUE);
  ```
- [x] Verify: insert rows from two strategies → cross-strategy aggregation queries return the expected results

**Exit criteria:** schema is in place; aggregation across multiple strategies works.

---

## Phase 3 — MongoDB Setup 🍃

> **Goal:** Provision schema-less MongoDB collections for logs, model parameters, and backtest results.

### 3.1 Create collections and indexes

- [x] Create init script `init-scripts/mongo-init.js`:
  ```javascript
  // Database for the CSM-SET strategy
  db = db.getSiblingDB('csm_logs');

  db.createCollection('backtest_results');
  db.createCollection('model_params');
  db.createCollection('signal_snapshots');

  db.backtest_results.createIndex({ strategy_id: 1, created_at: -1 });
  db.model_params.createIndex({ strategy_id: 1, version: -1 });
  db.signal_snapshots.createIndex({ strategy_id: 1, date: -1 });
  ```
- [x] Verify: `docker exec -it quant-mongo mongosh csm_logs --eval "show collections"`
  → the created collections are listed

**Exit criteria:** MongoDB collections and indexes are created automatically after `docker compose up`.

### 3.2 Connectivity smoke test from Python

- [x] Test PostgreSQL via `psycopg2`:
  ```python
  import psycopg2
  conn = psycopg2.connect(
      "postgresql://postgres:<pass>@localhost:5432/db_csm_set"
  )
  cur = conn.cursor()
  cur.execute("SELECT version();")
  print(cur.fetchone())
  ```
- [x] Test MongoDB via `pymongo`:
  ```python
  from pymongo import MongoClient
  client = MongoClient("mongodb://localhost:27017/")
  db = client.csm_logs
  db.backtest_results.insert_one({"test": "ok", "ts": "2026-05-05"})
  assert db.backtest_results.count_documents({}) > 0
  print("MongoDB OK")
  ```
- [x] Record the connection strings in `README.md` (use `<pass>` as a placeholder, never the real password)

**Exit criteria:** both PostgreSQL and MongoDB accept Python connections successfully.

---

## Phase 4 — Operations & Health Check ⚙️

> **Goal:** Prepare the health-check, backup, and recovery procedures needed for production.

### 4.1 Health check

- [x] Add `healthcheck:` blocks in `docker-compose.yml`:
  ```yaml
  # PostgreSQL
  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

  # MongoDB
  mongodb:
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
  ```
- [x] Verify: `docker compose ps` shows `(healthy)` for every container

**Exit criteria:** containers report `healthy`, not just `running`.

### 4.2 Backup script

- [x] Create the `backups/` folder (gitignored)
- [x] Create `scripts/backup.sh`:
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  DATE=$(date +%Y%m%d_%H%M%S)
  BACKUP_DIR="./backups"
  mkdir -p "$BACKUP_DIR"

  echo "=== Backing up PostgreSQL ==="
  docker exec quant-postgres pg_dumpall -U postgres \
      > "$BACKUP_DIR/pg_all_${DATE}.sql"
  echo "PostgreSQL backup saved: pg_all_${DATE}.sql"

  echo "=== Backing up MongoDB ==="
  docker exec quant-mongo mongodump \
      --out "/tmp/mongodump_${DATE}"
  docker cp "quant-mongo:/tmp/mongodump_${DATE}" \
      "$BACKUP_DIR/mongo_${DATE}"
  echo "MongoDB backup saved: mongo_${DATE}/"
  ```
- [x] Verify: `bash scripts/backup.sh` → all backup files are produced
- [x] Restore from a backup at least once to verify the procedure
- [x] Document the backup schedule in `README.md` (recommended: daily, before model runs)

**Exit criteria:** the backup script works end-to-end and data can be restored from a backup.

### 4.3 Connection-string reference

- [x] Record every connection string in `README.md`:
  ```
  # CSM-SET → PostgreSQL
  postgresql://postgres:<pass>@quant-postgres:5432/db_csm_set

  # Gateway → PostgreSQL (central)
  postgresql://postgres:<pass>@quant-postgres:5432/db_gateway

  # CSM-SET logs → MongoDB
  mongodb://quant-mongo:27017/csm_logs
  ```
- [x] Provide `.env.example` with the required variables:
  ```env
  POSTGRES_PASSWORD=your_strong_password_here
  ```

**Exit criteria:** a new developer can read `README.md` and bring the stack up without asking questions.

---

## Phase 5 — Documentation

> **Goal:** Create comprehensive, discoverable documentation so new users can
> understand, set up, and contribute to the project without reading source code.

### 5.1 Project overview

- [x] Create `docs/overview.md` — project identity, architecture diagram, data flow,
  key design decisions, and a documentation map linking to every other doc
- [x] Synthesize content from `.claude/knowledge/architecture.md`,
  `.claude/knowledge/stack-decisions.md`, and the completed phase plans

### 5.2 Usage guide

- [x] Create `docs/usage.md` — prerequisites, quick start, Docker Compose commands,
  connection strings (in-network and host-side), Python connectivity, healthcheck
  verification, backup and restore runbooks, security scanning, troubleshooting
- [x] Extract and expand usage material from `README.md` into the dedicated guide,
  keeping `README.md` focused on the quick-start path

### 5.3 Module reference

- [x] Create `docs/modules.md` — per-module documentation for the Python connectivity
  layer:
  - `src/config.py` — Pydantic Settings class, fields, validators, computed properties
  - `src/db/postgres.py` — asyncpg pool management and health checks
  - `src/db/mongo.py` — Motor async client and health checks
  - `src/db/errors.py` — exception hierarchy
  - `src/main.py` — async smoke-test entrypoint
  - `init-scripts/` — SQL/JS init scripts reference with schema summaries
  - `scripts/` — backup.sh and restore.sh reference

### 5.4 Navigation and cross-references

- [x] Update `README.md` with a Documentation section linking to all new docs
- [x] Ensure every cross-reference between docs is a valid relative link
- [x] Surface `.claude/knowledge/` content (architecture, standards, decisions) in
  human-readable form within `docs/`

**Exit criteria:** a new contributor can navigate from `README.md` to any piece of
information they need — architecture, usage, module APIs, or contribution guidelines —
without hitting a dead end or placeholder.

---

## Project file structure

```
infra-db/
├── docker-compose.yml              # Core services: postgres + mongodb
├── .env                            # Real credentials (gitignored)
├── .env.example                    # Credentials template
├── .gitignore
├── README.md                       # Setup, connection strings, backup guide
│
├── init-scripts/                   # Run automatically on first container start
│   ├── 01_create_databases.sql     # Create db_csm_set, db_gateway
│   ├── 02_enable_timescaledb.sql   # Enable the TimescaleDB extension
│   ├── 03_schema_csm_set.sql       # Tables: equity_curve, trade_history, backtest_log
│   ├── 04_schema_gateway.sql       # Tables: daily_performance, portfolio_snapshot
│   └── mongo-init.js               # MongoDB: create collections + indexes
│
├── scripts/
│   ├── backup.sh                   # Back up PostgreSQL + MongoDB
│   └── restore.sh                  # Restore from a timestamped backup
│
├── docs/
│   ├── overview.md                 # Project overview, architecture, doc map
│   ├── usage.md                    # Setup, operations, and troubleshooting
│   └── modules.md                  # Python module and script reference
│
└── backups/                        # Backup output directory (gitignored)
```

---

## Dependency Map

```
Phase 1 (Bootstrap + Docker Compose + Network)
    └── Phase 2 (PostgreSQL + TimescaleDB + Schema)
            └── Phase 3 (MongoDB + Collections)
                    └── Phase 4 (Health Check + Backup + Restore)
                            └── Phase 5 (Documentation)
                                    └── Phase 6 — Downstream service integration
                                            └── [CSM-SET adapter → API Gateway]
```

---

## Overall Exit Criteria

`docker compose up -d` from a fresh clone → everything is ready with no extra configuration:

- `docker compose ps` shows `quant-postgres` and `quant-mongo` as `healthy`
- `psql` connects to `db_csm_set` and `db_gateway` with the TimescaleDB extension available
- `mongosh` connects to `csm_logs` and lists the expected collections and indexes
- The Python connectivity smoke test passes for both PostgreSQL and MongoDB
- `scripts/backup.sh` runs and produces complete backup artifacts
- Every container is on `quant-network` so strategy services can reach them by hostname

---

## Current status

> Update this section as each phase completes.

- **Active phase:** Phase 5 — Documentation (comprehensive project docs, module reference, usage guide)
- **Completed phases:** Phase 1 (2026-05-06), Phase 2 (2026-05-06), Phase 3 (2026-05-06), Phase 4 (2026-05-06)
- **Blocked by:** nothing
- **Next:** Phase 6 — Downstream service integration: wire the CSM-SET strategy adapter to `db_csm_set` and `csm_logs`; provision the API Gateway service against `db_gateway`.

---

## Related notes

- [[batt/quant-csm-set]] — Architecture overview & main roadmap (API Gateway + Dashboard)
- [[batt/Cross-Sectional Momentum (CSM)]] — Strategy logic & backtest
