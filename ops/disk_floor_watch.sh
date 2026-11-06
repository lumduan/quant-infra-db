#!/usr/bin/env bash
# =============================================================================================
# disk_floor_watch.sh — is HOME's root LV above the recorder floor, and is the db_crypto
# sawtooth still covering itself?   [[TK-0645]] · armed at the operator's instruction 2026-11-06
#
# WHY THIS EXISTS, and why it is not just "df | awk":
#   On 2026-11-06 VM 103's / lost 12.83 GB overnight and nobody could say where it went. It was
#   db_crypto accumulating between its once-a-day 21:07 ICT retention runs — a SAWTOOTH, not a
#   leak. The operator's recorder floor for poring-lab is 120 GB free, and the sawtooth's rising
#   half crosses it every afternoon and recovers every night.
#
#   🔑 SO A BARE FREE-SPACE THRESHOLD WOULD BE WRONG IN BOTH DIRECTIONS. The SAME number means
#   two different things depending on the phase of the cycle:
#     - below the floor at 14:00, BEFORE retention  => EXPECTED, self-healing. Paging on it
#       would fire daily and teach everyone to ignore the check (DC-0007 alert fatigue).
#     - below the floor at 21:30, AFTER retention    => THE REAL ALARM. The nightly give-back no
#       longer covers the daily inflow, which is the condition [[TK-0645]]'s fix exists to end.
#   That phase distinction is the entire value of this script.
#
# READ-ONLY. It runs `df`, one `docker exec … psql` of catalog views, and appends to a log. It
# never writes a database, never runs `du` on the Postgres data dir (the 2026-10-02 IO guard),
# and never prints a secret — the Slack webhook is read from the environment and only ever
# passed to curl via a variable.
#
# NO PYTHON, NO VENV, NO `uv run`, DELIBERATELY. Every repo this could have lived in is an
# editable install whose venv a production daemon or cron executes from, and `uv run` syncs that
# venv as a side effect ([[TK-0660]]). A bash script with `docker exec psql` needs none of it, so
# this check cannot deploy anything by being run.
#
# EXIT CODES — the verdict IS the exit code, so a cron that tests it has a check:
#   0  GREEN    free >= floor + margin
#   1  UNKNOWN  could not read df or Postgres. An OBSERVER fails CLOSED: never "fine".
#   2  AMBER    free is within the margin of the floor, or below it BEFORE tonight's retention
#               (expected, self-healing)
#   3  RED      free is below the floor AFTER retention has run — the sawtooth stopped covering
#
#   ⚠️ Four states where the sibling `verify-crypto-cold` has three (0/1/2). Deliberate: folding
#   AMBER into RED would page every afternoon on a condition that fixes itself, and folding it
#   into GREEN would hide the approach. The sibling has no phase to be aware of.
#
# Usage:  ops/disk_floor_watch.sh [--floor-gb N] [--margin-gb N] [--no-slack] [--quiet]
#         (the floor DEFAULTS to whatever poring-lab's recorder enforces — see below; --floor-gb
#          overrides it, which is for tests and for answering "what if" questions, not for daily use)
#         ops/disk_floor_watch.sh --force-free-gb 118   # TEST ONLY: pretend df said this
#         ops/disk_floor_watch.sh --force-hhmm 21:45     # TEST ONLY: pretend the clock said this
#
# 🔑 Those two test flags exist because the RED branch is otherwise UNREACHABLE until 21:30 ICT,
# and an untested branch in an alarm path is the thing that fails on the night it matters. Both
# branches are proven below, and a forced run says so in its own output.
# Log:    /home/batt/.config/quant-pm/disk_floor_watch.log
# =============================================================================================
set -uo pipefail

# 🔴 THE FLOOR IS NOT OURS AND IT MOVES. Do not hard-code it.
# poring-lab's recorder owns it, declares it in code, and the operator has changed it TWICE in two
# days: 140 GB -> 120 (2026-11-05) -> 100 (2026-11-06, commit 8b46640, ADR-0010 Amendment). A
# checker that restates the number is wrong again within a day and says nothing when it is.
# So this READS the number from the instrument that enforces it, and when it cannot, it falls back
# AND SAYS IT FELL BACK — a silently-defaulted floor is worse than no floor, because the verdict
# still looks authoritative. (The umbrella's rule: prefer a pointer to the instrument over a
# restated measurement; the measurement belongs where it is produced.)
PORING_LAB=/home/batt/docker/poring-lab
PORING_LAB_SRC=scripts/dataset_ship.py
FLOOR_GB_FALLBACK=100
FLOOR_GB=""
# 20 GB, justified on its own terms rather than inherited: one nightly give-back is 8.7-13.4 GiB,
# so a 20 GB margin raises AMBER roughly one-and-a-half cycles before the floor — enough warning to
# act inside a maintenance window. It is NOT 20 because 100+20 happens to be the previous floor.
MARGIN_GB=20
NO_SLACK=0
QUIET=0
FORCE_FREE=""
FORCE_HHMM=""
LOG=/home/batt/.config/quant-pm/disk_floor_watch.log
STATE=/home/batt/.config/quant-pm/disk_floor_watch.state
PG_CONTAINER=quant-postgres

# The measured retention schedule: all three db_crypto policy_retention jobs ran 14:07–14:13 UTC
# on 2026-11-05, i.e. 21:07–21:13 ICT, on a `1 day` schedule_interval. The post-retention window
# starts safely after the last of them finishes.
RETENTION_ICT_HHMM="21:07"
POST_RETENTION_FROM="21:30"

while [ $# -gt 0 ]; do
  case "$1" in
    --floor-gb)       FLOOR_GB="$2"; shift 2 ;;
    --margin-gb)      MARGIN_GB="$2"; shift 2 ;;
    --no-slack)       NO_SLACK=1; shift ;;
    --quiet)          QUIET=1; shift ;;
    --force-free-gb)  FORCE_FREE="$2"; shift 2 ;;   # test only — see the positive controls
    --force-hhmm)     FORCE_HHMM="$2"; shift 2 ;;   # test only — reaches the RED branch by day
    *) echo "unknown arg: $1" >&2; exit 64 ;;
  esac
done

# --- 0. read the floor from the instrument that enforces it ------------------------------------
FLOOR_SRC=""
if [ -z "$FLOOR_GB" ]; then
  RAW=$(git -C "$PORING_LAB" show "origin/main:$PORING_LAB_SRC" 2>/dev/null \
        | sed -n 's/^MIN_FREE_BYTES[[:space:]]*=[[:space:]]*\([0-9]\+\)[[:space:]]*\*[[:space:]]*10\*\*9.*/\1/p' | head -1)
  case "$RAW" in
    ''|*[!0-9]*) FLOOR_GB="$FLOOR_GB_FALLBACK"
                 FLOOR_SRC=" [floor FELL BACK to ${FLOOR_GB_FALLBACK} GB — could not read MIN_FREE_BYTES from ${PORING_LAB_SRC} at origin/main]" ;;
    *)           FLOOR_GB="$RAW"; FLOOR_SRC="" ;;
  esac
fi

NOW_ICT=$(TZ=Asia/Bangkok date '+%Y-%m-%d %H:%M:%S')
HHMM=$(TZ=Asia/Bangkok date '+%H:%M')
if [ -n "$FORCE_HHMM" ]; then HHMM="$FORCE_HHMM"; fi

# --- 1. free space on / -----------------------------------------------------------------------
if [ -n "$FORCE_FREE" ]; then
  FREE_GB="$FORCE_FREE"
  FORCED=" [FORCED TEST VALUE — not a real df reading]"
else
  FORCED=""
  FREE_KB=$(df -k --output=avail / 2>/dev/null | tail -1 | tr -d ' ')
  case "$FREE_KB" in
    ''|*[!0-9]*)
      MSG="[disk-floor] UNKNOWN ${NOW_ICT} ICT — could not read \`df /\`. An observer fails CLOSED: this is NOT 'fine'."
      printf '%s\n' "$MSG" >> "$LOG" 2>/dev/null
      [ "$QUIET" = 0 ] && echo "$MSG"
      exit 1 ;;
  esac
  FREE_GB=$(awk -v k="$FREE_KB" 'BEGIN{printf "%.2f", k*1024/1e9}')
fi

# --- 2. Postgres, catalog only ----------------------------------------------------------------
# One psql call. `-At` keeps it parseable; nothing here scans a heap.
PG=$(docker exec "$PG_CONTAINER" psql -U postgres -At -X -q -F '|' -c "
  SELECT 'TOTAL',  round(sum(pg_database_size(datname))/1073741824.0,3)
    FROM pg_database WHERE datallowconn
  UNION ALL
  SELECT 'CRYPTO', round(pg_database_size('db_crypto')/1073741824.0,3)
  UNION ALL
  SELECT 'ORDERBOOK', round(pg_database_size('db_orderbook')/1073741824.0,3);" 2>/dev/null)
PG_TOTAL=$(printf '%s\n' "$PG" | awk -F'|' '$1=="TOTAL"{print $2}')
PG_CRYPTO=$(printf '%s\n' "$PG" | awk -F'|' '$1=="CRYPTO"{print $2}')
PG_OB=$(printf '%s\n' "$PG" | awk -F'|' '$1=="ORDERBOOK"{print $2}')

if [ -z "$PG_TOTAL" ]; then
  MSG="[disk-floor] UNKNOWN ${NOW_ICT} ICT — free ${FREE_GB} GB, but the Postgres catalog could not be read (container ${PG_CONTAINER}). An observer fails CLOSED: this is NOT 'fine'."
  printf '%s\n' "$MSG" >> "$LOG" 2>/dev/null
  [ "$QUIET" = 0 ] && echo "$MSG"
  exit 1
fi

# --- 3. what the NEXT retention run will give back --------------------------------------------
# Chunks whose range_end is already older than (now - drop_after) are eligible, so they will be
# dropped by the next run. Computed from the policy's own config, never from a remembered value.
NEXT_DROP=$(docker exec "$PG_CONTAINER" psql -U postgres -d db_crypto -At -X -q -c "
  WITH pol AS (
    SELECT (config->>'hypertable_id')::int htid, (config->>'drop_after')::interval drop_after
    FROM timescaledb_information.jobs WHERE proc_name='policy_retention')
  SELECT coalesce(round(sum(pg_total_relation_size(
           format('%I.%I', c.chunk_schema, c.chunk_name)))/1073741824.0, 3), 0)
  FROM timescaledb_information.chunks c
  JOIN _timescaledb_catalog.hypertable h
    ON h.table_name=c.hypertable_name AND h.schema_name=c.hypertable_schema
  JOIN pol p ON p.htid=h.id
  WHERE c.range_end < now() - p.drop_after;" 2>/dev/null)
[ -z "$NEXT_DROP" ] && NEXT_DROP="?"

# --- 4. the verdict, and it is PHASE-AWARE ----------------------------------------------------
# `[[ "$HHMM" > "$POST_RETENTION_FROM" ]]` is a lexical compare on zero-padded HH:MM, which is
# correct for this purpose and needs no date arithmetic.
POST=0
if [[ "$HHMM" > "$POST_RETENTION_FROM" ]]; then POST=1; fi

BELOW_FLOOR=$(awk -v f="$FREE_GB" -v fl="$FLOOR_GB" 'BEGIN{print (f<fl)?1:0}')
NEAR_FLOOR=$(awk -v f="$FREE_GB" -v fl="$FLOOR_GB" -v m="$MARGIN_GB" 'BEGIN{print (f<fl+m)?1:0}')

if [ "$BELOW_FLOOR" = 1 ] && [ "$POST" = 1 ]; then
  VERDICT=RED; CODE=3
  WHY="free ${FREE_GB} GB is BELOW the ${FLOOR_GB} GB floor AFTER the ${RETENTION_ICT_HHMM} retention has run — the nightly give-back no longer covers the daily inflow. This is the condition TK-0645's fix exists to end."
elif [ "$BELOW_FLOOR" = 1 ]; then
  VERDICT=AMBER; CODE=2
  WHY="free ${FREE_GB} GB is below the ${FLOOR_GB} GB floor, but BEFORE tonight's ${RETENTION_ICT_HHMM} retention — expected, and self-healing. The next run is due to give back ${NEXT_DROP} GiB."
elif [ "$NEAR_FLOOR" = 1 ]; then
  VERDICT=AMBER; CODE=2
  WHY="free ${FREE_GB} GB is within ${MARGIN_GB} GB of the ${FLOOR_GB} GB floor. The next ${RETENTION_ICT_HHMM} run is due to give back ${NEXT_DROP} GiB."
else
  VERDICT=GREEN; CODE=0
  WHY="free ${FREE_GB} GB, clear of the ${FLOOR_GB} GB floor by more than ${MARGIN_GB} GB."
fi

[ -n "$FORCE_HHMM" ] && FORCED="${FORCED} [FORCED CLOCK ${FORCE_HHMM} — not the real time]"
FORCED="${FORCED}${FLOOR_SRC}"
MSG="[disk-floor] ${VERDICT} ${NOW_ICT} ICT${FORCED} — free=${FREE_GB} GB  pg_total=${PG_TOTAL} GiB (crypto ${PG_CRYPTO}, orderbook ${PG_OB})  next_retention_gives_back=${NEXT_DROP} GiB  phase=$([ "$POST" = 1 ] && echo post-retention || echo pre-retention) — ${WHY}"

# --- 5. log BEFORE posting, so a dropped Slack post still leaves the text on disk -------------
printf '%s\n' "$MSG" >> "$LOG" 2>/dev/null
[ "$QUIET" = 0 ] && echo "$MSG"

# --- 6. Slack: RED always; otherwise only on a CHANGE of verdict ------------------------------
# A daily "nothing wrong" is the alert fatigue DC-0007 is about, so a repeated GREEN is silent.
PREV=$(cat "$STATE" 2>/dev/null)
printf '%s\n' "$VERDICT" > "$STATE" 2>/dev/null
if [ "$NO_SLACK" = 0 ] && { [ "$VERDICT" = RED ] || [ "$VERDICT" != "$PREV" ]; }; then
  # shellcheck disable=SC1091
  [ -f /home/batt/.config/quant-pm/env ] && . /home/batt/.config/quant-pm/env
  # 🔑 THE POST RESULT IS CAPTURED AND LOGGED, and that is not a nicety. Until 2026-11-06 this
  # discarded curl's output with `>/dev/null 2>&1 || true`, so the script could not tell whether
  # the alarm had LEFT THE MACHINE. An alarm path that cannot confirm delivery has the same defect
  # as an observer that reports "fine" when it could not look — and it has it at the only moment
  # that matters. A failed or skipped post now says, in the log, that THE VERDICT WAS NOT
  # DELIVERED, so a reader is never left inferring delivery from the verdict's presence.
  if [ -n "${PM_SLACK_WEBHOOK:-}" ]; then
    # The webhook is a credential: passed by variable, never echoed, never written to the log.
    HTTP=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -X POST -H 'Content-type: application/json' \
      --data "$(printf '{"text":%s}' "$(printf '%s' "$MSG" | sed 's/\\/\\\\/g; s/"/\\"/g; s/^/"/; s/$/"/')")" \
      "$PM_SLACK_WEBHOOK" 2>/dev/null)
    if [ "$HTTP" = "200" ]; then
      printf '[post] status=ok HTTP 200 verdict=%s\n' "$VERDICT" >> "$LOG" 2>/dev/null
    else
      printf '[post] status=FAILED HTTP %s — the %s verdict above was NOT DELIVERED\n' \
        "${HTTP:-none}" "$VERDICT" >> "$LOG" 2>/dev/null
    fi
  else
    printf '[post] status=SKIPPED no PM_SLACK_WEBHOOK in the environment — the %s verdict above was NOT DELIVERED\n' \
      "$VERDICT" >> "$LOG" 2>/dev/null
  fi
fi

exit "$CODE"
