#!/usr/bin/env bash
# rerun_after_campaign.sh <campaign-out-dir>
# Waits for the campaign's DONE file (written after the D4 reboot check), then reruns the two live suites that were void
# (race-live: admin MFA; rn-live: Toxiproxy setup) into <out>/race-live-rerun and <out>/rn-live-rerun.
# Started twice on purpose (a waiter now + an @reboot cron entry, because D4 reboots the Pi); the mkdir lock lets only one run.
set -u
OUT=${1:?campaign out dir}; HERE=$(cd "$(dirname "$0")" && pwd)
exec >>"$OUT/rerun.log" 2>&1
say() { echo "$(date -u +%FT%TZ) $*"; }
for _ in $(seq 1 720); do [ -e "$OUT/DONE" ] && break; sleep 30; done
[ -e "$OUT/DONE" ] || { say "no DONE file after 6 h, rerun not started"; exit 1; }
mkdir "$OUT/RERUN_STARTED" 2>/dev/null || exit 0
rm -f /etc/cron.d/clarion-rerun
. "$HERE/campaign_env.sh"
say "campaign done; waiting for the site (max 10 min)"
for _ in $(seq 1 60); do curl -sk -m 5 -o /dev/null -w '%{http_code}' "$BASE_URL/api/healthz" | grep -q 200 && break; sleep 10; done
sleep 120
say "BEGIN race-live-rerun"; RESULTS_DIR=$OUT/race-live-rerun timeout 3600 "$HERE/run_live.sh" races >"$OUT/race-live-rerun.log" 2>&1; say "END race-live-rerun rc=$?"
say "cooldown 150 s (login limiter)"; sleep 150
say "BEGIN rn-live-rerun"; RESULTS_DIR=$OUT/rn-live-rerun timeout 7200 "$HERE/run_live.sh" rn >"$OUT/rn-live-rerun.log" 2>&1; say "END rn-live-rerun rc=$?"
touch "$OUT/RERUN_DONE"; say "rerun finished"
