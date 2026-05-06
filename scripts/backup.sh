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

echo ""
echo "Backup complete. Artefacts:"
ls -lh "$BACKUP_DIR/pg_all_${DATE}.sql"
du -sh "$BACKUP_DIR/mongo_${DATE}"
