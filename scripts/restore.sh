#!/usr/bin/env bash
#
# Restore PostgreSQL and/or MongoDB from a timestamped backup produced by
# scripts/backup.sh.
#
# Usage:
#   scripts/restore.sh --list
#   scripts/restore.sh [--postgres-only|--mongo-only] [--force] <timestamp>
#
# Arguments:
#   <timestamp>          The shared timestamp produced by backup.sh,
#                        e.g. 20260506_153012Z. Resolves to:
#                            backups/pg_all_<timestamp>.sql
#                            backups/mongo_<timestamp>/
#
# Flags:
#   --list               Print every available <timestamp> under backups/
#                        and exit.
#   --postgres-only      Restore only PostgreSQL.
#   --mongo-only         Restore only MongoDB.
#   --force              Required when the target databases are non-empty.
#                        Without it, the script refuses to overwrite
#                        existing data.
#
# Safety:
#   1. Both target containers must report healthy.
#   2. Backup files for the requested engines must exist.
#   3. Non-empty targets require --force.
#   4. With --force AND a TTY, the operator must type "restore" at the
#      prompt. For non-interactive use, set RESTORE_CONFIRM=restore.
#
# Idempotency:
#   - PostgreSQL: drops db_csm_set / db_gateway before replaying the dump.
#   - MongoDB:   uses mongorestore --drop to clear each collection.
#
# Cross-engine atomicity is NOT provided. If a Mongo restore fails after
# the Postgres restore succeeded, re-run with --mongo-only.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

usage() {
    sed -n '2,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-1}"
}

list_backups() {
    if [[ ! -d "${BACKUP_DIR}" ]]; then
        echo "No backups directory at ${BACKUP_DIR}"
        return 0
    fi
    local found=0
    while IFS= read -r f; do
        local ts
        ts="${f#pg_all_}"; ts="${ts%.sql}"
        local mongo="${BACKUP_DIR}/mongo_${ts}"
        if [[ -d "${mongo}" ]]; then
            printf '%s  postgres+mongo\n' "${ts}"
        else
            printf '%s  postgres-only\n' "${ts}"
        fi
        found=1
    done < <(cd "${BACKUP_DIR}" && ls -1 | grep -E '^pg_all_.*\.sql$' | sort -r || true)

    while IFS= read -r d; do
        local ts="${d#mongo_}"
        if [[ ! -f "${BACKUP_DIR}/pg_all_${ts}.sql" ]]; then
            printf '%s  mongo-only\n' "${ts}"
            found=1
        fi
    done < <(cd "${BACKUP_DIR}" && ls -1d mongo_* 2>/dev/null | sort -r || true)

    if [[ "${found}" -eq 0 ]]; then
        echo "No backups found in ${BACKUP_DIR}"
    fi
}

require_healthy() {
    local name="$1"
    local status
    status="$(docker inspect --format '{{.State.Health.Status}}' "${name}" 2>/dev/null || echo missing)"
    if [[ "${status}" != "healthy" ]]; then
        echo "ERROR: ${name} is not healthy (status=${status}). Aborting restore." >&2
        exit 1
    fi
}

postgres_user_db_count() {
    docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" quant-postgres \
        psql -U postgres -d postgres -tAc \
        "SELECT count(*) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1');"
}

mongo_doc_count() {
    docker exec \
        -e MONGO_USER="${MONGO_INITDB_ROOT_USERNAME}" \
        -e MONGO_PASS="${MONGO_INITDB_ROOT_PASSWORD}" \
        quant-mongo \
        sh -c 'mongosh --quiet \
            --username "$MONGO_USER" --password "$MONGO_PASS" \
            --authenticationDatabase admin csm_logs \
            --eval "print(db.backtest_results.countDocuments({}) + db.model_params.countDocuments({}) + db.signal_snapshots.countDocuments({}))"'
}

confirm_destructive() {
    if [[ "${RESTORE_CONFIRM:-}" == "restore" ]]; then
        return 0
    fi
    if [[ -t 0 ]]; then
        local reply
        read -r -p "This will DESTROY existing data in quant-postgres and/or quant-mongo. Type 'restore' to proceed: " reply
        if [[ "${reply}" != "restore" ]]; then
            echo "Aborted."
            exit 1
        fi
    else
        echo "ERROR: --force in non-interactive mode requires RESTORE_CONFIRM=restore." >&2
        exit 1
    fi
}

restore_postgres() {
    local ts="$1"
    local dump="${BACKUP_DIR}/pg_all_${ts}.sql"
    if [[ ! -f "${dump}" ]]; then
        echo "ERROR: PostgreSQL dump not found: ${dump}" >&2
        exit 1
    fi
    echo "=== Restoring PostgreSQL from pg_all_${ts}.sql ==="
    # The dump (pg_dumpall --clean --if-exists) is idempotent against existing
    # databases, but pg_dumpall always emits DROP/CREATE ROLE for the cluster
    # superuser. Both fail when replayed against a live cluster: psql cannot
    # drop the role it is currently authenticated as, and the subsequent
    # CREATE collides with the existing role. Stripping just those two lines
    # leaves the trailing ALTER ROLE ... PASSWORD ... intact, which keeps the
    # role's attributes in sync with the dump.
    sed -e '/^DROP ROLE IF EXISTS postgres;$/d' \
        -e '/^CREATE ROLE postgres;$/d' \
        "${dump}" \
    | docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" quant-postgres \
        psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q >/dev/null
    echo "PostgreSQL restore complete."
}

restore_mongo() {
    local ts="$1"
    local dump="${BACKUP_DIR}/mongo_${ts}"
    if [[ ! -d "${dump}" ]]; then
        echo "ERROR: MongoDB dump not found: ${dump}" >&2
        exit 1
    fi
    echo "=== Restoring MongoDB from mongo_${ts}/ ==="
    docker cp "${dump}" "quant-mongo:/tmp/mongorestore_${ts}"
    docker exec \
        -e MONGO_USER="${MONGO_INITDB_ROOT_USERNAME}" \
        -e MONGO_PASS="${MONGO_INITDB_ROOT_PASSWORD}" \
        quant-mongo \
        sh -c 'mongorestore \
            --username "$MONGO_USER" --password "$MONGO_PASS" \
            --authenticationDatabase admin --drop --quiet \
            "/tmp/mongorestore_'"${ts}"'"'
    docker exec quant-mongo rm -rf "/tmp/mongorestore_${ts}"
    echo "MongoDB restore complete."
}

# ─── argument parsing ─────────────────────────────────────────────────
SCOPE="all"        # all | postgres | mongo
FORCE=0
TIMESTAMP=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --list)            list_backups; exit 0 ;;
        --postgres-only)   SCOPE="postgres"; shift ;;
        --mongo-only)      SCOPE="mongo"; shift ;;
        --force)           FORCE=1; shift ;;
        -h|--help)         usage 0 ;;
        --)                shift; break ;;
        -*)                echo "Unknown flag: $1" >&2; usage 1 ;;
        *)                 if [[ -n "${TIMESTAMP}" ]]; then
                               echo "Unexpected positional arg: $1" >&2; usage 1
                           fi
                           TIMESTAMP="$1"; shift ;;
    esac
done

if [[ -z "${TIMESTAMP}" ]]; then
    echo "ERROR: <timestamp> is required (use --list to see available)." >&2
    usage 1
fi

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set (via .env or environment)}"
: "${MONGO_INITDB_ROOT_USERNAME:?MONGO_INITDB_ROOT_USERNAME must be set (via .env or environment)}"
: "${MONGO_INITDB_ROOT_PASSWORD:?MONGO_INITDB_ROOT_PASSWORD must be set (via .env or environment)}"

# ─── safety checks ────────────────────────────────────────────────────
[[ "${SCOPE}" == "mongo"    ]] || require_healthy quant-postgres
[[ "${SCOPE}" == "postgres" ]] || require_healthy quant-mongo

NEEDS_FORCE=0
if [[ "${SCOPE}" != "mongo" ]]; then
    if [[ "$(postgres_user_db_count)" -gt 0 ]]; then
        NEEDS_FORCE=1
    fi
fi
if [[ "${SCOPE}" != "postgres" ]]; then
    if [[ "$(mongo_doc_count)" -gt 0 ]]; then
        NEEDS_FORCE=1
    fi
fi

if [[ "${NEEDS_FORCE}" -eq 1 && "${FORCE}" -eq 0 ]]; then
    echo "ERROR: Refusing to restore into a non-empty cluster. Use --force to override." >&2
    exit 1
fi

if [[ "${FORCE}" -eq 1 ]]; then
    confirm_destructive
fi

# ─── execute ──────────────────────────────────────────────────────────
case "${SCOPE}" in
    postgres) restore_postgres "${TIMESTAMP}" ;;
    mongo)    restore_mongo    "${TIMESTAMP}" ;;
    all)      restore_postgres "${TIMESTAMP}"; restore_mongo "${TIMESTAMP}" ;;
esac

echo ""
echo "Restore complete from timestamp: ${TIMESTAMP}"
