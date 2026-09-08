#!/usr/bin/env bash
# CLARION -- scheduled backup (roadmap P2.8, the tender).
#
#   backup.sh full          weekly physical full  (mariadb-backup)
#   backup.sh incremental   daily physical incremental
#   backup.sh logical       daily mydumper logical dump (granular / cross-version restore)
#   backup.sh binlog        every 15 min -- copy new binary logs (PITR, RPO <= 1h)
#   backup.sh objectstore   daily -- mirror the MinIO buckets
#   backup.sh prune         weekly -- apply the restic retention policy + `restic check`
#   backup.sh daily         = incremental + logical + objectstore   (one cron entry)
#
# Everything is encrypted: mariadb-backup / mydumper output is streamed
# through `age` (if AGE_RECIPIENTS set) and lands in a `restic` repo (itself
# encrypted, content-addressed, dedup'd). See backend/backup/README.md for
# the schedule, the restore procedure, and the DR runbook.
SCRIPT="backup:${1:-?}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backend/backup/lib.sh
. "$DIR/lib.sh"

FULL_DIR="$BACKUP_ROOT/mariadb/full"
INCR_DIR="$BACKUP_ROOT/mariadb/incr/$DAY"
BINLOG_DIR="$BACKUP_ROOT/mariadb/binlog"

mysql_opts=( --host="$MARIADB_HOST" --port="$MARIADB_PORT"
             --user="$MARIADB_BACKUP_USER" --password="$MARIADB_BACKUP_PASSWORD" )

do_full() {
  need mariadb-backup; need restic
  rm -rf "$FULL_DIR" && mkdir -p "$FULL_DIR"
  log "mariadb-backup --backup (full)"
  mariadb-backup --backup "${mysql_opts[@]}" --target-dir="$FULL_DIR"
  mariadb-backup --prepare --target-dir="$FULL_DIR"
  ( cd "$FULL_DIR" && tar -c . | maybe_age > "$BACKUP_ROOT/mariadb-full-$TS.tar.age" )
  restic backup --tag mariadb-full --tag "$DAY" "$BACKUP_ROOT/mariadb-full-$TS.tar.age"
  rm -f "$BACKUP_ROOT/mariadb-full-$TS.tar.age"
  _status "$SCRIPT" ok "full at $FULL_DIR"
}

do_incremental() {
  need mariadb-backup; need restic
  [ -f "$FULL_DIR/xtrabackup_checkpoints" ] || { log "no full base yet -- running full"; do_full; return; }
  mkdir -p "$INCR_DIR"
  local n; n="$(printf '%02d' "$(( $(find "$INCR_DIR" -maxdepth 1 -type d | wc -l) ))")"
  log "mariadb-backup --backup --incremental-basedir=$FULL_DIR -> $INCR_DIR/$n"
  mariadb-backup --backup "${mysql_opts[@]}" \
    --incremental-basedir="$FULL_DIR" --target-dir="$INCR_DIR/$n"
  ( cd "$INCR_DIR/$n" && tar -c . | maybe_age > "$BACKUP_ROOT/mariadb-incr-$TS.tar.age" )
  restic backup --tag mariadb-incr --tag "$DAY" "$BACKUP_ROOT/mariadb-incr-$TS.tar.age"
  rm -f "$BACKUP_ROOT/mariadb-incr-$TS.tar.age"
  _status "$SCRIPT" ok "incr $INCR_DIR/$n"
}

do_logical() {
  need mydumper; need restic
  local out="$BACKUP_ROOT/mydumper/$DAY"
  rm -rf "$out" && mkdir -p "$out"
  log "mydumper -> $out"
  mydumper --host="$MARIADB_HOST" --port="$MARIADB_PORT" \
    --user="$MARIADB_BACKUP_USER" --password="$MARIADB_BACKUP_PASSWORD" \
    --database="$MARIADB_DATABASE" --compress --rows=500000 --outputdir="$out" \
    --triggers --events --routines
  ( cd "$out" && tar -c . | maybe_age > "$BACKUP_ROOT/mydumper-$TS.tar.age" )
  restic backup --tag mydumper --tag "$DAY" "$BACKUP_ROOT/mydumper-$TS.tar.age"
  rm -f "$BACKUP_ROOT/mydumper-$TS.tar.age"
  _status "$SCRIPT" ok "logical $out"
}

do_binlog() {
  need restic
  mkdir -p "$BINLOG_DIR"
  # The binlog volume is mounted read-only at $BACKUP_ROOT/binlog-src. Copy
  # only logs newer than the last run; FLUSH first so the current one closes.
  mariadb "${mysql_opts[@]}" -e "FLUSH BINARY LOGS" || log "FLUSH BINARY LOGS failed (non-fatal)"
  rsync -a --ignore-existing "$BACKUP_ROOT/binlog-src/"clarion-bin.* "$BINLOG_DIR/" 2>/dev/null || \
    cp -n "$BACKUP_ROOT/binlog-src/"clarion-bin.* "$BINLOG_DIR/" 2>/dev/null || true
  restic backup --tag binlog "$BINLOG_DIR"
  _status "$SCRIPT" ok "binlog synced"
}

do_objectstore() {
  need mc; need restic
  mc alias set clarion-minio "$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
  local out="$BACKUP_ROOT/minio"
  mkdir -p "$out"
  # clarion-derived is regenerable -- excluded (matches On-Prem Architecture).
  for b in clarion-documents clarion-signatures clarion-medicine clarion-dicom clarion-reports-archive clarion-scratch; do
    mc mirror --overwrite --remove "clarion-minio/$b" "$out/$b" || log "mirror $b failed (non-fatal)"
  done
  restic backup --tag objectstore "$out"
  _status "$SCRIPT" ok "objectstore mirrored"
}

do_prune() {
  need restic
  restic forget --prune \
    --keep-daily "$RETENTION_KEEP_DAILY" --keep-weekly "$RETENTION_KEEP_WEEKLY" \
    --keep-monthly "$RETENTION_KEEP_MONTHLY" --keep-yearly "$RETENTION_KEEP_YEARLY"
  restic check --read-data-subset=5%
  _status "$SCRIPT" ok "pruned + checked"
}

case "${1:-}" in
  full)         do_full ;;
  incremental)  do_incremental ;;
  logical)      do_logical ;;
  binlog)       do_binlog ;;
  objectstore)  do_objectstore ;;
  prune)        do_prune ;;
  daily)        do_incremental; do_logical; do_objectstore ;;
  weekly)       do_full; do_prune ;;
  *) echo "usage: $0 {full|incremental|logical|binlog|objectstore|prune|daily|weekly}" >&2; exit 2 ;;
esac
log "done: ${1}"
