# Phase 4: Operations & Health Check

**Feature:** Healthcheck Verification, Backup Hardening, Restore Procedure
**Branch:** `feature/phase-4-operations-health-check`
**Created:** 2026-05-06
**Status:** Complete
**Completed:** 2026-05-06
**Depends On:** Phase 1 (Complete), Phase 2 (Complete), Phase 3 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [Scope](#scope)
3. [Design Decisions](#design-decisions)
4. [Implementation Steps](#implementation-steps)
5. [File Changes](#file-changes)
6. [Success Criteria](#success-criteria)
7. [Verification](#verification)
8. [Completion Notes](#completion-notes)

---

## Overview

### Purpose

Phase 4 closes the operations story for the database stack: prove that the Docker
healthchecks report `healthy`, make `scripts/backup.sh` production-usable against the
auth-enabled MongoDB introduced in Phase 3, and add a tested restore procedure with
safety guards. The intended outcome is that any new operator can bring the stack up,
verify it, back it up, and restore from a clean checkout.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — Phase 4 sections 4.1, 4.2, 4.3

### Key Deliverables

1. **`scripts/backup.sh`** — Hardened with MongoDB authentication, `.env`-driven credentials,
   container-health pre-flight, error trap, and `BASH_SOURCE`-resolved output directory.
2. **`scripts/restore.sh`** — New script for PostgreSQL + MongoDB restore with `--list`,
   `--force`, `--postgres-only`, `--mongo-only`, interactive confirm, and
   `RESTORE_CONFIRM=restore` non-interactive bypass.
3. **`.gitignore`** — Closes a Phase 1 omission by excluding `backups/`.
4. **`README.md`** — Healthcheck verification, backup, and restore runbooks.
5. **End-to-end verification evidence** — Captured below.

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| Healthcheck evidence capture | `docker compose ps` + `docker inspect` against the live stack | Complete |
| Backup script hardening | MongoDB auth, `.env` loading, health pre-flight, ERR trap, idempotent dump | Complete |
| Restore script | New `scripts/restore.sh` with three-layer destructive guard | Complete |
| `.gitignore` `backups/` entry | Closes Phase 1 oversight | Complete |
| README backup/restore section | Operator-facing runbook with safety semantics | Complete |
| Phase 4 plan document | This file | Complete |
| ROADMAP "Current status" advance | Mark Phase 4 done; advance Active phase pointer | Complete |
| CHANGELOG `[Unreleased]` entry | Phase 4 Added/Fixed blocks | Complete |

### Out of Scope

- TimescaleDB chunk-aware backup (would require migrating from `pg_dumpall` to
  `pg_dump --format=directory` plus `timescaledb_pre_restore()` / `timescaledb_post_restore()`).
  `pg_dumpall` is sufficient at the current data scale; the migration is tracked as a
  follow-up.
- Backup retention / rotation. Operators add `find backups/ -mtime +N -delete` to a cron
  externally; the script does not auto-prune so backups cannot be silently lost.
- Off-host backup replication (S3 / GCS) — track in a future phase.
- Backup encryption at rest — operator responsibility (`chmod 600 .env`, encrypted volumes).
- Cross-engine atomic restore — `pg_dumpall` and `mongorestore` cannot coordinate. Mitigated
  by `--postgres-only` / `--mongo-only` for retry.
- High-availability or replication topology — Phase 4 keeps single-instance services.

---

## Design Decisions

### 1. Restore as a script + runbook (not runbook only)

The ROADMAP requirement "restore from a backup at least once to verify the procedure" was
ticked but produced no reusable artefact. Hand-typed `psql` / `mongorestore` commands
during an outage are how operators destroy production data; a single, reviewable script
encodes the recovery path so it can be bisected, audited, and run by anyone.

### 2. MongoDB healthcheck stays unauthenticated

`db.adminCommand('ping')` is on MongoDB's auth-bypass list and returns `{ ok: 1 }` even
with auth enabled. Adding `--username` / `--password` to the healthcheck would put
plaintext credentials in `docker inspect` output and require fragile env-var interpolation
inside the `CMD` array. The healthcheck verifies the *server is up*; the auth path is
exercised by `scripts/backup.sh` and `scripts/restore.sh`, which provide the missing
coverage.

### 3. Credentials via `docker exec -e`, not CLI flags

Both scripts pass `MONGO_USER` / `MONGO_PASS` through `docker exec -e`, which keeps the
password out of `ps` listings inside the container. CLI flags (`--password=...`) would
expose the secret to anyone running `ps -ef` in the container.

### 4. Three-layer destructive guard on restore

A naive `restore.sh <ts>` would let a single typo wipe production data. The script
requires three affirmative signals:

1. The `--force` flag is required when target databases contain rows or documents.
2. With a TTY attached, the operator must type the word `restore` at the prompt.
3. Without a TTY (cron, CI), `RESTORE_CONFIRM=restore` must be set explicitly in the
   environment.

### 5. `pg_dumpall --clean --if-exists` for idempotent restore

The first restore attempt during verification failed with `role "postgres" already exists`
because the unmodified `pg_dumpall` output is intended for a fresh cluster. `--clean
--if-exists` adds guarded `DROP` statements before each `CREATE`. The cluster superuser
role still needs special handling — `pg_dumpall` always emits
`DROP ROLE IF EXISTS postgres; CREATE ROLE postgres;`, both of which fail (psql cannot drop
the role it is currently authenticated as, and the subsequent `CREATE` collides with the
existing role). `restore.sh` strips just those two lines via `sed` before piping the dump
to `psql`; the trailing `ALTER ROLE postgres WITH ... PASSWORD ...` still applies, keeping
the role's attributes in sync with the dump.

### 6. UTC timestamps in backup filenames

`date -u +%Y%m%d_%H%M%SZ` produces filenames like `pg_all_20260506_060737Z.sql`. UTC
parity matters when backups are taken on multiple hosts or when an operator restores from
a different timezone than the backup origin. The trailing `Z` makes the timezone explicit.

### 7. `BASH_SOURCE`-resolved output directory

`BACKUP_DIR` is computed from `$(dirname "${BASH_SOURCE[0]}")` so the script works under
cron, CI, or any working directory — not only when invoked from the repo root.

### 8. `ERR` trap removes partial artefacts

Without a trap, a backup that fails halfway leaves a corrupt half-written `.sql` file or a
partial `mongodump` directory in `backups/`. The trap deletes both on error and removes
the in-container `/tmp/mongodump_*` directory, so re-running the backup is always against
a clean state.

---

## Implementation Steps

1. **Branch off `main`** as `feature/phase-4-operations-health-check` (Phase 3 had merged
   in PR #3, so `main` is at `9f4bd49`).
2. **Commit 1 — `infra: gitignore backups directory`** (`.gitignore`):
   add `backups/` under the existing `# Logs` block. Closes the Phase 1 omission.
3. **Commit 2 — `infra: harden backup script for MongoDB authentication`**
   (`scripts/backup.sh`):
   - Source `.env` via `set -a; source .env; set +a`.
   - Validate `POSTGRES_PASSWORD`, `MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD`
     with bash `:?` (fail fast on missing).
   - Add `require_healthy()` and call for both containers before any backup work.
   - Add `cleanup_on_error()` and `trap … ERR`.
   - Pass MongoDB credentials via `docker exec -e` and authenticate against `admin`.
   - Resolve `BACKUP_DIR` from `${BASH_SOURCE[0]}`; switch `DATE` to UTC.
4. **Commit 3 — `infra: add restore script for PostgreSQL and MongoDB`**
   (`scripts/restore.sh`, mode 0755):
   - Argument parsing: `--list`, `--force`, `--postgres-only`, `--mongo-only`, `<timestamp>`.
   - Reuse the same `.env` loading and `require_healthy` pattern.
   - Detect non-empty targets via `pg_database` count and per-collection
     `countDocuments({})`; refuse without `--force`.
   - Confirmation: interactive `read -r -p` requiring the word `restore`, or
     `RESTORE_CONFIRM=restore` for non-interactive.
   - PostgreSQL restore drops `db_csm_set` / `db_gateway` and replays the dump (with the
     postgres-role line filter from §5).
   - MongoDB restore uses `mongorestore --drop` for per-collection idempotency, with
     `docker cp` to land the dump into the container and a cleanup `rm -rf` afterward.
5. **Verification** — Run the end-to-end runbook (see §7). Discovered the
   `pg_dumpall` non-idempotency on first restore attempt; fixed via `--clean --if-exists`
   in `backup.sh` plus the `sed` filter for the postgres role in `restore.sh`. Committed
   as `infra: make backup/restore round-trip idempotent against live cluster`.
6. **Commit 4 — `docs: document healthcheck verification, backup, and restore runbook`**
   (`README.md`): replace the old single-block "Backup and restore" section with three
   new sections (Healthcheck verification, Backup, Restore), each capturing the safety
   semantics so an operator does not need to read the script source.
7. **Commit 5 — `docs: add Phase 4 operations and health-check plan`** (this file +
   `ROADMAP.md` `Current status` block + `CHANGELOG.md` `[Unreleased]` Phase 4 entries).
8. **Quality gate** — `uv run ruff check . && uv run ruff format --check . && uv run
   mypy src tests && uv run pytest`. No Python changes in this phase, so coverage gate is
   a no-op against existing tests.
9. **Push branch and open PR** to `main` with the title
   `Phase 4 — Operations & Health Check`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `.gitignore` | MODIFY | Add `backups/` exclusion (closes Phase 1 omission) |
| `scripts/backup.sh` | MODIFY | `.env` sourcing, MongoDB auth via `docker exec -e`, health pre-flight, ERR trap, `BASH_SOURCE`-relative `BACKUP_DIR`, UTC timestamps, `pg_dumpall --clean --if-exists` |
| `scripts/restore.sh` | CREATE | New script: `--list`, `--force`, `--postgres-only`, `--mongo-only`; interactive + `RESTORE_CONFIRM` confirmation; `mongorestore --drop` and filtered `pg_dumpall` replay for idempotency |
| `README.md` | MODIFY | New Healthcheck verification / Backup / Restore sections; directory tree updated to include `restore.sh` |
| `CHANGELOG.md` | MODIFY | `[Unreleased]` Phase 4 Added + Fixed blocks |
| `docs/plans/ROADMAP.md` | MODIFY | `Current status`: Active phase → Phase 5; append "Phase 4 (2026-05-06)" to Completed phases |
| `docs/plans/phase_4_operations_health_check/phase_4_operations_health_check.md` | CREATE | This file |

---

## Success Criteria

- [x] `docker compose ps` reports `(healthy)` for `quant-postgres` and `quant-mongo`.
- [x] `scripts/backup.sh` aborts when either container is unhealthy.
- [x] `scripts/backup.sh` authenticates to MongoDB and produces both
      `backups/pg_all_<UTC-ts>.sql` and `backups/mongo_<UTC-ts>/` with non-zero size.
- [x] `scripts/restore.sh --list` enumerates available backups with their engine coverage.
- [x] `scripts/restore.sh <ts>` (without `--force`) refuses on a non-empty target.
- [x] `scripts/restore.sh --force <ts>` (with `RESTORE_CONFIRM=restore`) restores both
      engines end-to-end; probe rows present after restore match probe rows pre-deletion.
- [x] `backups/` is gitignored.
- [x] `README.md` covers healthcheck verification, backup, and restore.
- [x] `CHANGELOG.md` `[Unreleased]` includes Phase 4 entries.
- [x] `docs/plans/ROADMAP.md` `Current status` advanced past Phase 4.
- [x] Quality gate passes: `ruff check`, `ruff format --check`, `mypy --strict`, `pytest`.

---

## Verification

The commands below were run against the live stack on 2026-05-06. Output is recorded
verbatim (trimmed where noted) so a reviewer can audit the procedure.

### Healthcheck evidence

```text
$ docker compose ps
NAME             IMAGE                               STATUS
quant-mongo      mongo:latest                        Up About an hour (healthy)
quant-postgres   timescale/timescaledb:latest-pg16   Up About an hour (healthy)

$ docker inspect --format '{{.State.Health.Status}}' quant-postgres
healthy

$ docker inspect --format '{{.State.Health.Status}}' quant-mongo
healthy
```

Last health-log entry from each container (extracted via
`docker inspect ... .State.Health.Log`):

```text
quant-postgres → ExitCode: 0
                 Output:    /var/run/postgresql:5432 - accepting connections

quant-mongo    → ExitCode: 0
                 Output:    { ok: 1 }
```

### End-to-end backup → mutate → restore round-trip

Probe rows seeded with `strategy_id='PROBE_PHASE4'` to avoid colliding with real data.

```text
$ docker exec ... psql -d db_csm_set -c "INSERT INTO trade_history ..."
INSERT 0 1

$ docker exec ... mongosh ... --eval "db.signal_snapshots.insertOne({strategy_id:'PROBE_PHASE4', ...})"
{ acknowledged: true, insertedId: ObjectId('69fad86f02515340873d88b3') }

$ bash scripts/backup.sh
=== Backing up PostgreSQL ===
PostgreSQL backup saved: pg_all_20260506_060737Z.sql
=== Backing up MongoDB ===
MongoDB backup saved: mongo_20260506_060737Z/
Backup complete. Artefacts:
-rw-r--r-- ... 29K ... backups/pg_all_20260506_060737Z.sql
36K     backups/mongo_20260506_060737Z

$ # Mutate: delete probes
DELETE 1
{ acknowledged: true, deletedCount: 1 }

$ RESTORE_CONFIRM=restore bash scripts/restore.sh --force 20260506_060737Z
=== Restoring PostgreSQL from pg_all_20260506_060737Z.sql ===
PostgreSQL restore complete.
=== Restoring MongoDB from mongo_20260506_060737Z/ ===
MongoDB restore complete.
Restore complete from timestamp: 20260506_060737Z

$ # Verify probes restored
postgres probe rows: 1 (expected 1)
mongo   probe docs: 1 (expected 1)
✓ E2E PASSED
```

### Negative tests

```text
# Refuse without --force on non-empty cluster:
$ bash scripts/restore.sh 20260506_060737Z
ERROR: Refusing to restore into a non-empty cluster. Use --force to override.

# Refuse when a container is unhealthy:
$ docker stop quant-mongo && bash scripts/backup.sh
ERROR: quant-mongo is not healthy (status=unhealthy). Aborting backup.
```

### Notes on `pg_dump` warnings

Running `pg_dumpall` against a TimescaleDB-enabled cluster produces six warnings about
"circular foreign-key constraints" on the internal `_timescaledb_catalog.hypertable`,
`chunk`, and `continuous_agg` tables. These are cosmetic and do not affect the dump's
integrity for our usage; the warnings are reproduced verbatim in the script output but do
not cause a non-zero exit code. They reinforce the "Out of Scope" decision to defer a
TimescaleDB-aware backup format to a follow-up.

---

## Completion Notes

### Summary

Phase 4 finalised three operational capabilities:

1. **Healthcheck verification.** Both containers reach `healthy` and the procedure to
   confirm this is documented.
2. **Backup hardening.** `scripts/backup.sh` now authenticates to MongoDB, refuses to run
   against an unhealthy stack, cleans up partial artefacts on error, produces an
   idempotent dump that can be replayed against a live cluster, and is safe to invoke
   from any working directory.
3. **Restore procedure.** A new `scripts/restore.sh` provides a reviewable, idempotent
   restore path with three layers of destructive-action protection.

### Issues Encountered

1. **`backup.sh` was silently broken under MongoDB auth.** Phase 3 (commit `02611e1`)
   added `MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD` to the container env,
   but the `mongodump` invocation in `backup.sh` was unchanged and connected without
   credentials. Fix: pass credentials via `docker exec -e`, authenticate against `admin`.
2. **`.gitignore` was missing `backups/`.** The Phase 1 ROADMAP checkbox marked the task
   complete, but the entry was never added. Easy fix; flagged so the same gap doesn't
   recur in future phase audits.
3. **`pg_dumpall` is not idempotent against a live cluster** even with `--clean
   --if-exists`. The cluster superuser role triggers a chicken-and-egg conflict: psql
   cannot drop the role it is currently authenticated as. Fix: filter the two offending
   lines (`DROP ROLE IF EXISTS postgres;` and `CREATE ROLE postgres;`) on restore. The
   trailing `ALTER ROLE postgres WITH ... PASSWORD ...` still applies and keeps the role
   in sync with the dump.

### Lessons

- **Verify, don't assume.** Multiple ROADMAP checkboxes (`[x] Restore from a backup at
  least once`, `[x] Create the backups/ folder (gitignored)`) had been ticked without
  producing reusable artefacts. The phase plan doc now serves as the durable record of
  *how* the work was completed, separate from the ROADMAP's intent record.
- **Auth changes ripple.** Adding container-level auth in Phase 3 silently broke
  `backup.sh`. A future enhancement is a CI smoke test that runs `scripts/backup.sh`
  against an ephemeral stack so this kind of drift is caught at PR time.
- **Idempotent dumps need explicit flags.** `pg_dumpall` defaults to a fresh-cluster
  format; `--clean --if-exists` plus the postgres-role filter are required for a live
  restore. This is the kind of friction a TimescaleDB-aware backup tool would smooth out.

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Code)
**Status:** Complete
**Completed:** 2026-05-06
