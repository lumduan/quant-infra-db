# Migrate DB Data Storage to Project Root Directories

**Feature:** Database data stored in project-root bind mounts instead of Docker named volumes
**Branch:** `feature/phase-5-documentation`
**Created:** 2026-05-06
**Status:** Draft
**Depends On:** Phase 1 (Complete), Phase 2 (Complete), Phase 3 (Complete), Phase 4 (Complete)

---

## Table of Contents

1. [Overview](#overview)
2. [Scope](#scope)
3. [Design Decisions](#design-decisions)
4. [Implementation Steps](#implementation-steps)
5. [File Changes](#file-changes)
6. [Migration Guide](#migration-guide)
7. [Success Criteria](#success-criteria)
8. [Verification](#verification)
9. [Rollback](#rollback)

---

## Overview

### Purpose

The project currently stores PostgreSQL and MongoDB data in Docker-managed named
volumes (`quant-infra-db_postgres_data`, `quant-infra-db_mongo_data`). These volumes
live inside Docker's internal storage (`/var/lib/docker/volumes/`) and are opaque to
the host filesystem — they can't be inspected with `ls`, backed up at the filesystem
level, or easily migrated between hosts.

This change replaces named volumes with **bind mounts** at `./postgres_data/` and
`./mongo_data/` in the project root. The database files become directly visible,
portable, and colocated with the project source. The existing `scripts/backup.sh`
logical backups remain the primary backup and migration path; bind mounts add
filesystem-level visibility as a secondary benefit.

### Parent Plan Reference

- `docs/plans/ROADMAP.md` — Phase 1.2 "Docker Compose — Core services" (volume configuration)

### Key Deliverables

1. Updated `docker-compose.yml` — bind mounts replace named volumes; top-level `volumes:` section removed.
2. Updated `.gitignore` — `postgres_data/` and `mongo_data/` excluded from version control.
3. This plan document with migration guide and rollback steps.

---

## Scope

### In Scope

| Component | Description | Status |
|---|---|---|
| `docker-compose.yml` volume mounts | Replace named volumes with `./postgres_data` and `./mongo_data` bind mounts | Draft |
| Top-level `volumes:` section | Remove the now-unused named volume declarations | Draft |
| `.gitignore` | Add `postgres_data/` and `mongo_data/` exclusions | Draft |
| Migration guide | Step-by-step instructions for users with existing data in named volumes | Draft |
| Verification | `docker compose up -d` + healthcheck confirmation | Pending |

### Out of Scope

- Changes to `scripts/backup.sh` or `scripts/restore.sh` — logical backup/restore
  works identically regardless of where the live data lives.
- Changes to init scripts — they run on first container start regardless of mount type.
- Filesystem-level snapshot backups (e.g., `tar` of `postgres_data/`) — the logical
  backup scripts remain the documented, supported backup path.
- Docker volume driver or storage plugin configuration.

---

## Design Decisions

### 1. Relative paths over absolute paths

Using `./postgres_data:/var/lib/postgresql/data` (relative) rather than an absolute
path like `/home/user/projects/quant-infra-db/postgres_data:/var/lib/postgresql/data`.
Docker Compose resolves relative paths from the location of `docker-compose.yml`,
making the configuration portable across hosts and development environments.

### 2. Keep the `./init-scripts` bind mounts as-is

The init script mounts are already bind mounts and do not store mutable data.
No change needed.

### 3. No `docker compose down -v` safety net needed

With named volumes, `docker compose down -v` destroys all data — a well-known footgun.
With bind mounts, `docker compose down -v` does NOT delete `./postgres_data/` or
`./mongo_data/` (Docker only removes named volumes, not bind-mounted host directories).
This means data survives `down -v`, which is safer for development. To fully reset:
`docker compose down && rm -rf postgres_data/ mongo_data/`.

### 4. No Docker Compose `volumes:` section at all

Once the named volumes are removed, there is no remaining use for the top-level
`volumes:` key. Removing it entirely makes the compose file simpler and avoids
confusion about whether named volumes still exist.

### 5. Rely on official image entrypoint scripts for permissions

Both the PostgreSQL (`timescale/timescaledb`) and MongoDB (`mongo`) official images
include entrypoint scripts that detect and fix ownership of the data directory on
first start. This means Docker Compose can create the bind-mount directories (as root)
and the containers will `chown` them to the correct user (`postgres` UID 999,
`mongodb` UID 999) during initialization. No manual `chown` or `user:` directive
needed.

---

## Implementation Steps

1. **Edit `docker-compose.yml`** — Three changes:
   - PostgreSQL: `postgres_data:/var/lib/postgresql/data` → `./postgres_data:/var/lib/postgresql/data`
   - MongoDB: `mongo_data:/data/db` → `./mongo_data:/data/db`
   - Remove the top-level `volumes:` block (lines 43-47).
2. **Edit `.gitignore`** — Add `postgres_data/` and `mongo_data/` under a new
   `# Database data` section after the existing `# Backups` block.
3. **Verify fresh start** — `docker compose down && rm -rf postgres_data/ mongo_data/ && docker compose up -d`.
   Confirm `(healthy)` on both containers and init scripts run.
4. **Verify data survival** — `docker compose down && docker compose up -d`.
   Confirm init scripts do NOT re-run (data directories are non-empty) and
   `(healthy)` on both containers.
5. **Verify gitignore** — `git status` does not show `postgres_data/` or `mongo_data/`
   as untracked.
6. **Quality gate** — `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests && uv run pytest`.
7. **Commit** — Single commit with message following Conventional Commits:
   `infra: migrate DB data to project-root bind mounts`.

---

## File Changes

| File | Action | Description |
|---|---|---|
| `docker-compose.yml` | MODIFY | Replace named volumes with `./postgres_data` and `./mongo_data` bind mounts; remove top-level `volumes:` section |
| `.gitignore` | MODIFY | Add `postgres_data/` and `mongo_data/` exclusions |
| `docs/plans/db-data-in-project-root.md` | CREATE | This file |

---

## Migration Guide

### For users with existing data in named volumes

If you already have data in `quant-infra-db_postgres_data` and
`quant-infra-db_mongo_data`, follow these steps to migrate without data loss:

```bash
# Step 1: Back up existing data
bash scripts/backup.sh
# Produces: backups/pg_all_<timestamp>.sql and backups/mongo_<timestamp>/

# Step 2: Stop the stack
docker compose down

# Step 3: Remove the old named volumes
docker volume rm quant-infra-db_postgres_data quant-infra-db_mongo_data

# Step 4: Update docker-compose.yml (git pull or manual edit)
git pull

# Step 5: Start the stack with bind mounts
# Docker Compose creates ./postgres_data/ and ./mongo_data/ automatically;
# init scripts run on the empty data directories
docker compose up -d

# Step 6: Wait for healthy, then restore data
# Use the timestamp from Step 1
RESTORE_CONFIRM=restore bash scripts/restore.sh --force <timestamp>

# Step 7: Verify
docker compose ps   # both should show (healthy)
```

**Warning:** If you skip Step 3, the old named volumes persist on disk (orphaned
but safe). The new bind-mounted directories receive fresh initializations. To clean
up orphaned volumes later:
```bash
docker volume ls | grep quant-infra-db
docker volume rm quant-infra-db_postgres_data quant-infra-db_mongo_data
```

### For users with no existing data (fresh clone or empty volumes)

No migration needed. Pull the updated `docker-compose.yml` and run
`docker compose up -d`. Docker Compose creates `./postgres_data/` and `./mongo_data/`
automatically on first start.

---

## Success Criteria

- [ ] `docker compose up -d` from a clean state starts both containers with `(healthy)` status.
- [ ] `ls postgres_data/` shows PostgreSQL data files (`PG_VERSION`, `base/`, `pg_wal/`).
- [ ] `ls mongo_data/` shows MongoDB data files (`WiredTiger`, `diagnostic.data/`).
- [ ] `docker compose down && docker compose up -d` — data survives restart; init
      scripts do NOT re-run.
- [ ] `git status` — `postgres_data/` and `mongo_data/` are not shown as untracked.
- [ ] Quality gate passes: `ruff check`, `ruff format --check`, `mypy --strict`, `pytest`.
- [ ] `scripts/backup.sh` and `scripts/restore.sh` work correctly against the
      bind-mounted stack.
- [ ] No Docker named volumes remain after migration.

---

## Verification

### Fresh start

```text
$ docker compose down
$ rm -rf postgres_data/ mongo_data/
$ docker compose up -d
$ docker compose ps
NAME             IMAGE                               STATUS
quant-mongo      mongo:latest                        Up (healthy)
quant-postgres   timescale/timescaledb:latest-pg16   Up (healthy)

$ ls postgres_data/
PG_VERSION    base/         pg_hba.conf   pg_wal/       postgresql.conf
...

$ ls mongo_data/
WiredTiger    diagnostic.data/    journal/
...
```

### Data survival across restart

```text
$ docker compose down
$ docker compose up -d
$ docker compose ps
# Both should show (healthy)
# Init scripts should NOT re-run (data directories are non-empty)
$ docker compose logs | grep -c "CREATE DATABASE"
0   # No CREATE DATABASE on second start — init scripts skipped
```

### gitignore

```text
$ git status
# postgres_data/ and mongo_data/ must NOT appear in untracked files
```

---

## Rollback

If the bind-mount approach causes issues (e.g., permissions problems on a specific
Linux host, or unacceptable I/O performance on macOS), revert as follows:

```bash
# 1. Back up data from the bind mounts
bash scripts/backup.sh

# 2. Stop the stack and remove the bind-mount directories
docker compose down
rm -rf postgres_data/ mongo_data/

# 3. Revert docker-compose.yml to named volumes
git revert <commit-hash>

# 4. Start with named volumes
docker compose up -d

# 5. Restore data
RESTORE_CONFIRM=restore bash scripts/restore.sh --force <timestamp>
```

---

## Completion Notes

### Summary

This change moves PostgreSQL and MongoDB data storage from Docker-managed named volumes
to project-root bind mounts (`./postgres_data/` and `./mongo_data/`). The data becomes
directly visible on the host filesystem, portable across environments, and safe from
accidental `docker compose down -v` deletion. The existing logical backup and restore
scripts continue to work identically.

### Issues Encountered

*To be filled in during implementation.*

### Lessons

*To be filled in during implementation.*

---

**Document Version:** 1.0
**Author:** AI Agent (Claude Code)
**Status:** Draft
