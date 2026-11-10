#!/usr/bin/env bash
# durability.sh - D1-D4, D5 (power-loss helper), D6, D7, D8, D9, D10, D11, D12 (spec section D).
#   durability.sh [--dry-run] [--destructive] [--panic] [--gen-logs] [D1 D2 ...]
# default (no flag needed): D9 (config check only), D10 (config check only)
# --destructive : D1 D2 D3 D4 D5 D6 D8 D12 (D8 restores a backup into a scratch server; kill containers, restart docker, reboot, skew the clock, down/up)
# --panic       : with D9 + --destructive, really panic the kernel to prove the watchdog
# --gen-logs    : with D10, push ~1 GB through a throwaway container's log driver
# D7 overwrites a scratch object in the non-WORM clarion-derived bucket (no flag needed).
# D11 soak: --hours N (default 168), Ctrl-C ends early and still evaluates.
# D8 needs restic + RESTIC_REPOSITORY (backend/backup/README.md); D8_RTO_S / D8_RPO_S override the targets.
# D5 needs POWER_CYCLE_CMD (your smart-plug / relay command). It is run verbatim and never guessed.
# After every reboot run: verify_after_boot.sh [--continue]
set -euo pipefail
. "$(dirname "$0")/lib.sh"

# ---- thresholds (spec section D) --------------------------------------------
D1_SERVICES=${D1_SERVICES:-"web redis mpi minio backend proxy mariadb cloudflared"}
D1_UP_S=30
D2_UP_S=30
D3_UP_S=120;  D3_TUNNEL_S=60
D4_SERVE_S=180
D5_WARM_S=20; D5_CYCLES=${D5_CYCLES:-20}
D6_UP_S=300;  D6_IGNORE=${D6_IGNORE:-}      # regex of snapshot keys allowed to differ (busy tables)
D10_MAX_SIZE_MB=10; D10_MAX_FILE=3; D10_JOURNAL_MB=200
D7_BUCKET=clarion-derived
D8_RTO_S=${D8_RTO_S:-14400}; D8_RPO_S=${D8_RPO_S:-3600}
D11_MIN_AVAIL=${D11_MIN_AVAIL:-99.5}; D11_GAP_S=${D11_GAP_S:-60}; D11_EVERY_S=${D11_EVERY_S:-30}
D12_SKEW_S=600; PROTECTED_PATH=${PROTECTED_PATH:-/api/patients}
ACK_FILE=${ACK_FILE:-$STATE_DIR/d5.acked}
POWER_CYCLE_CMD=${POWER_CYCLE_CMD:-}

DESTRUCTIVE=0 PANIC=0 GENLOGS=0 HOURS=${SOAK_HOURS:-168} IDS=()
for a in "$@"; do
  case $a in
    --dry-run) ;;
    --destructive) DESTRUCTIVE=1 ;;
    --panic) PANIC=1 ;;
    --gen-logs) GENLOGS=1 ;;
    --hours=*) HOURS=${a#--hours=} ;;
    D[0-9] | D1[0-2]) IDS+=("$a") ;;
    *) die "unknown argument: $a" ;;
  esac
done
[ "${#IDS[@]}" -gt 0 ] || IDS=(D9 D10)
for id in "${IDS[@]}"; do
  case $id in D1 | D2 | D3 | D4 | D5 | D6 | D8 | D12)
    [ "$DESTRUCTIVE" = 1 ] || die "$id is destructive: add --destructive (staging / maintenance window only)" ;;
  esac
done

need_root; need_tools docker curl
COMPOSE=(docker compose -f "$COMPOSE_FILE" --project-directory "$REPO" --env-file "$REPO/.env.docker")

SKEWED=0 T_ORIG=0 T_SECS0=0
cleanup() {
  trap - EXIT INT TERM
  kill_jobs
  if [ "$SKEWED" = 1 ]; then
    date -s "@$(( T_ORIG + SECONDS - T_SECS0 ))" >/dev/null 2>&1 || true
    systemctl restart systemd-timesyncd chrony 2>/dev/null || true
  fi
  docker rm -f clarion-logtest >/dev/null 2>&1 || true
  collect_stop
}
trap cleanup EXIT INT TERM

# d1_one SVC : SIGKILL it, time how long until running + healthy again
d1_one() {
  local s=$1 c rc0 n=0 t0 el
  c=$(cid "$s"); [ -n "$c" ] || { skip D1 "$s: no container"; return 0; }
  rc0=$(restart_count "$s"); t0=$SECONDS
  run docker kill -s KILL "$c"
  [ "$DRY_RUN" = 1 ] && return 0
  while [ "$(restart_count "$s")" = "$rc0" ] && (( n < 10 )); do sleep 1; n=$(( n + 1 )); done   # restart policy kicked in
  if wait_up "$s" "$D1_UP_S" >/dev/null; then el=$(( SECONDS - t0 )); check "D1:$s" recovery_s "$el" le "$D1_UP_S"
  else record FAIL "D1:$s" "not healthy within ${D1_UP_S}s of the kill (needs manual action?)"; fi
  if [ "$s" = mariadb ]; then
    if db_check; then record PASS D1:mariadb "mariadb-check clean after SIGKILL"; else record FAIL D1:mariadb "mariadb-check problems"; fi
  fi
}
d1() { local s; for s in $D1_SERVICES; do d1_one "$s"; done; }

WORKER_PY='import os,sys,signal
ch=open("/proc/1/task/1/children").read().split()
if sys.argv[1]=="count": print(len(ch))
else: os.kill(int(ch[0]),signal.SIGKILL)'
d2() {
  local c n0 n1 rc0 s=0 st
  c=$(cid backend); rc0=$(restart_count backend)
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: docker exec backend python -c <kill one gunicorn worker>"; return 0; fi
  n0=$(docker exec "$c" python -c "$WORKER_PY" count)
  docker exec "$c" python -c "$WORKER_PY" kill
  while (( s < D2_UP_S )); do
    n1=$(docker exec "$c" python -c "$WORKER_PY" count 2>/dev/null || echo 0)
    [ "$n1" -ge "$n0" ] && break
    sleep 1; s=$(( s + 1 ))
  done
  st=$(origin_status /healthz)
  if [ "${n1:-0}" -ge "$n0" ]; then record PASS D2 "worker respawned (workers $n0 -> $n1 in ${s}s)"; else record FAIL D2 "workers $n0 -> ${n1:-0} after ${D2_UP_S}s"; fi
  check D2 healthz_http "$st" ge 200
  check D2 container_restarts "$(( $(restart_count backend) - rc0 ))" le 0
}

d3() {
  local s t bad=0
  mark "begin D3"
  run systemctl restart docker
  [ "$DRY_RUN" = 1 ] && return 0
  for s in $CORE_SERVICES; do
    if t=$(wait_up "$s" "$D3_UP_S"); then record PASS D3 "$s back in ${t}s"; else record FAIL D3 "$s not back in ${D3_UP_S}s"; bad=1; fi
  done
  if [ -n "$BASE_URL" ]; then
    if t=$(wait_ok "$D3_TUNNEL_S"); then check D3 tunnel_reconnect_ms "$t" le $(( D3_TUNNEL_S * 1000 )); else record FAIL D3 "public URL not back in ${D3_TUNNEL_S}s"; fi
  else skip D3 "BASE_URL unset: tunnel reconnect not measured"; fi
  info D3 "docker live-restore: $(docker info -f '{{.LiveRestoreEnabled}}' 2>/dev/null || echo unknown)"
  return 0
}

d4() {
  mkdir -p "$STATE_DIR"
  run bash "$LIB_DIR/snapshot_counts.sh" pre
  [ "$DRY_RUN" = 1 ] || date +%s >"$STATE_DIR/d4.ts"
  info D4 "rebooting; after boot run: sudo $LIB_DIR/verify_after_boot.sh (measures serving <= ${D4_SERVE_S}s, DB check, counts)"
  run systemctl reboot
}

d5() {
  [ -n "$POWER_CYCLE_CMD" ] || die "D5 needs POWER_CYCLE_CMD (e.g. a smart-plug off/on command); never guessed"
  local cyc
  mkdir -p "$STATE_DIR"
  cyc=$(( $(cat "$STATE_DIR/d5.cycle" 2>/dev/null || echo 0) + 1 ))
  [ "$cyc" -le "$D5_CYCLES" ] || { info D5 "all $D5_CYCLES cycles done"; rm -f "$STATE_DIR/d5.cycle"; return 0; }
  echo "$cyc" >"$STATE_DIR/d5.cycle"
  info D5 "cycle $cyc/$D5_CYCLES: writer (own INSERTs, ack file $ACK_FILE) for ${D5_WARM_S}s then: $POWER_CYCLE_CMD"
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: create stress_scratch.ack, start writer, then run: $POWER_CYCLE_CMD"; return 0; fi
  dbx -e 'CREATE DATABASE IF NOT EXISTS stress_scratch; CREATE TABLE IF NOT EXISTS stress_scratch.ack (id BIGINT PRIMARY KEY) ENGINE=InnoDB'
  bash "$LIB_DIR/snapshot_counts.sh" pre >/dev/null
  # ack = the row was committed (mariadb returned success) BEFORE the id is written here
  ( i=0; while :; do i=$(( i + 1 )); id=$(( cyc * 1000000 + i ))
      dbx -e "INSERT INTO stress_scratch.ack VALUES ($id)" && echo "$id" >>"$ACK_FILE" || true
    done ) &
  sleep "$D5_WARM_S"
  echo "CUTTING POWER NOW"
  bash -c "$POWER_CYCLE_CMD"
  sleep 120   # the Pi should be dead; if not, the cut failed
  record FAIL D5 "still running 120 s after POWER_CYCLE_CMD: the power cut did not happen"
}

d6() {
  local s t d
  mark "begin D6"
  run bash "$LIB_DIR/snapshot_counts.sh" d6a --checksum
  run "${COMPOSE[@]}" down            # never -v: volumes must survive
  run "${COMPOSE[@]}" up -d
  [ "$DRY_RUN" = 1 ] && return 0
  for s in $CORE_SERVICES; do
    wait_up "$s" "$D6_UP_S" >/dev/null || record FAIL D6 "$s not up within ${D6_UP_S}s"
  done
  bash "$LIB_DIR/snapshot_counts.sh" d6b --checksum >/dev/null
  d=$(diff <(sed 's/\t/ /' "$STATE_DIR/counts.d6a") <(sed 's/\t/ /' "$STATE_DIR/counts.d6b") || true)
  [ -z "$D6_IGNORE" ] || d=$(grep -Ev "$D6_IGNORE" <<<"$d" || true)
  d=$(grep -E '^[<>]' <<<"$d" || true); t=$(wc -l <<<"$d")
  if [ -z "$d" ]; then record PASS D6 "counts, checksums and object names identical across down/up"
  else record FAIL D6 "differences ($t lines), see $RESULTS_DIR/D6.diff"; echo "$d" >"$RESULTS_DIR/D6.diff"; fi
}

# D7: corrupt a stored object behind the app's back; the sha256 check must refuse to serve it.
d7() {
  local out
  mark "begin D7"
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: docker exec backend python (put, overwrite with different bytes, get_checked must raise)"; return 0; fi
  out=$(docker exec -i "$(cid backend)" python - "$D7_BUCKET" <<'PY' 2>&1 || true
import hashlib, sys
from app import storage
s = storage.get_object_store(); b = sys.argv[1]; k = "stress/d7-corruption-probe.bin"
good = b"clarion-d7-original" * 50
sha = hashlib.sha256(good).hexdigest()
s.put(b, k, good, mime="application/octet-stream")
r = {"clean": s.get_checked(b, k, sha) == good}
s.put(b, k, good[:-7] + b"CORRUPT", mime="application/octet-stream")          # same size
try: s.get_checked(b, k, sha); r["flipped"] = "SERVED"
except storage.ObjectIntegrityError: r["flipped"] = "refused"
s.put(b, k, good[: len(good) // 2], mime="application/octet-stream")          # truncated
try: s.get_checked(b, k, sha); r["truncated"] = "SERVED"
except storage.ObjectIntegrityError: r["truncated"] = "refused"
s.delete(b, k)
print("D7RESULT", r["clean"], r["flipped"], r["truncated"])
PY
)
  case $out in
    *"D7RESULT True refused refused"*) record PASS D7 "clean read ok; flipped and truncated objects refused by the sha256 check" ;;
    *D7RESULT*) record FAIL D7 "$(grep -o 'D7RESULT.*' <<<"$out") (a corrupted object was served)" ;;
    *) record FAIL D7 "probe did not run: $(tail -n 2 <<<"$out" | tr '\n' ' ')" ;;
  esac
}

# D8: backup restore drill = timed run of backend/backup/restore-test.sh (RTO) + age of newest snapshot (RPO)
d8() {
  local rt="$REPO/backend/backup/restore-test.sh" t0 el rc=0 age snap_ts
  mark "begin D8"
  if ! command -v restic >/dev/null 2>&1 || [ -z "${RESTIC_REPOSITORY:-}" ]; then skip D8 "restic and RESTIC_REPOSITORY/RESTIC_PASSWORD needed (backend/backup/README.md)"; return 0; fi
  snap_ts=$(restic snapshots --latest 1 --json 2>/dev/null | python3 -c 'import sys,json,datetime as d;s=json.load(sys.stdin);print(int(d.datetime.fromisoformat(s[-1]["time"][:19]+"+00:00").timestamp()) if s else 0)' 2>/dev/null || echo 0)
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: $rt --report $RESULTS_DIR/D8-restore.json"; return 0; fi
  age=$(( $(date +%s) - snap_ts ))
  if [ "$snap_ts" = 0 ]; then record FAIL D8 "no snapshot found in the restic repo"; else check D8 newest_snapshot_age_s "$age" le "$D8_RPO_S"; fi
  t0=$SECONDS
  bash "$rt" --report "$RESULTS_DIR/D8-restore.json" >"$RESULTS_DIR/D8-restore.log" 2>&1 || rc=$?
  el=$(( SECONDS - t0 ))
  if [ "$rc" = 0 ]; then record PASS D8 "restore verified, row counts reconciled (see D8-restore.json)"; else record FAIL D8 "restore-test.sh exit $rc, see D8-restore.log"; fi
  check D8 restore_seconds "$el" le "$D8_RTO_S"
}

# D11: soak. External-style probe every D11_EVERY_S for --hours; every gap >= D11_GAP_S is classified.
d11() {
  local csv=$RESULTS_DIR/D11.probe.csv end now code ms rs0 up0 last_ok=0 gap_start=0 n=0 bad=0 avail t0
  mark "begin D11"
  [ -n "$BASE_URL" ] || { skip D11 "BASE_URL not set"; return 0; }
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: probe $BASE_URL/healthz every ${D11_EVERY_S}s for ${HOURS}h -> $csv"; return 0; fi
  echo "epoch,code,dns_s,connect_s,tls_s,ttfb_s,total_s" >"$csv"
  rs0=$(restart_total); up0=$(awk '{print int($1)}' /proc/uptime); t0=$(date +%s); end=$(( t0 + HOURS * 3600 ))
  trap 'end=0' INT TERM    # Ctrl-C ends the soak early but still evaluates
  info D11 "soak ${HOURS}h against $BASE_URL (Ctrl-C to stop early)"
  while now=$(date +%s); [ "$now" -lt "$end" ]; do
    out=$("${CURL[@]}" -m 10 -o /dev/null -w '%{http_code},%{time_namelookup},%{time_connect},%{time_appconnect},%{time_starttransfer},%{time_total}' "$BASE_URL/healthz" 2>/dev/null || echo "000,0,0,0,0,0")
    code=${out%%,*}; echo "$now,$out" >>"$csv"; n=$(( n + 1 ))
    if [[ $code == 2* ]]; then
      if [ "$gap_start" != 0 ] && [ $(( now - gap_start )) -ge "$D11_GAP_S" ]; then
        info D11 "GAP $(date -d "@$gap_start" +%FT%T) .. $(date -d "@$now" +%FT%T) ($(( now - gap_start ))s) $(classify_gap "$gap_start" "$now" "$rs0" "$up0" "$t0")"
      fi
      gap_start=0; last_ok=$now
    else bad=$(( bad + 1 )); [ "$gap_start" != 0 ] || gap_start=${last_ok:-$now}; fi
    sleep "$D11_EVERY_S" || true
  done
  trap - INT TERM
  avail=$(awk -v n="$n" -v b="$bad" 'BEGIN{printf "%.3f", n? 100*(n-b)/n : 0}')
  check D11 availability_pct "$avail" ge "$D11_MIN_AVAIL"
  info D11 "probes=$n failed=$bad; graph: report.py picks up D11.probe.csv"
}

# classify_gap START END RESTARTS0 UPTIME0 T0: one-line cause hint (power / os / docker / tunnel / app / unknown)
classify_gap() {
  local s=$1 e=$2 rs0=$3 up0=$4 t0=$5 up cause=unknown
  up=$(awk '{print int($1)}' /proc/uptime)
  if [ $(( $(date +%s) - up )) -gt "$s" ] && [ $(( $(date +%s) - up )) -lt "$e" ]; then cause="reboot (power or kernel; uptime reset)"
  elif ! systemctl is-active --quiet docker 2>/dev/null; then cause="docker daemon down"
  elif ! svc_running cloudflared; then cause="tunnel container down"
  elif [ "$(restart_total)" -gt "$rs0" ]; then cause="container restart(s): $(restart_total) total vs $rs0 at start"
  elif [ "$(origin_status /healthz)" = 200 ]; then cause="origin healthy now: tunnel / Cloudflare / client network"
  else cause="application unhealthy"; fi
  echo "cause=$cause throttled=$(pi_throttled 2>/dev/null || echo na)"
}

d9() {
  local wd cfg
  wd=$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || echo 0)
  if ls /dev/watchdog* >/dev/null 2>&1; then record PASS D9 "watchdog device present"; else record FAIL D9 "no /dev/watchdog (dtparam=watchdog=on?)"; fi
  if [ -n "$wd" ] && [ "$wd" != 0 ] && [ "$wd" != infinity ]; then record PASS D9 "systemd RuntimeWatchdogSec=$wd"; else record FAIL D9 "systemd RuntimeWatchdogSec not set (setup_pi.sh --apply)"; fi
  cfg=/boot/firmware/config.txt
  if grep -qs '^dtparam=watchdog=on' "$cfg"; then record PASS D9 "dtparam=watchdog=on in $cfg"; else info D9 "dtparam=watchdog=on not found in $cfg"; fi
  if [ "$DESTRUCTIVE" = 1 ] && [ "$PANIC" = 1 ]; then
    mkdir -p "$STATE_DIR"; [ "$DRY_RUN" = 1 ] || date +%s >"$STATE_DIR/d9.ts"
    info D9 "kernel panic NOW; the watchdog must reboot within 1 min; afterwards run verify_after_boot.sh"
    run bash -c 'echo 1 >/proc/sys/kernel/sysrq; echo c >/proc/sysrq-trigger'
  else info D9 "panic trigger skipped (needs --destructive --panic)"; fi
}

d10() {
  local s c out t size files
  for s in $CORE_SERVICES; do
    c=$(cid "$s"); [ -n "$c" ] || continue
    out=$(docker inspect -f '{{.HostConfig.LogConfig.Type}} {{index .HostConfig.LogConfig.Config "max-size"}} {{index .HostConfig.LogConfig.Config "max-file"}}' "$c" 2>/dev/null || echo "? ? ?")
    read -r t size files <<<"$out"
    case $size in *m | *M) size=${size%[mM]} ;; *) size=999999 ;; esac
    if [ "$t" = json-file ] && [ "$size" -le "$D10_MAX_SIZE_MB" ] && [ "${files:-99}" -le "$D10_MAX_FILE" ] 2>/dev/null; then
      record PASS "D10:$s" "json-file ${size}m x $files"
    else record FAIL "D10:$s" "log config '$out' (daemon.json log-opts apply to NEW containers: recreate)"; fi
  done
  out=$(journalctl --disk-usage 2>/dev/null | grep -Eo '[0-9.]+[MG]' | head -n1 || true)
  info D10 "journal usage: ${out:-unknown}"
  if grep -rhEs '^SystemMaxUse=' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/ 2>/dev/null | grep -Eq "=([0-9]+)M" ; then
    t=$(grep -rhEs '^SystemMaxUse=' /etc/systemd/journald.conf /etc/systemd/journald.conf.d/ | tail -n1 | tr -dc 0-9)
    check D10 journald_SystemMaxUse_mb "$t" le "$D10_JOURNAL_MB"
  else record FAIL D10 "journald SystemMaxUse not set (setup_pi.sh --apply)"; fi
  [ -d /etc/logrotate.d ] && info D10 "logrotate.d entries: $(find /etc/logrotate.d -type f | wc -l)"
  if [ "$GENLOGS" = 1 ]; then
    run docker run -d --name clarion-logtest alpine sh -c 'yes 0123456789abcdef | head -c 1073741824'
    if [ "$DRY_RUN" != 1 ]; then
      docker wait clarion-logtest >/dev/null
      t=$(du -sm "/var/lib/docker/containers/$(docker inspect -f '{{.Id}}' clarion-logtest)" | cut -f1)
      docker rm -f clarion-logtest >/dev/null
      check D10 logdir_after_1GB_mb "$t" le $(( D10_MAX_SIZE_MB * D10_MAX_FILE + 5 ))
    fi
  fi
}

d12() {
  local svc="" s code before
  for s in chrony systemd-timesyncd; do systemctl is-active --quiet "$s" 2>/dev/null && svc="$svc $s"; done
  info D12 "time services stopped:${svc:- none active}"
  before=$(restart_total)
  [ "$DRY_RUN" = 1 ] && { echo "DRY: systemctl stop$svc; date -s +${D12_SKEW_S}s; probe; restore"; return 0; }
  T_ORIG=$(date +%s); T_SECS0=$SECONDS; SKEWED=1
  # shellcheck disable=SC2086
  [ -z "$svc" ] || systemctl stop $svc
  date -s "@$(( T_ORIG + D12_SKEW_S ))" >/dev/null
  sleep 5
  check D12 healthz_http "$(origin_status /healthz)" ge 200
  code=$("${CURL[@]}" -m 10 -o /dev/null -w '%{http_code}' -H 'Authorization: Bearer aaa.bbb.ccc' "$BASE_URL$PROTECTED_PATH" 2>/dev/null || true)
  case $code in 401 | 403) record PASS D12 "forged token rejected ($code) under +${D12_SKEW_S}s skew" ;; *) record FAIL D12 "forged token got HTTP $code (want 401/403, not 5xx)" ;; esac
  check D12 container_restarts "$(( $(restart_total) - before ))" le 0
  date -s "@$(( T_ORIG + SECONDS - T_SECS0 ))" >/dev/null; SKEWED=0
  # shellcheck disable=SC2086
  [ -z "$svc" ] || systemctl start $svc
  info D12 "clock restored; deterministic webhook/JWT timestamp rejection is asserted by the sec suite"
}

for id in "${IDS[@]}"; do
  echo "=== $id ==="; mark "begin $id"
  "d${id#D}"
done
summary
