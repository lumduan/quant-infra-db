# Phase 3: MongoDB Setup

**Feature:** MongoDB Collections, Indexes, and Python Connectivity
**Branch:** `feature/phase-3-mongodb-setup`
**Created:** 2026-05-06
**Status:** Complete
**Completed:** 2026-05-06
**Depends On:** Phase 1 (Complete), Phase 2 (Complete)

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

Phase 3 provisions schema-less MongoDB collections for the CSM-SET strategy's operational
data: backtest results, model hyperparameters, and daily signal snapshots. It also hardens
the Python connectivity layer with MongoDB authentication support and ensures all init
scripts are fully documented and idempotent.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — Phase 3 sections 3.1–3.2

### Key Deliverables

1. **`init-scripts/mongo-init.js`** — Hardened with correct indexes and comprehensive documentation
2. **`src/config.py`** — MongoDB authentication support via `MONGO_USERNAME` / `MONGO_PASSWORD`
3. **`tests/test_config.py`** — Unit tests for MongoDB URI variants (with/without auth)
4. **`tests/test_mongo.py`** — Updated index assertions to match corrected field names

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `mongo-init.js` hardening | Fix index field names (`version`, `date`); add full documentation | Complete |
| MongoDB auth support | `config.py` reads `MONGO_USERNAME` / `MONGO_PASSWORD`, builds authenticated URI | Complete |
| Config unit tests | Tests for `mongo_uri` with and without auth, `mongo_database` default | Complete |
| Index test updates | `test_indexes_exist` validates all three collections with correct fields | Complete |
| Phase 3 plan document | This file | Complete |

### Out of Scope

- MongoDB production deployment tuning (Phase 4)
- Backup script changes (already covers MongoDB in Phase 4)
- Additional collections beyond the three specified in the roadmap
- MongoDB replica sets or sharding

---

## Design Decisions

### 1. Per-collection index field names

The roadmap specifies different sort fields for each collection's compound index:

| Collection | Index | Rationale |
|---|---|---|
| `backtest_results` | `(strategy_id, created_at)` | Backtests are queried by run timestamp |
| `model_params` | `(strategy_id, version)` | Model parameters are versioned; newest version first |
| `signal_snapshots` | `(strategy_id, date)` | Signals are queried by trading date |

The original init script incorrectly used `created_at` for all three — this was fixed
to match the roadmap specification.

### 2. MongoDB authentication optional

`MONGO_USERNAME` and `MONGO_PASSWORD` are optional in `config.py`. When either is empty,
the connection URI omits credentials entirely. This supports two workflows:

- **Development without auth:** Neither env var set → `mongodb://localhost:27017`
- **Development with auth:** Both set → `mongodb://admin:s3cret@localhost:27017`

The Docker Compose file already declares `MONGO_INITDB_ROOT_USERNAME` and
`MONGO_INITDB_ROOT_PASSWORD` from `.env`. When these are set, MongoDB enables
authentication, and the Python code must supply matching credentials.

### 3. `motor` (async) over `pymongo` (sync)

The roadmap's Phase 3 code samples use synchronous `pymongo`. The project uses `motor`
(MongoDB's official async driver) instead, consistent with the async-first I/O rule
and the PostgreSQL side which uses `asyncpg`. `motor` wraps `pymongo` and exposes the
same API surface with `await`.

### 4. Init script idempotency via MongoDB semantics

MongoDB's `createCollection()` is a no-op when the collection already exists, and
`createIndex()` is a no-op for identical indexes. No additional idempotency guards
are needed — the MongoDB server handles this natively.

---

## Database Schema

### Database: `csm_logs`

| Collection | Purpose | Key fields | Index |
|---|---|---|---|
| `backtest_results` | Historical backtest run outputs | `strategy_id`, `created_at`, equity curves, metrics | `(strategy_id, created_at DESC)` |
| `model_params` | Serialized model hyperparameters | `strategy_id`, `version`, parameter dict | `(strategy_id, version DESC)` |
| `signal_snapshots` | Daily signal vectors | `strategy_id`, `date`, signal array | `(strategy_id, date DESC)` |

MongoDB is schema-less by design — documents within each collection may vary in shape.
Downstream consumers should validate document structure at the application level using
Pydantic models.

---

## Implementation Steps

### Step 1: Fix `mongo-init.js` indexes and documentation

Corrected `model_params` index from `created_at` → `version` and `signal_snapshots`
index from `created_at` → `date`. Added comprehensive header comments explaining
idempotency guarantees, database purpose, and each collection/index rationale.

### Step 2: Add MongoDB auth support to `config.py`

Added `mongo_username`, `mongo_password` (SecretStr), and `mongo_database` fields.
Updated `mongo_uri` property to conditionally include credentials in the connection
string when both username and password are set.

### Step 3: Add config unit tests

Added three new tests to `test_config.py`:
- `test_mongo_uri_format_with_auth` — verifies `mongodb://user:pass@host:port`
- `test_mongo_uri_format_auth_partial_username_only` — verifies fallback to no-auth
- `test_mongo_database_default` — verifies default value `csm_logs`

### Step 4: Update index integration test

Expanded `test_indexes_exist` in `test_mongo.py` to validate indexes on all three
collections with their correct field names.

### Step 5: Quality gate

All four quality gate commands pass: ruff check, ruff format, mypy, pytest (95.65% coverage).

---

## File Changes

| File | Action | Description |
|---|---|---|
| `init-scripts/mongo-init.js` | MODIFY | Fix index fields (`version`, `date`); add comprehensive documentation |
| `src/config.py` | MODIFY | Add `mongo_username`, `mongo_password`, `mongo_database`; conditional auth in `mongo_uri` |
| `tests/test_config.py` | MODIFY | Add 3 tests for MongoDB auth URI variants and default database |
| `tests/test_mongo.py` | MODIFY | Expand `test_indexes_exist` to validate all three collections |
| `docs/plans/phase_3_mongodb/phase_3_mongodb_setup.md` | CREATE | This plan document |

---

## Success Criteria

- [x] `mongo-init.js` uses correct index field names (`version`, `date`) per roadmap spec
- [x] `mongo-init.js` is fully documented with idempotency guarantees explained
- [x] `config.py` supports optional MongoDB authentication via env vars
- [x] `mongo_uri` falls back to no-auth when credentials are not set
- [x] Unit tests cover all MongoDB URI variants (with auth, without auth, partial)
- [x] Integration tests validate indexes on all three collections
- [x] `uv run ruff check .` passes
- [x] `uv run ruff format --check .` passes
- [x] `uv run mypy src tests` passes
- [x] `uv run pytest` passes with ≥80% coverage (95.65%)

---

## Verification

### Init script

```bash
# Verify mongo-init.js is valid JavaScript
docker exec -it quant-mongo mongosh --eval "load('/docker-entrypoint-initdb.d/mongo-init.js')"

# List collections and indexes
docker exec -it quant-mongo mongosh csm_logs --eval "show collections"
docker exec -it quant-mongo mongosh csm_logs --eval "db.backtest_results.getIndexes()"
docker exec -it quant-mongo mongosh csm_logs --eval "db.model_params.getIndexes()"
docker exec -it quant-mongo mongosh csm_logs --eval "db.signal_snapshots.getIndexes()"
```

### Python smoke test

```bash
uv run python -m src.main
```

### Quality gate

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest
```

---

## Completion Notes

### Summary

Phase 3 was largely scaffolded during Phase 1 bootstrap — Docker Compose already had MongoDB
configured with healthcheck, `mongo-init.js` existed, and the Python `motor` client was wired
into `src/db/mongo.py`. This phase focused on hardening: fixing index field names to match the
roadmap specification, adding MongoDB authentication support to the Python config layer, and
creating this formal phase document.

### Issues Encountered

1. **Index field name drift** — The original `mongo-init.js` used `created_at` for all three
   collections, but the roadmap specified `version` for `model_params` and `date` for
   `signal_snapshots`. The script was treated as authoritative during Phase 1 but the roadmap
   field names are more semantically correct (versioned model params, date-based signal lookups).
   Fixed to match the roadmap.

2. **MongoDB auth gap** — Docker Compose referenced `MONGO_INITDB_ROOT_USERNAME` and
   `MONGO_INITDB_ROOT_PASSWORD` but `config.py` had no corresponding fields. Python would
   fail to connect against an auth-enabled MongoDB. Added optional credential support with
   backward-compatible fallback.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Code)
**Status:** Complete
**Completed:** 2026-05-06
