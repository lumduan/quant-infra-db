#!/usr/bin/env bash
# Install config/pg_hba.conf into the RUNNING quant-postgres and apply it with a RELOAD — no restart.
# TK-0621 interim access restriction (operator ruling 2026-09-29). Run on HOME, as a user with docker access.
#
#   scripts/apply_pg_hba.sh --dry-run   checks only: subnet, parse on the server, the diff. Changes nothing.
#   scripts/apply_pg_hba.sh             backup -> install -> server-side parse check -> reload
#   scripts/apply_pg_hba.sh --rollback  restore the newest backup this script made, then reload
#
# Every step verifies before the next: a subnet mismatch or a parse error changes NOTHING that stays.
# pg_hba applies to NEW connections only; sessions already open are not disconnected by a reload.
# No password, hash or DSN is read or printed: psql runs over the container's local socket (trust).
set -euo pipefail
C="${PG_CONTAINER:-quant-postgres}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
NEW="$HERE/config/pg_hba.conf"
LIVE=/var/lib/postgresql/data/pg_hba.conf
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MODE=apply
case "${1:-}" in --dry-run) MODE=dry ;; --rollback) MODE=rollback ;; "") ;; *) echo "usage: $0 [--dry-run|--rollback]" >&2; exit 2 ;; esac
psqlc() { docker exec "$C" psql -U postgres -Atc "$1"; }
errors() { psqlc "select line_number || ': ' || error from pg_hba_file_rules where error is not null"; }
reload() { [ "$(psqlc 'select pg_reload_conf()')" = t ] || { echo "🔴 pg_reload_conf() did not return t"; exit 5; }; }

if [ "$MODE" = rollback ]; then
  B=$(docker exec "$C" sh -c "ls -1t $LIVE.bak-tk0621-* 2>/dev/null | head -1")
  [ -n "$B" ] || { echo "🔴 no backup found ($LIVE.bak-tk0621-*) — nothing restored"; exit 4; }
  docker exec "$C" cp -p "$B" "$LIVE"
  E=$(errors); [ -z "$E" ] || { echo "🔴 the backup does not parse: $E"; exit 5; }
  reload; echo "✅ ROLLED BACK to $B and reloaded ($STAMP)"; exit 0
fi

[ -f "$NEW" ] || { echo "🔴 $NEW missing"; exit 3; }
want=$(awk '$1=="host" && $5=="scram-sha-256" {print $4}' "$NEW" | sort -u)
have=$(docker network inspect quant-network -f '{{range .IPAM.Config}}{{.Subnet}} {{end}}' | xargs -n1 | sort -u)
[ "$want" = "$have" ] || { echo "🔴 REFUSED: the file admits '$want' but quant-network is '$have' — every container would be refused"; exit 3; }
echo "✅ subnet: the file admits exactly quant-network ($have)"

echo "--- diff, live -> new"
docker exec "$C" cat "$LIVE" | grep -vE '^\s*(#|$)' > "/tmp/pg_hba.live.$$" || true
grep -vE '^\s*(#|$)' "$NEW" | diff -u --label live --label new "/tmp/pg_hba.live.$$" - || true
rm -f "/tmp/pg_hba.live.$$"

if [ "$MODE" = dry ]; then
  # pg_hba_file_rules parses only the ACTIVE hba_file, so a dry run checks the shape locally and writes nothing.
  bad=$(grep -vE '^\s*(#|$)' "$NEW" | awk '!($1=="local" && NF==4) && !($1=="host" && NF==5) {print NR": "$0}')
  [ -z "$bad" ] || { echo "🔴 malformed lines: $bad"; exit 5; }
  echo "✅ DRY RUN: well-formed, subnet matches, nothing changed"; exit 0
fi

# Stage the new file beside the live one, owned as Postgres expects, before touching the live path.
docker cp "$NEW" "$C:$LIVE.candidate-$STAMP"
docker exec "$C" sh -c "chown postgres:postgres $LIVE.candidate-$STAMP && chmod 600 $LIVE.candidate-$STAMP"
docker exec "$C" cp -p "$LIVE" "$LIVE.bak-tk0621-$STAMP"
echo "✅ backup: $LIVE.bak-tk0621-$STAMP"
docker exec "$C" mv "$LIVE.candidate-$STAMP" "$LIVE"
E=$(errors)
if [ -n "$E" ]; then
  docker exec "$C" cp -p "$LIVE.bak-tk0621-$STAMP" "$LIVE"
  echo "🔴 the new file does not parse on the server — RESTORED the backup, NOT reloaded: $E"; exit 5
fi
reload
echo "✅ installed and reloaded ($STAMP). Rules now on disk:"
psqlc "select line_number, type, database, user_name, coalesce(address,''), coalesce(netmask,''), auth_method from pg_hba_file_rules order by line_number"
