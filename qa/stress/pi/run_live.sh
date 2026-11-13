#!/usr/bin/env bash
# run_live.sh [races|rn] - the live race suites from the Pi.
#   races : test_races_live.py against the public URL (R1, R2, R4, R8-R11)
#   rn    : test_degraded_network.py (RN1-RN10) through Toxiproxy placed in front of Caddy. Cloudflare needs the real hostname
#           for TLS, so during this step only $HOST is mapped to 127.0.0.1 (removed again on exit) and Toxiproxy forwards to Caddy.
set -u
. "$(dirname "$0")/campaign_env.sh"
OUT=${RESULTS_DIR:?set RESULTS_DIR}; mkdir -p "$OUT"
export ADMIN_EMAIL=admin@clarion.demo ADMIN_PASSWORD=admin123 VERIFY_TLS=0
# Admin is an MFA role on the production build: the TOTP secret (from py/enrol_totp.py) lives in a root-only file, not in the repo.
[ -r /etc/clarion-qa/admin_totp ] && export ADMIN_TOTP_SECRET=$(sed -n 's/^SECRET=//p' /etc/clarion-qa/admin_totp)
cd "$REPO_C/qa/stress/py"
case ${1:-races} in
  races)
    BASE_URL=$BASE_URL/api "$VENV/bin/python" -m pytest -q -rxXs test_races_live.py --junitxml="$OUT/races-live.xml" ;;
  rn)
    docker rm -f toxiproxy >/dev/null 2>&1
    docker run -d --name toxiproxy --network clarion-pi_app -p 8474:8474 -p 18080:18080 -p 443:443 ghcr.io/shopify/toxiproxy:latest >/dev/null || exit 3
    trap 'docker rm -f toxiproxy >/dev/null 2>&1; sed -i "/ campaign-rn\$/d" /etc/hosts' EXIT
    echo "127.0.0.1 $HOST # campaign-rn" >> /etc/hosts
    for i in $(seq 1 20); do curl -s -m 2 http://localhost:8474/version >/dev/null && break; sleep 1; done
    # $HOST now points at 127.0.0.1, so the suite's ordinary client needs something on :443: a toxic-free passthrough to Caddy.
    curl -s -X POST localhost:8474/proxies -d '{"name":"direct","listen":"0.0.0.0:443","upstream":"proxy:443","enabled":true}' >/dev/null
    export TOXIPROXY_URL=http://localhost:8474 TOXIPROXY_UPSTREAM_HOST=proxy TOXIPROXY_CLIENT_HOST=$HOST
    BASE_URL=https://$HOST/api "$VENV/bin/python" -m pytest -q -rxXs test_degraded_network.py --junitxml="$OUT/rn-live.xml" ;;
  *) echo "usage: run_live.sh races|rn"; exit 2 ;;
esac
