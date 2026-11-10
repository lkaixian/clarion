#!/usr/bin/env bash
# netem.sh - tc netem shaping with a dead-man switch (spec section A).
#   netem.sh [--ns CONTAINER] [--dry-run] <iface> "<netem args>"
#   netem.sh [--ns CONTAINER] [--dry-run] <iface> off
# env: DEADMAN=600  seconds until shaping is removed automatically (must be > 0, always armed)
#      DIR=both     both | in (client->Pi, via ifb0) | out (Pi->client)
# --ns shapes eth0-style <iface> inside the container's network namespace (host SSH untouched).
set -euo pipefail
. "$(dirname "$0")/lib.sh"

DEADMAN=${DEADMAN:-600}
DIR=${DIR:-both}
NS="" ARGS=()
while (( $# )); do
  case $1 in
    --ns) NS=${2:?--ns needs a container name}; shift 2 ;;
    --dry-run) shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
IF=${ARGS[0]:-} SPEC=${ARGS[1]:-}
[ -n "$IF" ] && [ -n "$SPEC" ] || die 'usage: netem.sh [--ns CONTAINER] [--dry-run] <iface> "<netem args>" | off'
[[ $DEADMAN =~ ^[1-9][0-9]*$ ]] || die "DEADMAN must be a positive number of seconds (never shape without it)"
case $DIR in both | in | out) ;; *) die "DIR must be both|in|out" ;; esac
need_root; need_tools tc ip
[ -z "$NS" ] || need_tools nsenter docker

PID=0
if [ -n "$NS" ] && [ "$DRY_RUN" != 1 ]; then
  PID=$(docker inspect -f '{{.State.Pid}}' "$NS")
  [ "$PID" -gt 0 ] || die "container $NS is not running"
fi
# T CMD... : run in the container netns when --ns, else on the host
T() { if [ -n "$NS" ]; then run nsenter -t "$PID" -n "$@"; else run "$@"; fi; }

PIDF=/run/netem-${NS:-host}-$IF.deadman

disarm() {
  [ -f "$PIDF" ] || return 0
  # the dead-man itself must not kill itself before it has cleaned up
  [ -n "${NETEM_DEADMAN_RUN:-}" ] || kill -- "-$(cat "$PIDF")" 2>/dev/null || true
  rm -f "$PIDF"
}
arm() {
  disarm
  if [ "$DRY_RUN" = 1 ]; then echo "DRY: dead-man ${DEADMAN}s -> netem.sh ${NS:+--ns $NS }$IF off"; return 0; fi
  # shellcheck disable=SC2016
  NETEM_DEADMAN_RUN=1 setsid bash -c 'sleep "$1"; shift; exec "$@"' _ "$DEADMAN" \
    bash "$0" ${NS:+--ns "$NS"} "$IF" off </dev/null >/dev/null 2>&1 &
  echo $! >"$PIDF"
  echo "dead-man armed: shaping on $IF removed automatically in ${DEADMAN}s"
}

if [ "$SPEC" = off ]; then
  T tc qdisc del dev "$IF" root 2>/dev/null || true
  T tc qdisc del dev "$IF" ingress 2>/dev/null || true
  T tc qdisc del dev ifb0 root 2>/dev/null || true
  disarm
  echo "netem off on ${NS:-host}:$IF"
  exit 0
fi

read -r -a NETEM <<<"$SPEC"
arm   # armed BEFORE anything is shaped
run modprobe ifb numifbs=0 2>/dev/null || true
T ip link add ifb0 type ifb 2>/dev/null || true
T ip link set ifb0 up
if [ "$DIR" != in ]; then
  T tc qdisc replace dev "$IF" root netem "${NETEM[@]}"                      # egress  (Pi -> client)
fi
if [ "$DIR" != out ]; then
  T tc qdisc replace dev "$IF" handle ffff: ingress
  T tc filter replace dev "$IF" parent ffff: protocol all u32 match u32 0 0 \
    action mirred egress redirect dev ifb0                                    # ingress (client -> Pi)
  T tc qdisc replace dev ifb0 root netem "${NETEM[@]}"
fi
[ "$DRY_RUN" = 1 ] || T tc qdisc show dev "$IF"
