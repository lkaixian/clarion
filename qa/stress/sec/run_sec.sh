#!/usr/bin/env bash
# Orchestrator. Remote (any machine):   BASE_URL=https://host SEC_USER=.. SEC_PASS=.. ./run_sec.sh
# On the Pi additionally:               sudo -E ./run_sec.sh --host     (adds sniff, exposure, host audit)
# Writes results/<timestamp>/ (junit xml, logs, csv). Exit 1 if any stage failed.
set -u
cd "$(dirname "$0")"
: "${BASE_URL:?set BASE_URL}"
export SEC_OUT="${SEC_OUT:-$PWD/results/$(date +%Y%m%d-%H%M%S)}"; mkdir -p "$SEC_OUT"
rc=0
stage() { local n="$1"; shift; echo "=== $n ==="; "$@" >"$SEC_OUT/$n.log" 2>&1; local s=$?; tail -n 25 "$SEC_OUT/$n.log"; echo "--- $n exit $s"; [ $s -ne 0 ] && rc=1; return 0; }
PY="${PYTHON:-python3}"; $PY -c 'import httpx,pytest' 2>/dev/null || { echo "need: pip install httpx pytest"; exit 2; }

stage cookies   $PY -m pytest -q -rxXs --junitxml="$SEC_OUT/cookies.xml"   test_cookies.py
stage transport $PY -m pytest -q -rxXs --junitxml="$SEC_OUT/transport.xml" test_transport_headers.py
stage tls       bash tls_audit.sh "${BASE_URL#*://}"
# Burst test (A3) trips the login limiter for ~1 min and runs last on purpose: SEC_RUN_BURST=1 to include it.
stage app       $PY -m pytest -q -rxXs --junitxml="$SEC_OUT/app.xml"       test_app_attack.py
if [ "${1:-}" = "--host" ]; then
  stage sniff    bash sniff_cookies.sh
  stage exposure bash exposure_scan.sh
  stage host     bash host_audit.sh
fi
echo; echo "FAIL/PASS lines:"; grep -h '^FAIL' "$SEC_OUT"/*.log | sort | uniq -c | head -50
echo "results: $SEC_OUT  (overall: $([ $rc = 0 ] && echo PASS || echo FAIL))"
exit $rc
