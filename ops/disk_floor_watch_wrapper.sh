#!/usr/bin/env bash
# Thin wrapper for ops/disk_floor_watch.sh  (TK-0645).  CANONICAL SOURCE — the INSTALLED copy is
# ~/.local/bin/disk_floor_watch.sh, which the cron calls. Re-install after any change here:
#     install -m 755 ops/disk_floor_watch_wrapper.sh ~/.local/bin/disk_floor_watch.sh
#
# ⚠️ AND THE RESIDUAL, STATED RATHER THAN CLAIMED AWAY: this wrapper IS a copy and CAN drift from
# the repo, because the cron must call a path that exists on disk. The SCRIPT it runs cannot drift
# (it is read from the ref every run, and the ref is fetched first). An earlier version of this
# header claimed nothing could drift at all; that was wrong twice over — see the ticket.
#
# WHY A WRAPPER: the operator authorised installing this check, but advancing quant-infra-db's
# WORKING TREE was refused (shared resource; the repo is an editable install). So the script is not
# on disk at the repo path. This reads it out of git and execs it.
#
# 🔴 AND WHY IT FETCHES FIRST — the correction that matters, found by session:HA 2026-11-06:
# `git show origin/main:…` reads a LOCAL REMOTE-TRACKING REF. That ref is a CACHED COPY of the
# remote and moves only when something runs `git fetch` in this clone. Measured: NOTHING fetches
# quant-infra-db on a schedule, and FETCH_HEAD had last been written by hand. So the first version
# of this wrapper claimed "a stale copy cannot drift because there is no copy" — and that was
# FALSE. `origin/main` IS the copy. The drift was moved one level down, not removed, and a merged
# fix would never have reached the cron.
#
# ⚠️ Note the failure MODE, because the previous guard did not cover it: this wrapper already
# failed CLOSED on an UNREADABLE source. A STALE source reads perfectly. Fail-closed does nothing
# about a value that is wrong while looking authoritative — only fetching, and then DECLARING what
# was actually run, does.
set -uo pipefail
REPO=/home/batt/docker/quant-trading-system/quant-infra-db
SRC=ops/disk_floor_watch.sh
CACHE=/home/batt/.local/state/disk-floor-watch/disk_floor_watch.sh
NOTE=""

# 🔑 A TEST-ONLY WAY TO REACH THE FAILURE BRANCH, for the same reason this script already has
# --force-free-gb and --force-hhmm: the branch is otherwise unreachable on demand, and an untested
# branch in the thing that tells you the monitor is stale is the one that fails silently.
# Measured 2026-11-06: two attempts to force a real fetch failure were BOTH VACUOUS —
# `--upload-pack=/bin/false` is ignored over HTTPS, and `-c remote.origin.url=…` is ignored for a
# SUBMODULE (git resolved the real GitHub URL anyway). Neither mutant touched the branch, and only
# reading the output said so. Hence an explicit switch rather than a cleverer mutant.
# ⚠️ Build a NEW list rather than `set -- "${@/--force-fetch-fail/}"`. That substitution replaces
# the flag with an EMPTY STRING instead of removing it, and the empty argument then reaches the
# script's parser as an unknown option (exit 64). Caught by running it.
FORCE_FETCH_FAIL=0
_ARGS=()
for a in "$@"; do
  if [ "$a" = "--force-fetch-fail" ]; then FORCE_FETCH_FAIL=1; else _ARGS+=("$a"); fi
done
set -- ${_ARGS[@]+"${_ARGS[@]}"}

# Refresh the ref. A failure is NOT fatal — a slightly stale answer still beats no answer — but it
# is ANNOUNCED, with the ref's age, so nobody reads a stale verdict as a current one.
if [ "$FORCE_FETCH_FAIL" = 1 ] || ! timeout 25 git -C "$REPO" fetch -q --no-tags origin main 2>/dev/null; then
  # 🔴 AGE IS TIME SINCE THE LAST SUCCESSFUL FETCH, not origin/main's commit date (session:HA's
  # review, 2026-11-06). The commit date misleads in the REASSURING direction, which is the
  # dangerous one: a merge one minute ago with a week of failed fetches would have printed
  # "0d old" — the ref looking brand new precisely when it is most stale. FETCH_HEAD's mtime is
  # written by a successful fetch, so it answers the question actually being asked.
  FH="$REPO/.git/FETCH_HEAD"
  [ -f "$FH" ] || FH="$(git -C "$REPO" rev-parse --git-dir 2>/dev/null)/FETCH_HEAD"
  LASTFETCH=$(stat -c %Y "$FH" 2>/dev/null)
  if [ -n "$LASTFETCH" ]; then
    AGE_H=$(( ( $(date +%s) - LASTFETCH ) / 3600 ))
    NOTE=" [⚠️ FETCH FAILED — last SUCCESSFUL fetch was ${AGE_H}h ago; a merged fix may NOT be in this run]"
  else
    NOTE=" [⚠️ FETCH FAILED — and FETCH_HEAD is absent, so the last successful fetch is UNKNOWN; a merged fix may NOT be in this run]"
  fi
  [ "$FORCE_FETCH_FAIL" = 1 ] && NOTE="${NOTE} [FORCED — not a real fetch failure]"
fi

if ! git -C "$REPO" show "origin/main:$SRC" > "$CACHE.new" 2>/dev/null; then
  echo "[disk-floor] UNKNOWN $(TZ=Asia/Bangkok date '+%Y-%m-%d %H:%M:%S') ICT — cannot read $SRC from origin/main in $REPO. An observer fails CLOSED: this is NOT 'fine'."
  rm -f "$CACHE.new"; exit 1
fi
if [ ! -s "$CACHE.new" ]; then
  echo "[disk-floor] UNKNOWN $(TZ=Asia/Bangkok date '+%Y-%m-%d %H:%M:%S') ICT — $SRC at origin/main is EMPTY. An observer fails CLOSED: this is NOT 'fine'."
  rm -f "$CACHE.new"; exit 1
fi
mv "$CACHE.new" "$CACHE" && chmod +x "$CACHE"

# Declare WHICH revision produced the verdict, always — so "which version ran?" is answerable from
# the log alone and never has to be inferred.
SHA=$(git -C "$REPO" log -1 --format=%h origin/main 2>/dev/null)
export DFW_SOURCE_NOTE=" src=${SHA:-?}${NOTE}"
exec bash "$CACHE" "$@"
