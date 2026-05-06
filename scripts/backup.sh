#!/usr/bin/env bash
#
# Backup PostgreSQL (pg_dumpall) and MongoDB (mongodump) to ./backups/.
#
# Requires: docker, a running quant-postgres + quant-mongo stack with
# healthchecks reporting healthy, and the credentials in .env (or exported
# in the environment).
#
# Output:
#   backups/pg_all_<UTC-timestamp>.sql
#   backups/mongo_<UTC-timestamp>/
#
# The script aborts if either container is not healthy and removes any
# partially written artefacts on error.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"
DATE="$(date -u +%Y%m%d_%H%M%SZ)"

if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set (via .env or environment)}"
: "${MONGO_INITDB_ROOT_USERNAME:?MONGO_INITDB_ROOT_USERNAME must be set (via .env or environment)}"
: "${MONGO_INITDB_ROOT_PASSWORD:?MONGO_INITDB_ROOT_PASSWORD must be set (via .env or environment)}"

require_healthy() {
    local name="$1"
    local status
    status="$(docker inspect --format '{{.State.Health.Status}}' "${name}" 2>/dev/null || echo missing)"
    if [[ "${status}" != "healthy" ]]; then
        echo "ERROR: ${name} is not healthy (status=${status}). Aborting backup." >&2
        exit 1
    fi
}

cleanup_on_error() {
    echo "Backup failed; removing partial artefacts" >&2
    rm -f  "${BACKUP_DIR}/pg_all_${DATE}.sql"
    rm -rf "${BACKUP_DIR}/mongo_${DATE}"
    docker exec quant-mongo rm -rf "/tmp/mongodump_${DATE}" 2>/dev/null || true
}
trap cleanup_on_error ERR

mkdir -p "${BACKUP_DIR}"

require_healthy quant-postgres
require_healthy quant-mongo

echo "=== Backing up PostgreSQL ==="
# --clean --if-exists makes the dump idempotent on replay: DROP statements
# precede every CREATE, guarded by IF EXISTS, so restore.sh can target a
# populated cluster without role/database collisions.
docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" quant-postgres \
    pg_dumpall -U postgres --clean --if-exists \
    > "${BACKUP_DIR}/pg_all_${DATE}.sql"
echo "PostgreSQL backup saved: pg_all_${DATE}.sql"

echo "=== Backing up MongoDB ==="
docker exec \
    -e MONGO_USER="${MONGO_INITDB_ROOT_USERNAME}" \
    -e MONGO_PASS="${MONGO_INITDB_ROOT_PASSWORD}" \
    quant-mongo \
    sh -c 'mongodump \
        --username "$MONGO_USER" \
        --password "$MONGO_PASS" \
        --authenticationDatabase admin \
        --out "/tmp/mongodump_'"${DATE}"'"'

docker cp "quant-mongo:/tmp/mongodump_${DATE}" "${BACKUP_DIR}/mongo_${DATE}"
docker exec quant-mongo rm -rf "/tmp/mongodump_${DATE}"
echo "MongoDB backup saved: mongo_${DATE}/"

trap - ERR

echo ""
echo "Backup complete. Artefacts:"
ls -lh "${BACKUP_DIR}/pg_all_${DATE}.sql"
du -sh "${BACKUP_DIR}/mongo_${DATE}"
