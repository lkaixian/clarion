# CLARION backup -- shared helpers (roadmap P2.8, the tender).
# Sourced by backup.sh / restore-test.sh / pre-update-snapshot.sh.
# shellcheck shell=bash

set -euo pipefail

# --- config (env-driven; see .env.docker.example "Backup / DR") ----------
: "${BACKUP_ROOT:=/backup}"                       # working area (a volume)
: "${MARIADB_HOST:=mariadb}"
: "${MARIADB_PORT:=3306}"
: "${MARIADB_BACKUP_USER:=clarion_migrate}"       # needs RELOAD, PROCESS, LOCK TABLES, REPLICATION CLIENT
: "${MARIADB_BACKUP_PASSWORD:?set MARIADB_BACKUP_PASSWORD}"
: "${MARIADB_DATABASE:=clarion}"
: "${MINIO_ENDPOINT:=http://minio:9000}"
: "${MINIO_ACCESS_KEY:=}"
: "${MINIO_SECRET_KEY:=}"
: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY (e.g. sftp:backup@vm-backup:/srv/restic/clarion)}"
: "${RESTIC_PASSWORD:?set RESTIC_PASSWORD}"
: "${AGE_RECIPIENTS:=}"                           # age public key(s), space-separated; empty = restic-only encryption
: "${RETENTION_KEEP_DAILY:=30}"
: "${RETENTION_KEEP_WEEKLY:=12}"
: "${RETENTION_KEEP_MONTHLY:=84}"
: "${RETENTION_KEEP_YEARLY:=7}"
: "${STATUS_LOG:=$BACKUP_ROOT/status.jsonl}"

export RESTIC_REPOSITORY RESTIC_PASSWORD

# Used by the scripts that source this file (backup.sh etc.).
# shellcheck disable=SC2034
TS="$(date -u +%Y%m%dT%H%M%SZ)"
# shellcheck disable=SC2034
DAY="$(date -u +%Y-%m-%d)"

log()  { printf '%s  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die()  { log "FATAL: $*"; _status "$SCRIPT" fail "$*"; exit 1; }

# One JSON line per run (-- backup success/failure reporting).
_status() {
  local job="$1" result="$2" detail="${3:-}"
  mkdir -p "$(dirname "$STATUS_LOG")"
  printf '{"ts":"%s","job":"%s","result":"%s","detail":%s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$job" "$result" \
    "$(printf '%s' "$detail" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$detail")" \
    >> "$STATUS_LOG"
}

need() { command -v "$1" >/dev/null 2>&1 || die "missing tool: $1"; }

# Encrypt stdin -> stdout. age if AGE_RECIPIENTS is set, else passthrough
# (restic already encrypts its repo; age is the extra "backup files are
# encrypted even outside the repo" layer for the offline-disk copy).
maybe_age() {
  if [ -n "$AGE_RECIPIENTS" ]; then
    need age
    local args=() r
    for r in $AGE_RECIPIENTS; do args+=(-r "$r"); done
    age "${args[@]}"
  else
    cat
  fi
}
