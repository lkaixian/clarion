#!/usr/bin/env bash
# Shared helpers for qa/stress/pi. Source it (no arguments): . "$(dirname "$0")/lib.sh"
# Sourcing without args keeps the caller's "$@", which is how --dry-run is picked up.
# shellcheck disable=SC2034  # variables here are consumed by the sourcing scripts

LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$LIB_DIR/../../.." && pwd)

DRY_RUN=${DRY_RUN:-0}
case " $* " in *" --dry-run "*) DRY_RUN=1 ;; esac

# ---- environment (override from the shell) ---------------------------------
PROJECT=${PROJECT:-clarion-pi}                         # compose project name (docker-compose.pi.yml: name:)
COMPOSE_FILE=${COMPOSE_FILE:-$REPO/docker-compose.pi.yml}
CORE_SERVICES=${CORE_SERVICES:-"mariadb backend proxy redis minio mpi cloudflared web"}
BASE_URL=${BASE_URL:-}                                 # e.g. https://clarion.larmkx.com
CURL_EXTRA=${CURL_EXTRA:-}                             # e.g. "--resolve clarion.larmkx.com:443:172.29.0.2"
PROBE_PATH=${PROBE_PATH:-/api/healthz}
CURL_TIMEOUT=${CURL_TIMEOUT:-10}
PROBE_GAP=${PROBE_GAP:-1.1}   # seconds between probe requests; the app allows 60 req/min per IP, a smaller gap turns probes into HTTP 429
LOGIN_USER=${LOGIN_USER:-}                             # test account only (visible in ps while curl runs)
LOGIN_PASS=${LOGIN_PASS:-}
STATE_DIR=${STATE_DIR:-/var/lib/clarion-stress}        # survives reboots (snapshots, D5 cycle counter)
RESULTS_DIR=${RESULTS_DIR:-$LIB_DIR/results/$(date +%Y%m%d-%H%M%S)}
export RESULTS_DIR

read -r -a CURL_X <<<"$CURL_EXTRA"
CURL=(curl -sk "${CURL_X[@]}")

# ---- basics ----------------------------------------------------------------
die() { echo "ERROR: $*" >&2; exit 2; }

rdir() { mkdir -p "$RESULTS_DIR"; }

mark() { rdir; echo "$(date -u +%FT%TZ) $*" >>"$RESULTS_DIR/events.log"; }

need_root() {
  [ "$(id -u)" -eq 0 ] && return 0
  [ "$DRY_RUN" = 1 ] && { echo "WARN: not root (ok for --dry-run)" >&2; return 0; }
  die "run as root (sudo)"
}

# need_tools tool... : map to apt packages, print the install hint, abort if missing
need_tools() {
  local t miss=() pkgs=() p
  for t in "$@"; do
    command -v "$t" >/dev/null 2>&1 && continue
    miss+=("$t")
    case $t in
      iostat) p=sysstat ;; tc | ip) p=iproute2 ;; nsenter | fallocate) p=util-linux ;;
      vcgencmd) p=libraspberrypi-bin ;; mmc) p=mmc-utils ;; smartctl) p=smartmontools ;;
      *) p=$t ;;
    esac
    pkgs+=("$p")
  done
  [ "${#miss[@]}" -eq 0 ] && return 0
  if [ "$DRY_RUN" = 1 ]; then echo "WARN: missing ${miss[*]} (ok for --dry-run)" >&2; return 0; fi
  die "missing: ${miss[*]}  ->  sudo apt install -y ${pkgs[*]}"
}

# run CMD... : execute, or only print under --dry-run (use for every destructive/mutating step)
run() { if [ "$DRY_RUN" = 1 ]; then echo "DRY: $*"; else "$@"; fi; }

# ---- recorder --------------------------------------------------------------
record() { rdir; printf '%s %s %s\n' "$1" "$2" "${3:-}" | tee -a "$RESULTS_DIR/results.txt"; }
info() { record INFO "$1" "${2:-}"; }
skip() { record SKIP "$1" "${2:-}"; }

# check ID LABEL VALUE le|ge LIMIT
check() {
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: check $1 $2 $3 $4 $5"; return 0; fi
  if awk -v v="$3" -v l="$5" -v o="$4" 'BEGIN{exit !(o=="le" ? v<=l : v>=l)}'; then
    record PASS "$1" "$2=$3 ($4 $5)"
  else
    record FAIL "$1" "$2=$3 ($4 $5)"
  fi
}

summary() {
  rdir; touch "$RESULTS_DIR/results.txt"
  local p f s
  p=$(grep -c '^PASS ' "$RESULTS_DIR/results.txt" || true)
  f=$(grep -c '^FAIL ' "$RESULTS_DIR/results.txt" || true)
  s=$(grep -c '^SKIP ' "$RESULTS_DIR/results.txt" || true)
  echo "SUMMARY pass=$p fail=$f skip=$s  results=$RESULTS_DIR"
  [ "$f" -eq 0 ]
}

# ---- Pi sensors ------------------------------------------------------------
pi_temp() {
  local t=""
  if command -v vcgencmd >/dev/null 2>&1; then
    t=$(vcgencmd measure_temp 2>/dev/null | sed -n "s/^temp=\([0-9.]*\).*/\1/p" || true)
  fi
  if [ -z "$t" ] && [ -r /sys/class/thermal/thermal_zone0/temp ]; then
    t=$(awk '{printf "%.1f",$1/1000}' /sys/class/thermal/thermal_zone0/temp)
  fi
  echo "${t:-na}"
}
pi_throttled() {
  local t=""
  if command -v vcgencmd >/dev/null 2>&1; then
    t=$(vcgencmd get_throttled 2>/dev/null | sed -n 's/^throttled=//p' || true)
  fi
  echo "${t:-na}"
}
pi_clock() {
  local t=""
  if command -v vcgencmd >/dev/null 2>&1; then
    t=$(vcgencmd measure_clock arm 2>/dev/null | sed -n 's/^.*=//p' || true)
  fi
  if [ -z "$t" ] && [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ]; then
    t=$(awk '{print $1*1000}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)
  fi
  echo "${t:-na}"
}
swap_pages() { awk '/^pswpin|^pswpout/{s+=$2} END{print s+0}' /proc/vmstat 2>/dev/null || echo 0; }
default_if() { ip route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}' || true; }

# check_throttle ID BEFORE MASK : fail only on bits that became set during the test
# (get_throttled is sticky since boot, so a raw "== 0x0" would blame earlier events)
check_throttle() {
  local id=$1 before=$2 mask=${3:-0xFFFFFFFF} after new
  [ "$DRY_RUN" = 1 ] && { echo "DRY: check_throttle $id"; return 0; }
  after=$(pi_throttled)
  if [ "$after" = na ] || [ "$before" = na ]; then skip "$id" "get_throttled unavailable (no vcgencmd)"; return 0; fi
  new=$(( after & ~before & mask ))
  if [ "$new" -eq 0 ]; then record PASS "$id" "no new throttle bits (before=$before after=$after mask=$mask)"
  else record FAIL "$id" "new throttle bits $(printf '0x%x' "$new") (before=$before after=$after)"; fi
}

# ---- docker helpers --------------------------------------------------------
cid() {
  docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=$1" | head -n1
}
svc_running() { [ "$(docker inspect -f '{{.State.Running}}' "$(cid "$1")" 2>/dev/null || echo false)" = true ]; }
restart_count() { docker inspect -f '{{.RestartCount}}' "$(cid "$1")" 2>/dev/null || echo 0; }
restart_total() { local s n=0; for s in $CORE_SERVICES; do n=$(( n + $(restart_count "$s") )); done; echo "$n"; }

# wait_up SVC SECS : echo elapsed seconds, rc 1 on timeout. "up" = running and (healthy or no healthcheck)
wait_up() {
  local s=0 st
  while (( s < $2 )); do
    st=$(docker inspect -f '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$(cid "$1")" 2>/dev/null || echo "false none")
    case $st in "true healthy" | "true none") echo "$s"; return 0 ;; esac
    sleep 1; s=$(( s + 1 ))
  done
  echo "$s"; return 1
}

# check_core ID : every core service still running
check_core() {
  local s bad=""
  [ "$DRY_RUN" = 1 ] && { echo "DRY: check_core $1"; return 0; }
  for s in $CORE_SERVICES; do svc_running "$s" || bad="$bad $s"; done
  if [ -z "$bad" ]; then record PASS "$1" "all core containers running"; else record FAIL "$1" "not running:$bad"; fi
}

# origin_status PATH : HTTP status of the backend as seen from inside its own container (0 = unreachable)
ORIGIN_PY='import sys,urllib.request as u,urllib.error as e
try: print(u.urlopen("http://127.0.0.1:8000"+sys.argv[1],timeout=5).status)
except e.HTTPError as x: print(x.code)
except Exception: print(0)'
origin_status() { docker exec "$(cid backend)" python -c "$ORIGIN_PY" "$1" 2>/dev/null || echo 0; }

# ---- database helpers (root via the container's own env; nothing stored here) ----
dbx() { docker exec -i "$(cid mariadb)" sh -c 'exec mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" "$@"' _ "$@"; }

# db_check : mariadb-check on everything; rc 0 if clean
db_check() {
  local out
  out=$(docker exec "$(cid mariadb)" sh -c 'exec mariadb-check --all-databases -uroot -p"$MARIADB_ROOT_PASSWORD"' 2>&1) || true
  echo "$out" >"$RESULTS_DIR/mariadb-check.$(date +%s).txt"
  ! grep -Eiq '^(error|warning)[[:space:]]*:|corrupt|crashed' <<<"$out"
}

# db_commit_ms [N] : average autocommit INSERT latency (ms) in a scratch schema
db_commit_ms() {
  local n=${1:-50} i t0 t1
  dbx -e 'CREATE DATABASE IF NOT EXISTS stress_scratch; CREATE TABLE IF NOT EXISTS stress_scratch.c (id BIGINT AUTO_INCREMENT PRIMARY KEY, v INT) ENGINE=InnoDB'
  t0=$(date +%s%N)
  for ((i = 0; i < n; i++)); do echo 'INSERT INTO stress_scratch.c (v) VALUES (1);'; done | dbx
  t1=$(date +%s%N)
  echo $(( (t1 - t0) / 1000000 / n ))
}
db_scratch_drop() { dbx -e 'DROP DATABASE IF EXISTS stress_scratch' || true; }

# ---- probe (client-side latency; run it from where the traffic should originate) ----
pct() { sort -n "$1" | awk -v p="$2" '{a[NR]=$1} END{if(!NR){print 0;exit} i=int(NR*p/100+0.9999); if(i<1)i=1; print a[i]}'; }

# probe ID SECS [PATH] -> PROBE_N PROBE_FAIL PROBE_5XX PROBE_OK_PCT PROBE_MED PROBE_P95 PROBE_P99 PROBE_MAX (ms)
# LOCUST=1 uses backend/loadtest/locustfile.py headless (LOCUST_USERS, LOCUST_RATE) instead of the curl loop.
probe() {
  local id=$1 secs=$2 path=${3:-$PROBE_PATH} csv end t out tmp
  PROBE_N=0 PROBE_FAIL=0 PROBE_5XX=0 PROBE_OK_PCT=0 PROBE_MED=0 PROBE_P95=0 PROBE_P99=0 PROBE_MAX=0
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: probe $id ${secs}s ${BASE_URL}${path}"; return 0; fi
  [ -n "$BASE_URL" ] || die "set BASE_URL (e.g. https://clarion.larmkx.com)"
  rdir
  if [ "${LOCUST:-0}" = 1 ]; then
    need_tools locust
    locust -f "$REPO/backend/loadtest/locustfile.py" --headless -u "${LOCUST_USERS:-20}" -r "${LOCUST_RATE:-5}" \
      -t "${secs}s" --host "$BASE_URL" --csv "$RESULTS_DIR/$id" --only-summary >"$RESULTS_DIR/$id.locust.log" 2>&1 || true
    out=$(awk -F, 'NR==1{for(i=1;i<=NF;i++)h[$i]=i; next} $2=="Aggregated"{print $h["Request Count"],$h["Failure Count"],$h["Median Response Time"],$h["95%"],$h["99%"],$h["Max Response Time"]}' "$RESULTS_DIR/${id}_stats.csv")
    read -r PROBE_N PROBE_FAIL PROBE_MED PROBE_P95 PROBE_P99 PROBE_MAX <<<"$out"
    PROBE_5XX=$PROBE_FAIL
  else
    csv=$RESULTS_DIR/$id.probe.csv; tmp=$csv.ms
    echo "epoch,code,dns_s,connect_s,tls_s,ttfb_s,total_s" >"$csv"
    end=$(( SECONDS + secs ))
    while (( SECONDS < end )); do
      t=$(date +%s)
      out=$("${CURL[@]}" -m "$CURL_TIMEOUT" -o /dev/null \
        -w '%{http_code},%{time_namelookup},%{time_connect},%{time_appconnect},%{time_starttransfer},%{time_total}' \
        "$BASE_URL$path" 2>/dev/null) || true
      echo "$t,${out:-000,0,0,0,0,0}" >>"$csv"
      sleep "$PROBE_GAP"
    done
    PROBE_N=$(( $(wc -l <"$csv") - 1 ))
    PROBE_FAIL=$(awk -F, 'NR>1 && $2!~/^[23]/' "$csv" | wc -l)
    PROBE_5XX=$(awk -F, 'NR>1 && $2~/^5/' "$csv" | wc -l)
    awk -F, 'NR>1{print $7*1000}' "$csv" >"$tmp"
    PROBE_MED=$(pct "$tmp" 50); PROBE_P95=$(pct "$tmp" 95); PROBE_P99=$(pct "$tmp" 99); PROBE_MAX=$(pct "$tmp" 100)
  fi
  PROBE_OK_PCT=$(awk -v n="$PROBE_N" -v f="$PROBE_FAIL" 'BEGIN{printf "%.3f", n ? 100*(n-f)/n : 0}')
  info "$id" "probe n=$PROBE_N fail=$PROBE_FAIL 5xx=$PROBE_5XX ok%=$PROBE_OK_PCT med=${PROBE_MED}ms p95=${PROBE_P95}ms p99=${PROBE_P99}ms max=${PROBE_MAX}ms"
}

# login_probe ID MAX_MS : form login (OAuth2 password form) with LOGIN_USER/LOGIN_PASS; skipped if unset
login_probe() {
  local out code ms
  if [ -z "$LOGIN_USER" ] || [ -z "$LOGIN_PASS" ]; then skip "$1" "LOGIN_USER/LOGIN_PASS not set"; return 0; fi
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: login_probe $1"; return 0; fi
  out=$("${CURL[@]}" -m "$CURL_TIMEOUT" -o /dev/null -w '%{http_code} %{time_total}' \
    --data-urlencode "username=$LOGIN_USER" --data-urlencode "password=$LOGIN_PASS" \
    "$BASE_URL/api/auth/login" 2>/dev/null) || true
  code=${out%% *}; ms=$(awk -v t="${out##* }" 'BEGIN{printf "%d", t*1000}')
  if [ "$code" = 200 ]; then check "$1" login_ms "$ms" le "$2"; else record FAIL "$1" "login http=$code"; fi
}

# wait_ok SECS : poll BASE_URL+PROBE_PATH until 200; echo ms to first success, rc 1 on timeout
wait_ok() {
  local t0 now code
  t0=$(date +%s%N)
  while :; do
    code=$("${CURL[@]}" -m 2 -o /dev/null -w '%{http_code}' "$BASE_URL$PROBE_PATH" 2>/dev/null) || true
    now=$(date +%s%N)
    [ "$code" = 200 ] && { echo $(( (now - t0) / 1000000 )); return 0; }
    (( (now - t0) / 1000000000 >= $1 )) && { echo $(( (now - t0) / 1000000 )); return 1; }
    sleep 0.5
  done
}

# ---- background collector ---------------------------------------------------
COLLECT_PID=""
collect_start() {
  [ "$DRY_RUN" = 1 ] && { echo "DRY: collect.sh start"; return 0; }
  [ "${COLLECT_EXTERNAL:-0}" = 1 ] && return 0
  [ -n "$COLLECT_PID" ] && return 0
  rdir
  bash "$LIB_DIR/collect.sh" >/dev/null 2>&1 &
  COLLECT_PID=$!
}
collect_stop() {
  if [ -n "$COLLECT_PID" ]; then kill "$COLLECT_PID" 2>/dev/null || true; wait "$COLLECT_PID" 2>/dev/null || true; fi
  COLLECT_PID=""
}
# shellcheck disable=SC2046
kill_jobs() { kill $(jobs -p) 2>/dev/null || true; }
