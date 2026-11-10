#!/usr/bin/env bash
# collect.sh - sample the Pi every INTERVAL seconds into CSV until SIGTERM/SIGINT.
#   collect.sh [outdir]      (default: $RESULTS_DIR)
# Files: collect.csv (host), docker_stats.csv (per container), iostat.log (if sysstat present).
# vcgencmd columns read "na" when absent (non-Pi dev box).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

INTERVAL=${INTERVAL:-5}
DISK=${DISK:-mmcblk0}
OUT=${1:-$RESULTS_DIR}
[ "$DRY_RUN" = 1 ] && { echo "DRY: collect every ${INTERVAL}s into $OUT"; exit 0; }
mkdir -p "$OUT"

trap 'kill_jobs; exit 0' TERM INT

CSV=$OUT/collect.csv
DCSV=$OUT/docker_stats.csv
[ -f "$CSV" ] || echo "epoch,temp_c,throttled,arm_hz,mem_used_mb,mem_avail_mb,swap_used_mb,load1,pswp_pages,rd_sectors,wr_sectors,iowait_pct" >"$CSV"
[ -f "$DCSV" ] || echo "epoch,name,cpu,mem_usage,mem_pct,net_io,block_io" >"$DCSV"
command -v iostat >/dev/null 2>&1 && { iostat -dxt "$INTERVAL" >"$OUT/iostat.log" 2>&1 & }

cpu_line() { awk '/^cpu /{t=0; for(i=2;i<=NF;i++) t+=$i; print $6, t}' /proc/stat; }
read -r pw pt <<<"$(cpu_line)"

while :; do
  ts=$(date +%s)
  read -r cw ct <<<"$(cpu_line)"
  iow=$(awk -v a="$(( cw - pw ))" -v b="$(( ct - pt ))" 'BEGIN{printf "%.1f", b ? 100*a/b : 0}')
  pw=$cw pt=$ct
  mem=$(free -m | awk '/^Mem:/{u=$3;a=$7} /^Swap:/{s=$3} END{print u","a","s}')
  dsk=$(awk -v d="$DISK" '$3==d{print $6","$10}' /proc/diskstats)
  echo "$ts,$(pi_temp),$(pi_throttled),$(pi_clock),$mem,$(cut -d' ' -f1 /proc/loadavg),$(swap_pages),${dsk:-na,na},$iow" >>"$CSV"
  if command -v docker >/dev/null 2>&1; then
    docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}}' 2>/dev/null \
      | sed "s/^/$ts,/" >>"$DCSV" || true
  fi
  sleep "$INTERVAL" &
  wait $! || true
done
