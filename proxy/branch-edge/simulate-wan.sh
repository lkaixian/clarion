#!/usr/bin/env sh
# CLARION WAN-link simulator (P5.3 validation).
#
# There is no real second campus to test against in this environment, so
# this is the buildable half of "WAN validation": inject Branch-WAN-like
# latency/jitter/loss on the branch-proxy container's OWN interface using
# `tc netem` (iproute2 -- already present on the Debian/Rocky targets
# healthcare/On-Prem Architecture.md specifies, no new dependency), then
# re-run backend/loadtest's Locust suite (P5.2) against
# https://<branch-host>:${BRANCH_HTTPS_PORT:-8443} and confirm the app still
# behaves acceptably. See proxy/branch-edge/README.md for the full procedure
# and what "acceptably" means. This script only adds/removes the
# impairment; it does not run Locust itself.
#
# Usage:
#   ./simulate-wan.sh add [delay] [jitter] [loss%]   # default 40ms/10ms/0.5%
#   ./simulate-wan.sh clear
#   ./simulate-wan.sh show
#
# Requires: branch-proxy running with cap_add: NET_ADMIN (already set in
# docker-compose.yml's branch-edge profile) and `docker` on PATH here.
set -eu
CONTAINER="${BRANCH_PROXY_CONTAINER:-clarion-branch-proxy-1}"
IFACE="${WAN_IFACE:-eth0}"

case "${1:-}" in
  add)
    DELAY="${2:-40ms}"
    JITTER="${3:-10ms}"
    LOSS="${4:-0.5%}"
    docker exec "$CONTAINER" tc qdisc replace dev "$IFACE" root netem delay "$DELAY" "$JITTER" loss "$LOSS"
    echo "WAN simulated on $CONTAINER/$IFACE: delay=$DELAY jitter=$JITTER loss=$LOSS"
    ;;
  clear)
    docker exec "$CONTAINER" tc qdisc del dev "$IFACE" root 2>/dev/null || true
    echo "WAN simulation cleared on $CONTAINER/$IFACE"
    ;;
  show)
    docker exec "$CONTAINER" tc qdisc show dev "$IFACE"
    ;;
  *)
    echo "usage: $0 {add [delay] [jitter] [loss%]|clear|show}" >&2
    exit 2
    ;;
esac
