#!/usr/bin/env bash
# campaign.sh - the whole test stack, unattended, on the Clean Prod Pi (192.168.1.7). One system, one build, one config.
#   sudo -E ./campaign.sh [--dry-run]        start with setsid/nohup; it survives the SSH session and the laptop going away
# Order: baseline -> security (CK/T/A + host) -> live races (R) -> races on bad networks (RN) -> network N1-N7 -> hardware
#        (safe) -> H2 -> H7 8 h soak -> D11 availability soak -> DESTRUCTIVE (N8-N11, H5/H10/H13, D1/D2/D3/D6/D12, D7/D9/D10,
#        H11 second reading) -> D4 cold reboot LAST (cron @reboot hook verifies and writes DONE).
# After every step a health gate waits for the whole stack and the public URL; if it cannot recover it, the queue stops (ABORT).
# Results: results/campaign-<timestamp>/ : queue.log, config.txt, not-run.txt, one <step>.log + results folder per step.
set -u
cd "$(dirname "$0")"
HERE=$PWD
REPO_C=$(cd "$HERE/../../.." && pwd)

# Refuse to run if any script has Windows line endings: bash then misreads variables (DRY_RUN becomes "0<CR>") and a dry run
# would execute for real. This happened once when the files were edited on Windows.
CR=$(printf '\r')
if grep -lq "$CR" "$HERE"/*.sh; then echo "ABORT: CRLF line endings in: $(grep -l "$CR" "$HERE"/*.sh | tr '\n' ' ')" >&2; exit 2; fi

# merged compose file: the repo's quay.io MinIO images are no longer pullable, use the identical local image (as on Dirty)
export COMPOSE_FILE=$REPO_C/docker-compose.campaign.yml
sed -E 's#quay.io/minio/(minio|mc):RELEASE[^[:space:]]*#clarion/minio:local#' "$REPO_C/docker-compose.pi.yml" > "$COMPOSE_FILE"
export PROBE_GAP=${PROBE_GAP:-1.1}                      # BEFORE lib.sh (its default would otherwise apply)
. "$HERE/campaign_env.sh"
. "$HERE/lib.sh"                                        # REPO, PROJECT, DRY_RUN (from --dry-run)
export H7_SECS=${H7_SECS:-28800}                        # 8 h
D11_HOURS=${D11_HOURS:-6}
OUT=${CAMPAIGN_OUT:-$HERE/results/campaign-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"; LOG=$OUT/queue.log
[ "$DRY_RUN" = 0 ] || [ "$DRY_RUN" = 1 ] || { echo "ABORT: DRY_RUN is '$DRY_RUN'" >&2; exit 2; }
case " $* " in *" --dry-run "*) [ "$DRY_RUN" = 1 ] || { echo "ABORT: --dry-run given but DRY_RUN=$DRY_RUN" >&2; exit 2; } ;; esac
DRYARG=(); [ "$DRY_RUN" = 1 ] && DRYARG=(--dry-run)
COMPOSE=(docker compose -f "$COMPOSE_FILE" --project-directory "$REPO_C" --env-file "$REPO_C/.env.docker")

say() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG"; }

gate() {   # whole stack healthy + public URL 200; one automatic recovery attempt
  [ "$DRY_RUN" = 1 ] && { say "DRY: gate"; return 0; }
  local tries=0 i n code
  while [ "$tries" -lt 2 ]; do
    i=0
    while [ "$i" -lt 120 ]; do
      n=$(docker ps --filter "label=com.docker.compose.project=$PROJECT" --filter health=healthy -q | wc -l)
      code=$(curl -sk -m 10 -o /dev/null -w '%{http_code}' "$BASE_URL/api/healthz" || true)
      [ "$n" -ge 7 ] && [ "$code" = 200 ] && return 0
      sleep 5; i=$(( i + 1 ))
    done
    say "gate: not healthy after 10 min (healthy=$n public=$code); running compose up -d"
    "${COMPOSE[@]}" up -d >>"$LOG" 2>&1
    tries=$(( tries + 1 ))
  done
  return 1
}

cleanup() {   # idempotent: undo anything a killed step could leave behind
  [ "$DRY_RUN" = 1 ] && return 0
  bash "$HERE/netem.sh" --ns "$NS_CONTAINER" eth0 off >/dev/null 2>&1 || true
  bash "$HERE/netem.sh" "$(default_if)" off >/dev/null 2>&1 || true
  systemctl start systemd-timesyncd >/dev/null 2>&1 || true
  rm -rf /var/lib/docker/fill.bin /var/lib/docker/clarion-fio
  docker rm -f toxiproxy >/dev/null 2>&1 || true
  sed -i '/ campaign-rn$/d' /etc/hosts 2>/dev/null || true
}

step() {  # NAME TIMEOUT_S CMD...
  local name=$1 to=$2; shift 2
  say "BEGIN $name"
  RESULTS_DIR=$OUT/$name timeout "$to" "$@" >"$OUT/$name.log" 2>&1; local rc=$?
  say "END   $name rc=$rc  $(grep -h '^SUMMARY' "$OUT/$name.log" | tail -1)"
  cleanup
  gate || { say "ABORT: stack did not recover after $name; queue stopped, see $OUT"; exit 3; }
}

say "campaign start  host=$(hostname)  out=$OUT  dry=$DRY_RUN  H7_SECS=$H7_SECS  D11_HOURS=$D11_HOURS  url=$BASE_URL"
gate || { say "ABORT: stack not healthy at start"; exit 3; }

# ---- step 0: configuration snapshot, notes, H11 first reading
if [ "$DRY_RUN" != 1 ]; then
  {
    echo "== $(date -u +%FT%TZ) $(hostname)"; uname -a; grep PRETTY /etc/os-release; cat /proc/device-tree/model 2>/dev/null | tr -d '\0'; echo
    docker --version; docker compose version; free -m; cat /proc/swaps; awk '$1=="memory"' /proc/cgroups; df -h /
    echo "== images"; docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedSince}}'
    echo "== containers"; docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
    echo "== API paths in the running backend"
    docker exec clarion-pi-backend-1 python -c "import logging; logging.disable(50); from app.main import app; print(len(app.openapi()['paths']))" 2>/dev/null
    echo "== throttle $(vcgencmd get_throttled 2>/dev/null)  temp $(vcgencmd measure_temp 2>/dev/null)"
  } >"$OUT/config.txt" 2>&1
  cat >"$OUT/not-run.txt" <<EOF
Deliberately not run in this campaign, and why:
 D5  power cut           needs POWER_CYCLE_CMD (a smart plug); never guessed
 D8  restore drill       needs a restic repository and the backup sandbox
 D9  kernel panic        --panic needs the watchdog configured (hardening not applied: baseline) and someone present to power-cycle
 N12 offline NFC (phone) manual: airplane mode, scan a tag
 RN4/RN5/RN8             UI race / 15 min token expiry / true half-open sockets: need a browser, hardware or time not available here
 A2 IDOR, A5 upload, A8 SSRF   need ids / endpoints supplied by hand (SEC_FOREIGN_PATIENT_ID, SEC_UPLOAD, SEC_SSRF)
 T7  origin IP           needs the Pi's public address (ORIGIN_IP)
 fail2ban / watchdog / log rotation: not installed or applied (this is the baseline configuration)
EOF
fi
step h11-first 300 "$HERE/hw_stress.sh" "${DRYARG[@]}" H11

# ---- 1. non-destructive
step speed          1500 env TAG=base RUNS=3 TUNNEL_SECS=60 "$HERE/speedtest_baseline.sh" "${DRYARG[@]}"
if [ "$DRY_RUN" = 1 ]; then say "DRY: sec / races / rn wrappers not run in dry mode"; else
  step sec           14400 env SEC_OUT="$OUT/sec" "$HERE/run_sec_pi.sh"
  say "cooldown 150 s (the A3 burst trips the login limiter)"; sleep 150
  step race-live      3600 "$HERE/run_live.sh" races
  step rn-live        7200 "$HERE/run_live.sh" rn
fi
step net-N1-N7      5400 "$HERE/net_scenarios.sh" "${DRYARG[@]}"
step hw-safe        7200 env CURL_EXTRA="$ORIGIN_RESOLVE" "$HERE/hw_stress.sh" "${DRYARG[@]}" H1 H3 H4 H6 H8 H9 H12
step hw-H2          3600 env CURL_EXTRA="$ORIGIN_RESOLVE" "$HERE/hw_stress.sh" "${DRYARG[@]}" H2
step hw-H7          $(( H7_SECS + 3600 )) env CURL_EXTRA="$ORIGIN_RESOLVE" "$HERE/hw_stress.sh" "${DRYARG[@]}" H7
step dur-D11        $(( D11_HOURS * 3600 + 3600 )) "$HERE/durability.sh" "${DRYARG[@]}" "--hours=$D11_HOURS" D11

# ---- 2. destructive (the stack is rebuilt by the gate between steps)
step net-disruptive 3600 "$HERE/net_scenarios.sh" "${DRYARG[@]}" --disruptive N8 N9 N10 N11
step hw-risky       5400 env CURL_EXTRA="$ORIGIN_RESOLVE" "$HERE/hw_stress.sh" "${DRYARG[@]}" --i-know-this-kills H5 H10 H13
step dur-destructive 5400 "$HERE/durability.sh" "${DRYARG[@]}" --destructive D1 D2 D3 D6 D12
step dur-D7-D9-D10  3600 "$HERE/durability.sh" "${DRYARG[@]}" --gen-logs D7 D9 D10
step h11-second      600 "$HERE/hw_stress.sh" "${DRYARG[@]}" H11     # >= 24 h after the first reading; before the reboot resets the counter

# ---- 3. cold boot last
say "snapshot + reboot for D4"
if [ "$DRY_RUN" = 1 ]; then
  say "DRY: would install /etc/cron.d/clarion-campaign and run durability.sh --destructive D4"; say "campaign end (dry)"; exit 0
fi
cat >/etc/cron.d/clarion-campaign <<EOF
@reboot root cd $HERE && BASE_URL=$BASE_URL PROBE_GAP=1.1 RESULTS_DIR=$OUT/D4-verify ./verify_after_boot.sh >$OUT/D4-verify.log 2>&1; echo "\$(date -u +\\%FT\\%TZ) D4 verify finished rc=\$?" >>$LOG; rm -f /etc/cron.d/clarion-campaign; touch $OUT/DONE
EOF
chmod 644 /etc/cron.d/clarion-campaign
RESULTS_DIR=$OUT/dur-D4 "$HERE/durability.sh" --destructive D4 >"$OUT/dur-D4.log" 2>&1
say "reboot issued"; sleep 120
