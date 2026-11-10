#!/usr/bin/env bash
# net_scenarios.sh - N1..N12 network degradation drivers (spec section A).
#   net_scenarios.sh [--dry-run] [--disruptive] [N1 N5 ...]     default: N1-N7 (N12 is manual)
# N8 (slowloris), N9 (blackout), N10 (tunnel stop), N11 (DNS block) need --disruptive.
#
# Where to run it decides what is shaped:
#   on the Pi, BASE_URL = public URL      -> traffic leaves via cloudflared on the Pi uplink  (SERVER side)
#   on the Pi, NS_CONTAINER=cloudflared   -> shaping only inside that container's netns, SSH untouched
#   on the load generator                 -> IFACE is the generator's NIC                      (CLIENT side)
# netem.sh always arms a dead-man switch; leaving the SSH interface shaped is impossible past DEADMAN.
set -euo pipefail
. "$(dirname "$0")/lib.sh"

# ---- thresholds (spec section A) --------------------------------------------
N1_SECS=${N1_SECS:-600};   N1_WARMUP=${N1_WARMUP:-60}
N1_MED_MS=1000;            N1_OKPCT=99.9
N2_MED_MS=3000;            N2_5XX=0
N3_MAX_MS=10000;           N3_LOGIN_MS=10000
N4_OKPCT=99.9;             N4_MAX_MS=10000
N5_MAX_MS=11000            # curl -m is CURL_TIMEOUT (10 s); anything above = a hang
N6_OKPCT=99.9;             N6_5XX=0
N7_BLOCK_SECS=30;          N7_MAX_MS=11000;  N7_RECOVER_MS=5000
N8_SECS=60;                N8_OKPCT=99
N9_BLACKOUT_SECS=60;       N9_RECOVER_MS=5000
N10_DOWN_SECS=120;         N10_RECONNECT_S=30
N11_LOGIN_MS=10000
NET_SECS=${NET_SECS:-60}   # probe window per shaped scenario
DEADMAN_PAD=${DEADMAN_PAD:-120}

IFACE=${IFACE:-$(default_if)}
[ -n "$IFACE" ] || [ "$DRY_RUN" != 1 ] || IFACE=eth0
NS_CONTAINER=${NS_CONTAINER:-}
[ -z "$NS_CONTAINER" ] || IFACE=${IFACE_IN_NS:-eth0}
EMERGENCY_PATH=${EMERGENCY_PATH:-$PROBE_PATH}

DISRUPTIVE=0 IDS=()
for a in "$@"; do
  case $a in
    --dry-run) ;;
    --disruptive) DISRUPTIVE=1 ;;
    N[0-9] | N1[0-2]) IDS+=("$a") ;;
    *) die "unknown argument: $a" ;;
  esac
done
[ "${#IDS[@]}" -gt 0 ] || IDS=(N1 N2 N3 N4 N5 N6 N7)

need_root; need_tools curl awk tc ip
[ "$DRY_RUN" = 1 ] || [ -n "$IFACE" ] || die "cannot detect IFACE, set IFACE=eth0"
[ -z "$NS_CONTAINER" ] || need_tools docker nsenter
[ "$DRY_RUN" = 1 ] || [ -n "$BASE_URL" ] || die "set BASE_URL"

NETEM_ARGS=()
[ -z "$NS_CONTAINER" ] || NETEM_ARGS+=(--ns "$NS_CONTAINER")
[ "$DRY_RUN" != 1 ] || NETEM_ARGS+=(--dry-run)

CLEAN_CF=0 CLEAN_DNS=0 BACKEND_PID=0
cleanup() {
  trap - EXIT INT TERM
  bash "$LIB_DIR/netem.sh" "${NETEM_ARGS[@]}" "$IFACE" off >/dev/null 2>&1 || true
  if [ "$CLEAN_CF" = 1 ]; then docker start "$(cid cloudflared)" >/dev/null 2>&1 || true; fi
  if [ "$CLEAN_DNS" = 1 ]; then
    for p in udp tcp; do nsenter -t "$BACKEND_PID" -n iptables -D OUTPUT -p "$p" --dport 53 -j DROP 2>/dev/null || true; done
  fi
  kill_jobs
  collect_stop
}
trap cleanup EXIT INT TERM

shape() { # SPEC DIR SECS
  mark "shape '$1' dir=$2"
  DIR=$2 DEADMAN=$(( $3 + DEADMAN_PAD )) bash "$LIB_DIR/netem.sh" "${NETEM_ARGS[@]}" "$IFACE" "$1"
}
unshape() { bash "$LIB_DIR/netem.sh" "${NETEM_ARGS[@]}" "$IFACE" off; }

# shaped_probe ID SPEC DIR SECS : shape, probe, unshape (the EXIT trap is the safety net)
shaped_probe() {
  shape "$2" "$3" "$4"
  probe "$1" "$4"
  unshape
}
no_5xx() { check "$1" http_5xx "$PROBE_5XX" le "$2"; }

n1() {
  info N1 "warm-up ${N1_WARMUP}s discarded, then ${N1_SECS}s; p95 SERVER time needs Caddy/uvicorn logs or /metrics (not measured here)"
  probe N1-warmup "$N1_WARMUP"
  probe N1 "$N1_SECS"
  check N1 median_ms "$PROBE_MED" le "$N1_MED_MS"
  check N1 ok_pct "$PROBE_OK_PCT" ge "$N1_OKPCT"
  info N1 "p95_rtt=${PROBE_P95}ms (client RTT, not server time)"
}
n2() {
  shaped_probe N2 "rate 1mbit" both "$NET_SECS"
  check N2 median_ms "$PROBE_MED" le "$N2_MED_MS"; no_5xx N2 "$N2_5XX"
  if [ "$DRY_RUN" != 1 ]; then
    if "${CURL[@]}" -m 15 -H 'Accept-Encoding: gzip' -D - -o /dev/null "$BASE_URL/" | grep -qi '^content-encoding:'; then
      record PASS N2 "static asset served compressed"
    else record FAIL N2 "no content-encoding on $BASE_URL/ (enable Caddy encode zstd gzip)"; fi
  fi
  shape "rate 1mbit" both "$NET_SECS"; login_probe N2 "$N2_MED_MS"; unshape
}
n3() {
  shaped_probe N3 "rate 256kbit" both "$NET_SECS"
  check N3 max_ms "$PROBE_MAX" le "$N3_MAX_MS"
  shape "rate 256kbit" both "$NET_SECS"; probe N3-scan "$NET_SECS" "$EMERGENCY_PATH"
  check N3 scan_max_ms "$PROBE_MAX" le "$N3_MAX_MS"; login_probe N3 "$N3_LOGIN_MS"; unshape
  info N3 "'no worker pinned': inspect docker stats / gunicorn log in $RESULTS_DIR"
}
n4() {
  shaped_probe N4 "delay 200ms 50ms loss 1%" both "$NET_SECS"
  check N4 ok_pct "$PROBE_OK_PCT" ge "$N4_OKPCT"; check N4 max_ms "$PROBE_MAX" le "$N4_MAX_MS"
  info N4 "zero duplicated writes is asserted by the R group, not here"
}
n5() {
  shaped_probe N5a "loss 10%" out "$NET_SECS"
  check N5a max_ms "$PROBE_MAX" le "$N5_MAX_MS"
  shaped_probe N5b "loss 10%" both "$NET_SECS"
  check N5b max_ms "$PROBE_MAX" le "$N5_MAX_MS"
  info N5 "no half-written record: assert with the R/RN group"
}
n6() {
  shaped_probe N6 "delay 100ms reorder 25% 50% duplicate 5%" both "$NET_SECS"
  no_5xx N6 "$N6_5XX"; check N6 ok_pct "$PROBE_OK_PCT" ge "$N6_OKPCT"
}
n7() {
  shaped_probe N7 "loss 100%" in "$N7_BLOCK_SECS"
  check N7 max_ms "$PROBE_MAX" le "$N7_MAX_MS"
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: wait_ok 30"; return 0; fi
  local ms; ms=$(wait_ok 30) || true
  check N7 recovery_ms "$ms" le "$N7_RECOVER_MS"
}
n8() {
  need_tools slowhttptest
  local before spid; before=$(restart_total)
  run slowhttptest -c 500 -H -i 10 -r 100 -t GET -u "$BASE_URL/api/healthz" -l "$N8_SECS" -o "$RESULTS_DIR/N8.slowhttptest" >/dev/null 2>&1 &
  spid=$!
  probe N8 "$N8_SECS"
  wait "$spid" || true
  check N8 ok_pct "$PROBE_OK_PCT" ge "$N8_OKPCT"
  check N8 restarts_delta "$(( $(restart_total) - before ))" le 0
  info N8 "Caddy dropping slow headers at its timeout: confirm in proxy logs"
}
n9() {
  local before ms; before=$(restart_total)
  shape "loss 100%" both "$N9_BLACKOUT_SECS"
  [ "$DRY_RUN" = 1 ] || sleep "$N9_BLACKOUT_SECS"
  unshape
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: wait_ok 30"; return 0; fi
  ms=$(wait_ok 30) || true
  check N9 first_request_ms "$ms" le "$N9_RECOVER_MS"
  check N9 restarts_delta "$(( $(restart_total) - before ))" le 0
}
n10() {
  local before s; before=$(restart_total)
  CLEAN_CF=1
  run docker stop "$(cid cloudflared)"
  [ "$DRY_RUN" = 1 ] || sleep "$N10_DOWN_SECS"
  run docker start "$(cid cloudflared)"; CLEAN_CF=0
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: wait_ok $N10_RECONNECT_S"; return 0; fi
  s=$(( $(wait_ok 120 || true) / 1000 ))
  check N10 reconnect_s "$s" le "$N10_RECONNECT_S"
  check N10 other_restarts "$(( $(restart_total) - before ))" le 0
}
n11() {
  need_tools iptables nsenter
  BACKEND_PID=$(docker inspect -f '{{.State.Pid}}' "$(cid backend)" 2>/dev/null || echo 0)
  [ "$DRY_RUN" = 1 ] || [ "$BACKEND_PID" -gt 0 ] || die "backend not running"
  CLEAN_DNS=1
  for p in udp tcp; do run nsenter -t "$BACKEND_PID" -n iptables -I OUTPUT -p "$p" --dport 53 -j DROP; done
  probe N11 "$NET_SECS" "$EMERGENCY_PATH"
  check N11 ok_pct "$PROBE_OK_PCT" ge 99.9
  login_probe N11 "$N11_LOGIN_MS"
  info N11 "NIH RxClass should degrade, not fail: check backend logs in $RESULTS_DIR"
}
n12() { skip N12 "manual: airplane mode on the phone, scan NFC tag, reconnect (see spec)"; }

collect_start
for id in "${IDS[@]}"; do
  case $id in N8 | N9 | N10 | N11)
    [ "$DISRUPTIVE" = 1 ] || die "$id is disruptive: add --disruptive" ;;
  esac
  echo "=== $id ==="; mark "begin $id"
  "n${id#N}"
  mark "end $id"
done
collect_stop
summary
