#!/usr/bin/env bash
# snapshot_counts.sh [LABEL] [--checksum]  - save row counts (and optionally CHECKSUM TABLE + MinIO object names)
# to $STATE_DIR/counts.LABEL ("name value" per line). Compare later with verify_after_boot.sh or diff.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

LABEL=pre SUM=0
for a in "$@"; do
  case $a in --dry-run) ;; --checksum) SUM=1 ;; -*) die "unknown flag $a" ;; *) LABEL=$a ;; esac
done
DB=${MARIADB_DATABASE:-clarion}
OUT=$STATE_DIR/counts.$LABEL
need_tools docker
[ "$DRY_RUN" = 1 ] && { echo "DRY: snapshot $DB -> $OUT"; exit 0; }
mkdir -p "$STATE_DIR"

tables=$(dbx -N -e "SELECT table_name FROM information_schema.tables WHERE table_schema='$DB' AND table_type='BASE TABLE' ORDER BY 1")
{
  for t in $tables; do echo "SELECT '$t', COUNT(*) FROM \`$DB\`.\`$t\`;"; done | dbx -N
  if [ "$SUM" = 1 ]; then
    for t in $tables; do echo "CHECKSUM TABLE \`$DB\`.\`$t\`;"; done | dbx -N | sed 's/^/cksum./'
    echo "minio_objects $(docker exec "$(cid minio)" mc ls --recursive local 2>/dev/null | wc -l)"
    echo "minio_names_sha $(docker exec "$(cid minio)" mc ls --recursive local 2>/dev/null | awk '{print $NF}' | sort | sha256sum | cut -d' ' -f1)"
  fi
} >"$OUT"
echo "saved $(wc -l <"$OUT") lines -> $OUT"
