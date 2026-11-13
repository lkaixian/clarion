#!/usr/bin/env bash
# speedtest_baseline.sh - internet speed + latency from the Pi out through the modem (no server of ours involved).
#   [TAG=base] [RUNS=3] [STREAMS=4] [DL_MB=25] [UL_MB=10] ./speedtest_baseline.sh [--dry-run]
# Three paths: (1) raw internet speed (Cloudflare speed endpoints), (2) ping 1.1.1.1 + 8.8.8.8,
# (3) through our tunnel: BASE_URL$PROBE_PATH latency (avg/med/p95, needs BASE_URL) and, if TUNNEL_DL_PATH is set to a
# large GET path on the site, download Mbit/s through the tunnel.
# Records INFO: <TAG>_down_mbps, <TAG>_up_mbps (mean of RUNS), <TAG>_ping_<ip>_avg_ms (min/max/loss in detail).
# Run it with nothing else running; compare a run during netem with TAG=shaped.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

TAG=${TAG:-base}; RUNS=${RUNS:-3}; STREAMS=${STREAMS:-4}; DL_MB=${DL_MB:-25}; UL_MB=${UL_MB:-10}
CF=https://speed.cloudflare.com
rdir; mark "speedtest_baseline $TAG"

# latency: 20 pings per target. Summary line: "rtt min/avg/max/mdev = a/b/c/d ms"
for ip in 1.1.1.1 8.8.8.8; do
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: ping -c 20 -i 0.2 -q $ip"; continue; fi
  out=$(ping -c 20 -i 0.2 -q "$ip" 2>&1 || true)
  echo "$out" >"$RESULTS_DIR/$TAG.ping.$ip.txt"
  stats=$(echo "$out" | awk -F'[ /]' '/min\/avg\/max/{print $(NF-4), $(NF-3), $(NF-2)}')
  loss=$(echo "$out" | grep -oE '[0-9.]+% packet loss' | head -1 || true)
  if [ -n "$stats" ]; then set -- $stats; info "${TAG}_ping_${ip}_avg_ms" "$2 (min=$1 max=$3 ${loss:-loss=?})"
  else skip "${TAG}_ping_$ip" "no reply"; fi
done

# throughput: STREAMS parallel curls, total bytes / wall seconds, mean over RUNS
mbps() { awk -v b="$1" -v s="$2" 'BEGIN{printf "%.1f", b*8/s/1e6}'; }
measure() { # dir [download URL] -> mean Mbit/s
  local dir=$1 dlurl=${2:-} sum=0 r i t0 t1 bytes up=$RESULTS_DIR/.ul.bin
  [ "$dir" = up ] && head -c $((UL_MB*1000000)) /dev/zero >"$up"
  for r in $(seq "$RUNS"); do
    rm -f "$RESULTS_DIR"/.sz.*; t0=$(date +%s.%N)
    for i in $(seq "$STREAMS"); do
      if [ "$dir" = down ]; then curl -s -m 60 -o /dev/null -w '%{size_download}
' "${dlurl:-$CF/__down?bytes=$((DL_MB*1000000))}" >"$RESULTS_DIR/.sz.$i" &
      else curl -s -m 60 -o /dev/null -w '%{size_upload}
' --data-binary @"$up" "$CF/__up" >"$RESULTS_DIR/.sz.$i" & fi
    done; wait
    t1=$(date +%s.%N); bytes=$(cat "$RESULTS_DIR"/.sz.* | awk '{s+=$1} END{print s+0}')
    sum=$(awk -v a="$sum" -v b="$(mbps "$bytes" "$(awk -v a="$t0" -v b="$t1" 'BEGIN{print b-a}')")" 'BEGIN{print a+b}')
  done
  rm -f "$RESULTS_DIR"/.sz.* "$up"; awk -v s="$sum" -v n="$RUNS" 'BEGIN{printf "%.1f", s/n}'
}
for dir in down up; do
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: $STREAMS x curl $CF ($dir) x $RUNS runs"; continue; fi
  v=$(measure "$dir"); if [ "$v" = 0.0 ]; then skip "${TAG}_${dir}" "no data (Cloudflare unreachable?)"; else info "${TAG}_${dir}_mbps" "$v ($STREAMS streams, $RUNS runs)"; fi
done

# (3) through the tunnel
if [ -z "$BASE_URL" ]; then skip "${TAG}_tunnel" "BASE_URL not set"; exit 0; fi
probe "${TAG}_tunnel" "${TUNNEL_SECS:-20}"
if [ "$DRY_RUN" != 1 ] && [ -f "$RESULTS_DIR/${TAG}_tunnel.probe.csv" ]; then
  avg=$(awk -F, 'NR>1&&$2~/^[23]/{s+=$7*1000;n++} END{printf "%.1f", n?s/n:0}' "$RESULTS_DIR/${TAG}_tunnel.probe.csv")
  info "${TAG}_tunnel_avg_ms" "$avg (client RTT via $BASE_URL$PROBE_PATH, successful requests only)"
fi
if [ -n "${TUNNEL_DL_PATH:-}" ] && [ "$DRY_RUN" != 1 ]; then
  v=$(measure down "$BASE_URL$TUNNEL_DL_PATH"); info "${TAG}_tunnel_down_mbps" "$v ($STREAMS streams, $RUNS runs, $TUNNEL_DL_PATH)"
fi
