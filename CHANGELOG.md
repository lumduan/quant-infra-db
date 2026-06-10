# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added (feature-execution-engine — Phase 2: service-role grants)

- `init-scripts/12_schema_execution.sql`: idempotent **least-privilege grants for the
  `quant` service role** (created if absent; placeholder password matches the compose
  files — operators override per machine). orders: SELECT/INSERT/UPDATE; fills +
  order_events: SELECT/INSERT (the audit trigger runs with INVOKER rights, so the
  engine role needs INSERT on order_events; append-only still trigger-enforced);
  USAGE on the identity sequences. **No DELETE anywhere; strategies/gateway get no
  grant.** This is the grant block the Phase 1 header deferred to Phase 2.

### Added (feature-execution-engine — Phase 2 prep: engine registry + reject_reason)

- `init-scripts/07_engine_catalog.sql`: register the **`execution`** engine
  (`EXTERNAL`, `active`) in `engine_registry` — the gateway's `/api/v2/engines/catalog`
  is DB-first, so the standalone `quant-execution-engine` (host `:8400`) must exist here,
  not just in the gateway's static fallback. Idempotent (`ON CONFLICT (slug) DO NOTHING`).
- `init-scripts/12_schema_execution.sql`: add **`execution.orders.reject_reason`**
  (nullable TEXT) — the Phase-1-sanctioned Phase-2 `ALTER`; the engine persists the
  adapter/venue reject reason durably on REJECTED rows. Both in `CREATE TABLE` (fresh
  volumes) and as `ALTER TABLE … ADD COLUMN IF NOT EXISTS` (live databases).
- `tests/test_execution_schema.py`: assert the new column.

### Added (feature-execution-engine — Phase 1: `execution` order store)

- New database **`db_execution`** with an **`execution`** schema — the durable, idempotent,
  auditable order store for the Execution engine (a dedicated DB, mirroring `db_market_data`,
  so the store is independently owned; the standalone `quant-execution-engine` becomes the
  sole writer in Phase 2). Created via the `\gexec` guard in `01_create_databases.sql`.
  **Plain tables, no TimescaleDB** — low-volume real-money command plane; `fills`/`order_events`
  FK to `orders` and hypertables cannot be FK targets.
- `init-scripts/12_schema_execution.sql`:
  - `execution.orders` — **PK `client_order_id` (TEXT, opaque per ADR §A)** = the idempotency
    constraint; the frozen NormalizedOrder enums as CHECK constraints (broker ∈
    {sim,liberator,settrade}, market ∈ {SET,TFEX}, side, 8 order types, tif,
    position_effect, the 9-state status); prices `numeric(18,6)`, quantities `bigint`;
    cross-field CHECKs (LIMIT/STOP_LIMIT price required, STOP/STOP_LIMIT stop_price required,
    `display_qty ≤ quantity`, position_effect TFEX-only); partial index
    `(broker, broker_order_id)` for venue→local lookup and the ADR §B reconciliation index
    `(account, symbol, side, quantity, created_at)` (±5 s lost-ack fuzzy match).
  - `execution.fills` — identity PK, FK → orders; `UNIQUE (client_order_id, broker_fill_id)`
    dedupes at-least-once fill delivery (NULL fill ids exempt — adapters must supply one).
  - `execution.order_events` — **append-only** audit log (UPDATE/DELETE/TRUNCATE raise);
    FK → orders, so audited orders can never be deleted.
  - Triggers: `orders_guard` (entry state = PENDING_NEW; **exactly the 13 frozen
    state-machine edges**, ERRCODE 23514; terminal states immutable; auto `updated_at`) and
    `orders_append_event` (one audit row per INSERT/transition, `broker_order_id`
    snapshotted atomically on ack per ADR §B — DB-enforced, no app code). Frozen-graph gaps
    (cancel-reject, Liberator `PENDING_REPLACE → CANCELLED`) deliberately not encoded —
    amending the graph needs an ADR amendment + follow-up migration.
- `src/config.py`: `execution_dsn` property (`db_execution`).
- Tests: `tests/test_execution_schema.py` (`-m infra`) proving double-apply idempotency
  (psql via docker exec, `ON_ERROR_STOP=1`), duplicate `client_order_id` rejection,
  entry-state enforcement, legal-lifecycle audit rows (one per transition), illegal-transition
  rejection, terminal immutability, fill FK/dedupe, append-only enforcement, and Decimal
  `numeric(18,6)` round-trip; `test_config.py::test_execution_dsn_format` (unit).

### Added (feature-market-data-engine — Phase 1: shared `market_data` schema)

- New database **`db_market_data`** with a **`market_data`** schema — the shared canonical
  OHLCV store (a dedicated DB, not a `db_gateway` schema, per ADR D4/D7). Created via the
  `\gexec` guard in `01_create_databases.sql`; TimescaleDB enabled in `02_enable_timescaledb.sql`.
- `init-scripts/10_schema_market_data.sql`:
  - `market_data.ohlcv` hypertable, **PK `(symbol, timeframe, ts)`** (Option A multi-timeframe,
    D10). Prices `numeric(18,6)`, `volume`/`open_interest` `numeric(20,4)`; `open_interest`
    carried from day one (NULL for equities). `ts` is bar-open UTC. 30-day chunks; compression
    `segmentby (symbol, timeframe)` after 7 days; read-path index `(symbol, timeframe, ts DESC)`.
    CHECK constraints: timeframe ∈ {1d,1h,5m}, prices > 0, volume ≥ 0, open_interest ≥ 0,
    high ≥ low. **Deliberately uses `numeric(18,6)` vs the 08/09 mirror's `(18,4)`** (shared
    multi-asset store; ADR §5 serialises 6-dp prices; 08/09 is being retired).
  - `market_data.corporate_actions` — splits/dividends + futures roll dates; PK
    `(symbol, ex_date, action_type)`. `ratio` = price back-adjustment multiplier.
  - `market_data.universe_membership` — as-of dated point-in-time constituents; PK
    `(as_of, symbol, index_name)`.
  - `market_data.ohlcv_adjusted` — adjust-on-read **view** (D2): back-adjusts prior bars by the
    cumulative product of `ratio` over later-dated actions; recomputes on every read.
- `init-scripts/11_market_data_caggs.sql` — `cagg_ohlcv_1h` / `cagg_ohlcv_4h` continuous
  aggregates derived from the 5m base (`WITH NO DATA` + refresh policies, 06-style). Fetched
  `1d` stays authoritative (settlement, never rolled up).
- `src/db/models.py`: `OHLCVBarRow`, `CorporateActionRow`, `UniverseMembershipRow` (Pydantic v2,
  `Decimal` prices, UTC validators, timeframe/action-type enums, high ≥ low check).
- `src/db/repositories.py`: `upsert_ohlcv`, `fetch_ohlcv`, `upsert_corporate_actions`,
  `upsert_universe_membership` (asyncpg `INSERT … ON CONFLICT … DO UPDATE`).
- `src/config.py`: `market_data_dsn` property (`db_market_data`).
- Tests: unit (`test_models.py`, `test_repositories.py`) + live-DB infra (`test_postgres.py`,
  `-m infra`) proving hypertable creation, upsert idempotency, constraint rejection, adjusted-view
  recompute on a new action, CAGG registration, and index-backed reads.

### Added (Phase 1)

- **Project Bootstrap:** Docker Compose stack (PostgreSQL + TimescaleDB + MongoDB) on `quant-network`.
- `docker-compose.yml` with healthchecks, named volumes, and external network configuration.
- Init scripts: `01_create_databases.sql`, `02_enable_timescaledb.sql`, `03_schema_csm_set.sql`, `04_schema_gateway.sql`, `mongo-init.js`.
- Python connectivity layer: Pydantic Settings config, asyncpg pool, motor client, typed exceptions.
- `scripts/backup.sh` for PostgreSQL (`pg_dumpall`) and MongoDB (`mongodump`).
- Unit tests (`test_config.py`) and integration tests (`test_postgres.py`, `test_mongo.py`, `test_infra.py`).
- Updated `README.md` with setup instructions, connection strings, and backup workflow.

### Added (Phase 2 — PostgreSQL hardening)

- Idempotent database creation via `\gexec` pattern in `01_create_databases.sql`.
- Schema documentation: `docs/plans/phase_2_postgre_db/phase_2_postgresql_setup.md`.

### Added (Phase 3 — MongoDB hardening)

- MongoDB authentication support in `config.py` (`mongo_username`, `mongo_password`, `mongo_database`).
- Conditional auth in `mongo_uri` property — falls back to no-auth when credentials are empty.
- Hardened `mongo-init.js` with correct per-collection index fields (`version`, `date`) and comprehensive documentation.
- Expanded `test_mongo.py` index assertions to validate all three collections.
- Schema documentation: `docs/plans/phase_3_mongodb/phase_3_mongodb_setup.md`.

### Added (Phase 4 — Operations & Health Check)

- Hardened `scripts/backup.sh`: sources `.env`, validates required credentials, refuses to run when either container is not `healthy`, passes MongoDB credentials via `docker exec -e` (admin auth), uses `pg_dumpall --clean --if-exists` for idempotent restore, traps errors to remove partial artefacts, and resolves `BACKUP_DIR` from `${BASH_SOURCE[0]}` so the script works from any CWD. Timestamps are UTC.
- New `scripts/restore.sh` covering both engines with `--list`, `--force`, `--postgres-only`, `--mongo-only`, an interactive `read -r -p` confirmation, and a `RESTORE_CONFIRM=restore` bypass for non-interactive use. Strips the cluster superuser role's `DROP/CREATE ROLE` lines before piping `pg_dumpall` output to `psql` so the restore is idempotent against a live cluster.
- README sections: "Healthcheck verification", "Backup", "Restore" with the safety semantics so operators do not need to read the script source.
- Phase 4 plan document: `docs/plans/phase_4_operations_health_check/phase_4_operations_health_check.md` with end-to-end verification evidence.

### Fixed (Phase 4)

- `.gitignore` now excludes `backups/` (closes a Phase 1 oversight where the ROADMAP claimed the task complete but the entry was never added).

### Changed

- Renamed project from `python-template` to `quant-infra-db`.
- Updated `.env.example` with PostgreSQL and MongoDB variables.
- Migrated DB data storage from Docker named volumes (`quant-infra-db_postgres_data`, `quant-infra-db_mongo_data`) to project-root bind mounts (`./postgres_data/`, `./mongo_data/`) for direct filesystem visibility and portability. Removed the top-level `volumes:` section from `docker-compose.yml`.

## [0.1.0] — 2026-05-06

### Added
- Initial template scaffold: `src/`, `tests/`, `docs/`, `.claude/`, `.github/`.
- `pyproject.toml` with `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `bandit`, `pip-audit`.
- Multi-stage `Dockerfile` (uv-native, Python 3.11-slim).
- CI workflow (lint, format check, type check, test with coverage) on Python 3.11 and 3.12.
- Docker publish workflow targeting GHCR.
- Weekly security scan workflow (`bandit` + `pip-audit`).
- AI-agent enablement: `.claude/knowledge/project-skill.md`, `.claude/playbooks/feature-development.md`, `.claude/prompts/Prompt-Engineer.prompt.md`.
- Issue templates (bug, feature), PR template, `FUNDING.yml`.

[Unreleased]: https://github.com/OWNER/REPO/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OWNER/REPO/releases/tag/v0.1.0
