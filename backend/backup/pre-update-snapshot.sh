#!/usr/bin/env bash
# CLARION -- pre-update full-system snapshot (roadmap P2.8, tender
# "full system image snapshot before major updates/changes").
#
# A HARD GATE in the deploy pipeline: run this and confirm it exits 0
# BEFORE any `alembic upgrade`, image bump, or config change. It records
# everything needed to roll back:
#   - a fresh full DB backup (mariadb-backup + mydumper), pushed to restic
#   - the current Alembic head (the `downgrade` target)
#   - the digests of every currently-running container image
#   - a note of the hypervisor snapshot id (operator supplies it)
#
#   pre-update-snapshot.sh "upgrade to c3e8f1a4d5b7 / image v1.4"
SCRIPT="pre-update-snapshot"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=backend/backup/lib.sh
. "$DIR/lib.sh"

REASON="${1:?describe the change, e.g. \"alembic upgrade + web image v1.4\"}"
OUT="$BACKUP_ROOT/pre-update/$TS"
mkdir -p "$OUT"

log "1/4 fresh full DB backup"
"$DIR/backup.sh" full
"$DIR/backup.sh" logical

log "2/4 record the rollback target (current Alembic head)"
HEAD="$(mariadb --host="$MARIADB_HOST" --port="$MARIADB_PORT" \
  --user="$MARIADB_BACKUP_USER" --password="$MARIADB_BACKUP_PASSWORD" \
  -N -B -e "SELECT version_num FROM alembic_version" "$MARIADB_DATABASE")"
echo "$HEAD" > "$OUT/alembic_downgrade_target.txt"
log "    downgrade target: $HEAD"

log "3/4 record running image digests"
if command -v docker >/dev/null 2>&1; then
  docker compose ps --format '{{.Service}} {{.Image}}' 2>/dev/null > "$OUT/images.txt" || true
  while read -r _svc img; do
    [ -n "$img" ] && docker image inspect --format '{{.RepoDigests}}' "$img" 2>/dev/null \
      | tr -d '[]' >> "$OUT/image_digests.txt" || true
  done < "$OUT/images.txt"
fi

log "4/4 hypervisor snapshot"
if [ -n "${HYPERVISOR_SNAPSHOT_ID:-}" ]; then
  echo "$HYPERVISOR_SNAPSHOT_ID" > "$OUT/hypervisor_snapshot_id.txt"
else
  echo "!! HYPERVISOR_SNAPSHOT_ID not set -- take a VM snapshot NOW and record its id in $OUT/" >&2
  echo "PENDING -- operator must record" > "$OUT/hypervisor_snapshot_id.txt"
fi

printf '{"ts":"%s","reason":%s,"alembic_downgrade_target":"%s"}\n' \
  "$(date -u +%FT%TZ)" \
  "$(printf '%s' "$REASON" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' 2>/dev/null || printf '"%s"' "$REASON")" \
  "$HEAD" > "$OUT/manifest.json"

need restic
restic backup --tag pre-update --tag "$TS" "$OUT"
_status "$SCRIPT" ok "snapshot $OUT (downgrade target $HEAD)"
log "PRE-UPDATE SNAPSHOT COMPLETE -- rollback target $HEAD, artifacts in $OUT"
