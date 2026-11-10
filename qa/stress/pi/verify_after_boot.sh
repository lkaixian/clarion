#!/usr/bin/env bash
# verify_after_boot.sh [--label pre] [--continue] [--dry-run]
# Run right after a reboot / power cycle (D4, D5, D9). Checks: services back, mariadb-check clean,
# row counts >= the snapshot_counts.sh snapshot, every acknowledged D5 write present.
# --continue : after a D5 cycle, start the next one until D5_CYCLES (needs POWER_CYCLE_CMD).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

D4_SERVE_S=180          # full stack serving within this many seconds of boot
D9_REBOOT_S=60          # watchdog: back within this long of the freeze
WAIT_S=300
D5_CYCLES=${D5_CYCLES:-20}
ACK_FILE=${ACK_FILE:-$STATE_DIR/d5.acked}
LABEL=pre CONT=0
while (( $# )); do
  case $1 in --label) LABEL=${2:?}; shift 2 ;; --continue) CONT=1; shift ;; --dry-run) shift ;; *) die "unknown arg $1" ;; esac
done
need_tools docker
if [ "$DRY_RUN" = 1 ]; then echo "DRY: would wait for services, mariadb-check, compare counts vs counts.$LABEL, check $ACK_FILE"; exit 0; fi
mkdir -p "$STATE_DIR"

up=$(cut -d. -f1 /proc/uptime)
[ -f "$STATE_DIR/d5.cycle" ] && cyc=$(cat "$STATE_DIR/d5.cycle") || cyc=0
id=BOOT; [ "$cyc" -gt 0 ] && id="D5-c$cyc"
info "$id" "uptime_at_start=${up}s"

for s in $CORE_SERVICES; do
  if t=$(wait_up "$s" "$WAIT_S"); then record PASS "$id" "$s up (waited ${t}s, uptime $(( up + t ))s)"; else record FAIL "$id" "$s not up after ${WAIT_S}s"; fi
done
at=$(cut -d. -f1 /proc/uptime)
if [ "$up" -le "$D4_SERVE_S" ]; then check "$id" serving_uptime_s "$at" le "$D4_SERVE_S"
else info "$id" "started ${up}s after boot: boot-to-serving time not measurable, run this sooner (cron @reboot)"; fi

check "$id" backend_healthz "$(origin_status /healthz)" ge 200
if db_check; then record PASS "$id" "mariadb-check clean"; else record FAIL "$id" "mariadb-check problems"; fi

# row counts must not go DOWN versus the snapshot (acknowledged writes survive)
if [ -f "$STATE_DIR/counts.$LABEL" ]; then
  bash "$LIB_DIR/snapshot_counts.sh" post >/dev/null
  lost=$(awk 'NR==FNR{a[$1]=$2; next} ($1 in a) && !/^cksum|^minio/ && $2<a[$1]{print $1": "a[$1]" -> "$2}' \
    "$STATE_DIR/counts.$LABEL" "$STATE_DIR/counts.post")
  if [ -z "$lost" ]; then record PASS "$id" "row counts >= counts.$LABEL"; else record FAIL "$id" "rows lost: $lost"; fi
else
  skip "$id" "no $STATE_DIR/counts.$LABEL (run snapshot_counts.sh before the test)"
fi

# D5 writer: every id it saw acknowledged must exist
if [ -s "$ACK_FILE" ]; then
  missing=$(comm -23 <(sort "$ACK_FILE") <(dbx -N -e 'SELECT id FROM stress_scratch.ack' | sort) | wc -l)
  if [ "$missing" -eq 0 ]; then record PASS "$id" "all $(wc -l <"$ACK_FILE") acknowledged writes present"
  else record FAIL "$id" "$missing acknowledged writes missing after power loss"; fi
fi

# D9: time since the freeze (clock quality on a Pi without RTC is only approximate)
if [ -f "$STATE_DIR/d9.ts" ]; then
  d=$(( $(date +%s) - $(cut -d. -f1 /proc/uptime) - $(cat "$STATE_DIR/d9.ts") ))   # boot time minus freeze time
  check D9 seconds_freeze_to_boot "$d" le "$D9_REBOOT_S"; rm -f "$STATE_DIR/d9.ts"
fi

if [ "$CONT" = 1 ] && [ "$cyc" -gt 0 ] && [ "$cyc" -lt "$D5_CYCLES" ]; then
  echo "next D5 cycle in 60 s (Ctrl-C to stop)"; sleep 60
  summary || true
  exec bash "$LIB_DIR/durability.sh" D5 --destructive
fi
summary
