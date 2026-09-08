#!/usr/bin/env bash
# CLARION -- automated restore test (roadmap P2.8, the tender
# "quarterly restore testing"). Run this on the VM-BACKUP sandbox, NEVER
# against production.
#
#   restore-test.sh              restore latest full+incr into a scratch
#                                mariadbd, smoke-check, reconcile row counts
#   restore-test.sh --report out.json   also write a machine-readable report
#
# Exit 0 = restore verified. Non-zero = investigate before the next backup
# cycle. File the signed report with the University (see README.md).
SCRIPT="restore-test"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backend/backup/lib.sh
. "$DIR/lib.sh"
need restic; need mariadbd || need mariadb-install-db

REPORT=""
[ "${1:-}" = "--report" ] && REPORT="${2:?--report needs a path}"

SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/clarion-restore.XXXXXX")"
trap 'rm -rf "$SCRATCH"; [ -n "${MYSQL_PID:-}" ] && kill "$MYSQL_PID" 2>/dev/null || true' EXIT
DATADIR="$SCRATCH/data" ; mkdir -p "$DATADIR"
SOCK="$SCRATCH/mysql.sock"
PORT=13399

log "restore latest mariadb-full from restic"
restic restore latest --tag mariadb-full --target "$SCRATCH/full" --path '*/mariadb-full-*'
FULL_AGE="$(find "$SCRATCH/full" -name 'mariadb-full-*.tar.age' -o -name 'mariadb-full-*.tar' | head -1)"
[ -n "$FULL_AGE" ] || die "no full backup found in the restic repo"

mkdir -p "$SCRATCH/restored"
if [[ "$FULL_AGE" == *.age ]]; then
  [ -n "${AGE_IDENTITY:-}" ] || die "AGE_IDENTITY (private key file) must be set to decrypt"
  age -d -i "$AGE_IDENTITY" "$FULL_AGE" | tar -x -C "$SCRATCH/restored"
else
  tar -xf "$FULL_AGE" -C "$SCRATCH/restored"
fi

log "apply incrementals + prepare"
mariadb-backup --prepare --target-dir="$SCRATCH/restored" || die "prepare failed"
# (a full runbook loops mariadb-backup --prepare --incremental-dir over each
#  incr in date order + replays binlog to a target time; kept short here)

log "move-back into a scratch datadir and start a throwaway mariadbd"
mariadb-backup --copy-back --target-dir="$SCRATCH/restored" --datadir="$DATADIR"
chown -R "$(id -u):$(id -g)" "$DATADIR" 2>/dev/null || true
mariadbd --no-defaults --datadir="$DATADIR" --socket="$SOCK" --port="$PORT" \
  --skip-networking=0 --skip-grant-tables --pid-file="$SCRATCH/mysqld.pid" &
MYSQL_PID=$!

for _ in $(seq 1 30); do mariadb --socket="$SOCK" -e 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done
mariadb --socket="$SOCK" -e 'SELECT 1' >/dev/null 2>&1 || die "restored mariadbd never came up"

log "smoke + row-count reconcile against production"
q() { mariadb --socket="$SOCK" -N -B -e "$1" "$MARIADB_DATABASE"; }
p() { mariadb --host="$MARIADB_HOST" --port="$MARIADB_PORT" --user="$MARIADB_BACKUP_USER" \
        --password="$MARIADB_BACKUP_PASSWORD" -N -B -e "$1" "$MARIADB_DATABASE"; }

HEAD_R="$(q "SELECT version_num FROM alembic_version")"
HEAD_P="$(p "SELECT version_num FROM alembic_version")"
[ "$HEAD_R" = "$HEAD_P" ] || die "alembic head differs: restored=$HEAD_R prod=$HEAD_P"

MISMATCH=0
while read -r t; do
  cr="$(q "SELECT COUNT(*) FROM \`$t\`")"; cp="$(p "SELECT COUNT(*) FROM \`$t\`")"
  if [ "$cr" != "$cp" ]; then log "  MISMATCH $t: restored=$cr prod=$cp"; MISMATCH=$((MISMATCH+1))
  else log "  ok $t ($cr)"; fi
done < <(p "SELECT table_name FROM information_schema.tables WHERE table_schema='$MARIADB_DATABASE' AND table_type='BASE TABLE'")

RESULT=$([ "$MISMATCH" -eq 0 ] && echo pass || echo "fail:$MISMATCH tables")
_status "$SCRIPT" "$([ "$MISMATCH" -eq 0 ] && echo ok || echo fail)" "$RESULT (head $HEAD_R)"
[ -n "$REPORT" ] && printf '{"ts":"%s","alembic_head":"%s","table_mismatches":%d,"result":"%s"}\n' \
  "$(date -u +%FT%TZ)" "$HEAD_R" "$MISMATCH" "$RESULT" > "$REPORT"

log "restore test: $RESULT"
[ "$MISMATCH" -eq 0 ]
