#!/usr/bin/env bash
# pull_when_done.sh - runs on the LAPTOP. Polls the Pi until the rerun is finished, pulls the whole campaign folder into
# qa/result/final/2026-11-13/evidence/clean-pi/campaign and regenerates the matrix, STATUS.md, FAILURES.md and the SVGs. Survives the Pi's reboot.
set -u
PI=pi@192.168.1.7; REMOTE=CLARION_CENTRAL/qa/stress/pi/results/campaign-20261112-180523
RES=$(cd "$(dirname "$0")/../../result/final/2026-11-13" && pwd)
for _ in $(seq 1 1200); do        # up to ~10 h at 30 s
  ssh -o ConnectTimeout=8 -o BatchMode=yes $PI "test -e $REMOTE/RERUN_DONE" 2>/dev/null && break
  sleep 30
done
ssh -o ConnectTimeout=8 $PI "test -e $REMOTE/RERUN_DONE" 2>/dev/null || { echo "timed out before RERUN_DONE"; exit 1; }
rm -rf "$RES/evidence/clean-pi/campaign.new" && scp -rq $PI:$REMOTE "$RES/evidence/clean-pi/campaign.new" 2>/dev/null \
  && rm -rf "$RES/evidence/clean-pi/campaign" && mv "$RES/evidence/clean-pi/campaign.new" "$RES/evidence/clean-pi/campaign" || { echo "pull failed"; exit 2; }
cd "$RES/tools" && python build_matrix.py | grep "clean  Pi" && python build_failures.py
echo PULLED_AND_REBUILT
