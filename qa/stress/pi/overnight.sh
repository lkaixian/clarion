#!/usr/bin/env bash
# overnight.sh - unattended queue of the destructive + soak tests for the TEST Pi (never production).
#   sudo -E ./overnight.sh [--dry-run]            start it with setsid/nohup; it survives the SSH session
# Order matters: network and destructive tests first, soaks after (a kill or reboot would void a soak),
# the cold-boot test D4 last (it reboots the Pi; a cron @reboot hook runs verify_after_boot.sh and writes DONE).
# Between steps a health gate waits for the whole stack; if it cannot recover it, the queue stops (ABORT).
# Everything lands in results/overnight-<timestamp>/ : queue.log, one <step>.log and one results folder per step.
set -u
cd "$(dirname "$0")"
HERE=$PWD
# PROBE_GAP must be set BEFORE lib.sh loads: lib.sh defaults it to 0.2 s, which exceeds the app's 60 req/min per-IP
# limit and turns most probes into HTTP 429 (this happened in the first pilot run).
export PROBE_GAP=${PROBE_GAP:-1.1}
. "$HERE/lib.sh"                       # REPO, COMPOSE_FILE, DRY_RUN (from --dry-run)

export BASE_URL=${BASE_URL:-https://clarion.test:18443}
export CORE_SERVICES="mariadb backend proxy redis minio mpi web"
export D1_SERVICES="web redis mpi minio backend proxy mariadb"       # no cloudflared: the test Pi has no tunnel
export H7_SECS=${H7_SECS:-21600}                                      # 6 h soak
NS=${NS_CONTAINER:-clarion-pi-proxy-1}                                # shape inside the proxy's netns
OUT=${OVERNIGHT_OUT:-$HERE/results/overnight-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"; LOG=$OUT/queue.log
DRYARG=(); [ "$DRY_RUN" = 1 ] && DRYARG=(--dry-run)

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

gate() {   # whole stack healthy + healthz 200; one automatic recovery attempt (compose up -d)
  [ "$DRY_RUN" = 1 ] && { say "DRY: gate"; return 0; }
  local tries=0 i n code
  while [ "$tries" -lt 2 ]; do
    i=0
    while [ "$i" -lt 120 ]; do
      n=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter health=healthy -q | wc -l)
      code=$(curl -sk -m 8 -o /dev/null -w '%{http_code}' "$BASE_URL/api/healthz" || true)
      [ "$n" -ge 7 ] && [ "$code" = 200 ] && return 0
      sleep 5; i=$(( i + 1 ))
    done
    say "gate: not healthy after 10 min (healthy=$n http=$code); running compose up -d"
    docker compose -f "$COMPOSE_FILE" --project-directory "$REPO" --env-file "$REPO/.env.docker" up -d >>"$LOG" 2>&1
    tries=$(( tries + 1 ))
  done
  return 1
}

cleanup_net() {   # idempotent: remove any shaping a killed step could have left, and restore time sync
  [ "$DRY_RUN" = 1 ] && return 0
  bash "$HERE/netem.sh" --ns "$NS" eth0 off >/dev/null 2>&1 || true
  bash "$HERE/netem.sh" "$(default_if)" off >/dev/null 2>&1 || true
  systemctl start systemd-timesyncd >/dev/null 2>&1 || true
  rm -f /var/lib/docker/fill.bin
}

step() {  # NAME TIMEOUT_S CMD...
  local name=$1 to=$2; shift 2
  say "BEGIN $name"
  RESULTS_DIR=$OUT/$name timeout "$to" "$@" >"$OUT/$name.log" 2>&1; local rc=$?
  say "END   $name rc=$rc  $(grep -h '^SUMMARY' "$OUT/$name.log" | tail -1)"
  cleanup_net
  gate || { say "ABORT: stack did not recover after $name; queue stopped, see $OUT"; exit 3; }
}

say "queue start  host=$(hostname)  out=$OUT  dry=$DRY_RUN  H7_SECS=$H7_SECS"
gate || { say "ABORT: stack not healthy at start"; exit 3; }

# 1. network (shaping inside the proxy container; N10 tunnel stop does not apply here)
step net-N1-N7     3000 env NS_CONTAINER="$NS" N1_SECS=300 "$HERE/net_scenarios.sh" "${DRYARG[@]}"
step net-N8-N9-N11 1800 env NS_CONTAINER="$NS" "$HERE/net_scenarios.sh" "${DRYARG[@]}" --disruptive N8 N9 N11
# 2. destructive hardware (OOM, disk full, worst case)
step hw-H5-H10-H13 3600 "$HERE/hw_stress.sh" "${DRYARG[@]}" --i-know-this-kills H5 H10 H13
# 3. durability (kill containers, restart docker, down/up, clock skew, object corruption, config checks)
step dur-destructive 3600 "$HERE/durability.sh" "${DRYARG[@]}" --destructive D1 D2 D3 D6 D12
step dur-D7-D9-D10   900 "$HERE/durability.sh" "${DRYARG[@]}" D7 D9 D10
# 4. soaks
step hw-H2           3000 "$HERE/hw_stress.sh" "${DRYARG[@]}" H2
step hw-H7           $(( H7_SECS + 1800 )) "$HERE/hw_stress.sh" "${DRYARG[@]}" H7

# 5. cold boot last. The hook (cron @reboot) verifies after boot, writes DONE, removes itself.
say "snapshot + reboot for D4"
if [ "$DRY_RUN" = 1 ]; then
  say "DRY: would install /etc/cron.d/clarion-overnight and run durability.sh --destructive D4"; say "queue end (dry)"; exit 0
fi
cat >/etc/cron.d/clarion-overnight <<EOF
@reboot root cd $HERE && BASE_URL=$BASE_URL CORE_SERVICES="$CORE_SERVICES" RESULTS_DIR=$OUT/D4-verify ./verify_after_boot.sh >$OUT/D4-verify.log 2>&1; echo "\$(date -u +\\%FT\\%TZ) D4 verify finished rc=\$?" >>$LOG; rm -f /etc/cron.d/clarion-overnight; touch $OUT/DONE
EOF
chmod 644 /etc/cron.d/clarion-overnight
RESULTS_DIR=$OUT/dur-D4 "$HERE/durability.sh" --destructive D4 >"$OUT/dur-D4.log" 2>&1
say "reboot issued"; sleep 120      # the reboot happens during this sleep; the hook finishes the run
