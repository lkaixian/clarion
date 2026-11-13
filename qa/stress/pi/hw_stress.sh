#!/usr/bin/env bash
# hw_stress.sh - H1..H13 hardware pressure with a constant probe (spec section B).
#   hw_stress.sh [--dry-run] [--i-know-this-kills] [H1 H4 ...]
# default set : H1 H3 H4 H6 H8 H9 H12
# explicit    : H2 (30 min soak), H7 (8 h soak), H11 (run twice ~24 h apart)
# gated       : H5 (OOM), H10 (disk full), H13 (combined worst case)  -> need --i-know-this-kills
# Staging only. The probe measures RTT against BASE_URL; run on the Pi against the origin/proxy to approximate
# "server time", and use LOCUST=1 (20 users) for the spec's critical-path probe.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

# ---- thresholds (spec section B) --------------------------------------------
H_MED_MS=1000                       # probe median under any load
H1_SECS=600;  H1_P95_MS=250
H2_SECS=1800; H2_MAX_C=80;  H2_MASK=0x50005
H3_SECS=300;  H3_P95_MS=500;  H3_CPUS=8
H4_SECS=300;  H4_SWAP_PPS=100;  H4_VM_BYTES=${H4_VM_BYTES:-60%}
H5_SECS=120;  H5_VICTIM_BAD='mariadbd|mysqld|gunicorn|caddy|redis|cloudflared|minio|uvicorn|python'
H6_MEM=256m;  H6_SECS=180;  H6_RESTARTS=1;  H6_UP_SECS=120
H7_SECS=${H7_SECS:-28800}; H7_GROWTH_PCT_12H=5
H8_SECS=300;  H8_P95_MS=250;  H8_COMMIT_MS=100
H9_SECS=300;  H9_COMMIT_MS=2000
H10_FLOOR_MB=1024; H10_RECOVER_S=60; FILL_FILE=${FILL_FILE:-/var/lib/docker/fill.bin}
H11_MAX_GB_DAY=5; MMC_DEV=${MMC_DEV:-/dev/mmcblk0}
H12_SECS=120; H12_MASK=0x10001      # bits 0 / 16 = under-voltage now / has occurred
H13_SECS=600; H13_MAX_MS=10000; H13_5XX_PCT=0.1; H13_NETEM="delay 200ms 50ms loss 1%"
FIO_DIR=${FIO_DIR:-/var/lib/docker/clarion-fio}
FIO_SIZE=${FIO_SIZE:-1g}
EMERGENCY_PATH=${EMERGENCY_PATH:-$PROBE_PATH}

KILLS=0 IDS=()
for a in "$@"; do
  case $a in
    --dry-run) ;;
    --i-know-this-kills) KILLS=1 ;;
    H[0-9] | H1[0-3]) IDS+=("$a") ;;
    *) die "unknown argument: $a" ;;
  esac
done
[ "${#IDS[@]}" -gt 0 ] || IDS=(H1 H3 H4 H6 H8 H9 H12)
for id in "${IDS[@]}"; do
  case $id in H5 | H10 | H13) [ "$KILLS" = 1 ] || die "$id can kill services or fill the disk: add --i-know-this-kills (staging only)" ;; esac
done

need_root; need_tools docker curl awk
[ "$DRY_RUN" = 1 ] || [ -n "$BASE_URL" ] || die "set BASE_URL"

CLEAN_FILL=0 CLEAN_MEM=0 CLEAN_FIO=0 CLEAN_SCRATCH=0 CLEAN_NETEM=0
cleanup() {
  trap - EXIT INT TERM
  kill_jobs
  [ "$CLEAN_FILL" = 0 ] || rm -f "$FILL_FILE"
  [ "$CLEAN_FIO" = 0 ] || rm -rf "$FIO_DIR"
  [ "$CLEAN_MEM" = 0 ] || docker update --memory 0 --memory-swap -1 "$(cid backend)" >/dev/null 2>&1 || true
  [ "$CLEAN_SCRATCH" = 0 ] || db_scratch_drop >/dev/null 2>&1 || true
  [ "$CLEAN_NETEM" = 0 ] || bash "$LIB_DIR/netem.sh" "$(default_if)" off >/dev/null 2>&1 || true
  collect_stop
}
trap cleanup EXIT INT TERM

sample_temp() { while :; do echo "$(date +%s),$(pi_temp)" >>"$RESULTS_DIR/$1.temp"; sleep 5; done; }
max_temp() { sort -t, -k2 -n "$RESULTS_DIR/$1.temp" 2>/dev/null | tail -n1 | cut -d, -f2; }

# hrun ID SECS STRESSOR... : stressor + probe at the same time (HOOK=fn runs once after HOOK_DELAY s)
TH0=na SW0=0 R0=0
hrun() {
  local id=$1 secs=$2 spid tpid hpid=""; shift 2
  mark "begin $id"
  TH0=$(pi_throttled); SW0=$(swap_pages); R0=$(restart_total)
  if [ "$DRY_RUN" != 1 ]; then rdir; : >"$RESULTS_DIR/$id.temp"; sample_temp "$id" & tpid=$!; fi
  if [ -n "${HOOK:-}" ] && [ "$DRY_RUN" != 1 ]; then ( sleep "${HOOK_DELAY:-30}"; "$HOOK" >"$RESULTS_DIR/$id.hook" 2>&1 || true ) & hpid=$!; fi
  run "$@" &
  spid=$!
  probe "$id" "$secs" "${HPATH:-$PROBE_PATH}"
  wait "$spid" || info "$id" "stressor exited non-zero (normal for stress-ng under pressure)"
  [ -z "$hpid" ] || wait "$hpid" || true
  [ "$DRY_RUN" = 1 ] || { kill "$tpid" 2>/dev/null || true; }
  mark "end $id"
}
probe_ok() { # ID : median/ok-pct under load
  check "$1" median_ms "$PROBE_MED" le "$H_MED_MS"
  check "$1" ok_pct "$PROBE_OK_PCT" ge 99.9
}
hook_value() { cat "$RESULTS_DIR/$1.hook" 2>/dev/null | tail -n1 || echo 0; }
fio_prep() {
  local need=$(( 2 * 1024 )) free
  run mkdir -p "$FIO_DIR"; CLEAN_FIO=1
  [ "$DRY_RUN" = 1 ] && return 0
  free=$(df -BM --output=avail "$FIO_DIR" | tail -n1 | tr -dc 0-9 || echo 0)
  [ "$free" -gt "$need" ] || die "need >= ${need}M free on $FIO_DIR (have ${free}M)"
}

h1() {
  hrun H1 "$H1_SECS" stress-ng --cpu 4 --cpu-method matrixprod --timeout "${H1_SECS}s"
  probe_ok H1; check H1 p95_rtt_ms "$PROBE_P95" le "$H1_P95_MS"
  check_throttle H1 "$TH0"
}
h2() {
  hrun H2 "$H2_SECS" stress-ng --cpu 4 --cpu-method matrixprod --timeout "${H2_SECS}s"
  [ "$DRY_RUN" = 1 ] || check H2 max_temp_c "$(max_temp H2)" le "$H2_MAX_C"
  check_throttle H2 "$TH0" "$H2_MASK"
  info H2 "closed-case vs open-case comparison is manual: repeat with the case open"
}
h3() {
  HPATH=$EMERGENCY_PATH hrun H3 "$H3_SECS" stress-ng --cpu "$H3_CPUS" --cpu-load 100 --timeout "${H3_SECS}s"
  check H3 p95_rtt_ms "$PROBE_P95" le "$H3_P95_MS"
}
h4() {
  hrun H4 "$H4_SECS" stress-ng --vm 2 --vm-bytes "$H4_VM_BYTES" --timeout "${H4_SECS}s"
  probe_ok H4
  [ "$DRY_RUN" = 1 ] || check H4 swap_pages_per_s "$(( ($(swap_pages) - SW0) / H4_SECS ))" le "$H4_SWAP_PPS"
  check_core H4
}
h5() {
  local d0 victims bad
  d0=$(dmesg 2>/dev/null | wc -l || true)
  hrun H5 "$H5_SECS" stress-ng --vm 1 --vm-bytes 110% --vm-keep --timeout "${H5_SECS}s"
  [ "$DRY_RUN" = 1 ] && return 0
  sleep 20
  victims=$(dmesg | tail -n +$(( d0 + 1 )) | sed -n 's/.*Killed process [0-9]* (\([^)]*\)).*/\1/p' | sort -u | tr '\n' ' ')
  if [ -z "$victims" ]; then skip H5 "inconclusive: no OOM kill seen (stressor exited or swap absorbed it)"
  else
    bad=$(grep -Eo "$H5_VICTIM_BAD" <<<"$victims" || true)
    if [ -z "$bad" ]; then record PASS H5 "oom victims: $victims"; else record FAIL H5 "core process killed: $victims"; fi
  fi
  check_core H5
  if db_check; then record PASS H5 "mariadb-check clean"; else record FAIL H5 "mariadb-check reported problems"; fi
}
h6() {
  local c; c=$(cid backend)
  # Without the memory cgroup, docker discards --memory and this test would pass without testing anything.
  if [ "$DRY_RUN" != 1 ] && [ "$(awk '$1=="memory"{print $4}' /proc/cgroups 2>/dev/null)" != 1 ]; then
    skip H6 "memory cgroup disabled: add 'cgroup_enable=memory cgroup_memory=1' to /boot/cmdline.txt (or /boot/firmware/cmdline.txt) and reboot"
    return 0
  fi
  CLEAN_MEM=1
  run docker update --memory "$H6_MEM" --memory-swap "$H6_MEM" "$c"
  hrun H6 "$H6_SECS" sleep "$H6_SECS"
  run docker update --memory 0 --memory-swap -1 "$c"; CLEAN_MEM=0
  [ "$DRY_RUN" = 1 ] && return 0
  if wait_up backend "$H6_UP_SECS" >/dev/null; then record PASS H6 "backend running+healthy after the limit"; else record FAIL H6 "backend not healthy within ${H6_UP_SECS}s"; fi
  check H6 restart_delta "$(( $(restart_total) - R0 ))" le "$H6_RESTARTS"
  info H6 "no data loss: compare snapshot_counts.sh before/after if you ran writes"
}
h7() {
  local f=$RESULTS_DIR/H7.rss.csv spid
  [ "$DRY_RUN" = 1 ] && { echo "DRY: H7 soak ${H7_SECS}s, RSS sample every 60s"; return 0; }
  echo "epoch,name,mib" >"$f"
  # Sum of RSS of every process in each container, read from the host with `docker top`. Works with the memory
  # cgroup off (docker stats shows 0B then) and measures the same thing on every Pi. Shared pages are counted
  # per process, so read the trend, not the absolute number.
  ( while :; do
      for c in $(docker ps --format '{{.Names}}'); do
        docker top "$c" -eo pid,rss 2>/dev/null | awk -v t="$(date +%s)" -v n="$c" 'NR>1{s+=$2} END{printf "%s,%s,%.1f\n", t, n, s/1024}' >>"$f"
      done
      sleep 60
    done ) & spid=$!
  probe H7 "$H7_SECS"
  kill "$spid" 2>/dev/null || true
  awk -F, -v secs="$H7_SECS" -v lim="$H7_GROWTH_PCT_12H" 'NR>1{n[$2]++; v[$2,n[$2]]=$3}
    END{for(k in n){ w=(n[k]>10?10:n[k]); a=0;b=0
        for(i=1;i<=w;i++){a+=v[k,i]; b+=v[k,n[k]-i+1]}
        g=(a>0)?(b-a)/a*100*(43200/secs):0
        printf "%s %s growth_pct_per_12h=%.2f (limit %s)\n", (g<=lim?"PASS":"FAIL"), k, g, lim}}' "$f" \
    | while read -r st name rest; do record "$st" "H7:$name" "$rest"; done
}
h8() {
  fio_prep; CLEAN_SCRATCH=1; HOOK=db_commit_ms HOOK_DELAY=60
  hrun H8 "$H8_SECS" fio --name=w --rw=randwrite --bs=4k --size="$FIO_SIZE" --iodepth=16 --runtime="$H8_SECS" \
    --time_based --direct=1 --ioengine=libaio --directory="$FIO_DIR" --output="$RESULTS_DIR/H8.fio.txt"
  check H8 p95_rtt_ms "$PROBE_P95" le "$H8_P95_MS"
  [ "$DRY_RUN" = 1 ] || check H8 mariadb_commit_ms "$(hook_value H8)" le "$H8_COMMIT_MS"
  unset HOOK HOOK_DELAY
}
h9() {
  local since; since=$(date -u +%Y-%m-%dT%H:%M:%S)
  fio_prep; CLEAN_SCRATCH=1; HOOK=db_commit_ms HOOK_DELAY=60
  hrun H9 "$H9_SECS" fio --name=m --rw=randrw --rwmixread=70 --bs=4k --size="$FIO_SIZE" --iodepth=16 --runtime="$H9_SECS" \
    --time_based --direct=1 --fsync=1 --ioengine=libaio --directory="$FIO_DIR" --output="$RESULTS_DIR/H9.fio.txt"
  unset HOOK HOOK_DELAY
  [ "$DRY_RUN" = 1 ] && return 0
  check H9 mariadb_commit_ms "$(hook_value H9)" le "$H9_COMMIT_MS"
  check H9 semaphore_waits "$(docker logs --since "$since" "$(cid mariadb)" 2>&1 | grep -ci 'semaphore wait' || true)" le 0
}
h10() {
  local free fill
  free=$(df -BM --output=avail "$(dirname "$FILL_FILE")" | tail -n1 | tr -dc 0-9 || echo 0)
  fill=$(( free - H10_FLOOR_MB ))
  [ "$DRY_RUN" = 1 ] || [ "$fill" -gt 0 ] || die "less than ${H10_FLOOR_MB}M free, refusing"
  CLEAN_FILL=1; mark "begin H10 fill=${fill}M floor=${H10_FLOOR_MB}M"
  run fallocate -l "${fill:-0}M" "$FILL_FILE"
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: checks healthz, /readyz, then rm $FILL_FILE and wait ${H10_RECOVER_S}s"; return 0; fi
  sleep 15
  check H10 healthz_http "$(origin_status /healthz)" ge 200
  info H10 "readyz while full: $(origin_status /readyz); uploads 503/507 and 75/90% alerts: verify by hand/Alertmanager"
  if db_check; then record PASS H10 "mariadb-check clean while full"; else record FAIL H10 "mariadb-check problems"; fi
  rm -f "$FILL_FILE"; CLEAN_FILL=0
  local t=0 ok=0
  while (( t < H10_RECOVER_S )); do
    [ "$(origin_status /readyz)" = 200 ] && { ok=1; break; }
    sleep 2; t=$(( t + 2 ))
  done
  if [ "$ok" = 1 ]; then record PASS H10 "recovered in ${t}s with no manual repair"; else record FAIL H10 "readyz not 200 after ${H10_RECOVER_S}s"; fi
  check_core H10
}
h11() {
  local snap=$STATE_DIR/h11.snap now sect life t0 s0 dt gb
  now=$(date +%s); sect=$(awk -v d="${MMC_DEV#/dev/}" '$3==d{print $10}' /proc/diskstats)
  life=$( { mmc extcsd read "$MMC_DEV" 2>/dev/null | grep -i 'life' || smartctl -a "$MMC_DEV" 2>/dev/null | grep -i -E 'life|wear' || true; } | tr '\n' ';')
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: H11 snapshot/compare via $snap"; return 0; fi
  [ -n "$sect" ] || { skip H11 "$MMC_DEV not in /proc/diskstats (set MMC_DEV)"; return 0; }
  info H11 "life: ${life:-no mmc-utils/smartctl output}"
  if [ ! -f "$snap" ]; then
    mkdir -p "$STATE_DIR"; echo "$now $sect" >"$snap"
    info H11 "baseline saved; run again after ~24 h"; return 0
  fi
  read -r t0 s0 <"$snap"; rm -f "$snap"
  dt=$(( now - t0 ))
  gb=$(awk -v s="$(( sect - s0 ))" -v dt="$dt" 'BEGIN{printf "%.2f", s*512/1e9*86400/dt}')
  check H11 gb_written_per_day "$gb" le "$H11_MAX_GB_DAY"
  info H11 "life estimate >5 y needs the before/after Life Time Est. codes above (10% steps); compare the two runs"
}
h12() {
  hrun H12 "$H12_SECS" stress-ng --cpu 4 --cpu-method matrixprod --timeout "${H12_SECS}s"
  check_throttle H12 "$TH0" "$H12_MASK"
}
h13() {
  local nif fpid dry=(); nif=$(default_if)
  [ "$DRY_RUN" != 1 ] || dry=(--dry-run)
  mark "begin H13 (cpu + vm 60% + fio + netem '$H13_NETEM')"
  fio_prep; CLEAN_NETEM=1
  DIR=both DEADMAN=$(( H13_SECS + 120 )) bash "$LIB_DIR/netem.sh" "${dry[@]}" "$nif" "$H13_NETEM"
  run fio --name=w --rw=randwrite --bs=4k --size="$FIO_SIZE" --iodepth=16 --runtime="$H13_SECS" --time_based \
    --direct=1 --ioengine=libaio --directory="$FIO_DIR" --output="$RESULTS_DIR/H13.fio.txt" &
  fpid=$!
  hrun H13 "$H13_SECS" stress-ng --cpu 4 --cpu-method matrixprod --vm 2 --vm-bytes 60% --timeout "${H13_SECS}s"
  wait "$fpid" || true
  bash "$LIB_DIR/netem.sh" "${dry[@]}" "$nif" off; CLEAN_NETEM=0
  check H13 max_ms "$PROBE_MAX" le "$H13_MAX_MS"
  [ "$DRY_RUN" = 1 ] || check H13 pct_5xx "$(awk -v a="$PROBE_5XX" -v n="$PROBE_N" 'BEGIN{printf "%.3f", n ? 100*a/n : 0}')" le "$H13_5XX_PCT"
  check_core H13
}

collect_start
for id in "${IDS[@]}"; do
  echo "=== $id ==="
  "h${id#H}"
done
summary
