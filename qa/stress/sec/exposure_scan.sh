#!/usr/bin/env bash
# T4/T5: port exposure + internal segmentation. Run ON the Pi (sudo) for the host/docker parts;
# the nmap part can be run from any other machine:  TARGET=<pi ip> ./exposure_scan.sh nmap
#   sudo ./exposure_scan.sh            -> local review (ss, docker ps, DOCKER-USER, netshoot) + nmap on $TARGET if set
# Env: TARGET (ip for nmap), NET (default clarion-pi_app), COMPOSE (default docker-compose.pi.yml),
#      EXPECT_OPEN="22" (tcp ports allowed to be open from outside), ALLOW_FLAT_NET=1 (downgrade the flat-network
#      FAILs to WARN: docker-compose.pi.yml puts everything on ONE network, so T5 fails by design today).
# Non-destructive: connect scans, banner-less probes, a PING to redis, anonymous HTTP GET to minio.
set -u
NET="${NET:-clarion-pi_app}"; COMPOSE="${COMPOSE:-docker-compose.pi.yml}"
EXPECT_OPEN="${EXPECT_OPEN:-22}"
SENSITIVE="3306 9000 9001 6379 2575 8000 8100 8080 8042 4242"
fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails+1)); }
warn() { echo "WARN $*"; }
flat() { if [ "${ALLOW_FLAT_NET:-0}" = 1 ]; then warn "$*"; else fail "$*"; fi; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---- T4a: nmap from outside ----
nmap_scan() {
  have nmap || { warn "nmap not installed (apt install nmap)"; return; }
  [ -n "${TARGET:-}" ] || { warn "TARGET not set; skipping nmap"; return; }
  echo "== nmap TCP all ports on $TARGET =="
  open=$(nmap -Pn -sT -p- --min-rate 1000 -oG - "$TARGET" 2>/dev/null | grep -o '[0-9]*/open/tcp' | cut -d/ -f1 | sort -n)
  for p in $open; do
    if echo " $EXPECT_OPEN " | grep -q " $p "; then pass "tcp/$p open (expected)"
    elif echo " $SENSITIVE " | grep -q " $p "; then fail "T4 tcp/$p reachable from scanner (sensitive)"
    else warn "tcp/$p open (not in EXPECT_OPEN)"; fi
  done
  [ -z "$open" ] && pass "no open tcp ports"
  echo "== nmap UDP top 100 (needs root) =="
  if [ "$(id -u)" = 0 ]; then
    nmap -Pn -sU --top-ports 100 -oG - "$TARGET" 2>/dev/null | grep -o '[0-9]*/open/udp' | while read -r l; do warn "udp/${l%%/*} open"; done
  else warn "UDP scan needs root"; fi
}
[ "${1:-}" = nmap ] && { nmap_scan; exit $fails; }

# ---- T4b: host listeners ----
echo "== ss -tlnp =="
ss -tlnp 2>/dev/null
ss -H -tln 2>/dev/null | awk '{print $4}' | while read -r a; do
  port="${a##*:}"; ip="${a%:*}"
  echo " $SENSITIVE " | grep -q " $port " || continue
  case "$ip" in 127.*|"[::1]") ;; *) echo "FAIL T4 $a listens on a non-loopback address (sensitive port)";; esac
done > /tmp/sec_ss.$$; cat /tmp/sec_ss.$$; grep -q '^FAIL' /tmp/sec_ss.$$ && fails=$((fails+1)) || pass "T4 sensitive ports are loopback/private only on host (review CENTRAL_BIND_IP: $(printenv CENTRAL_BIND_IP || echo 'unset=127.0.0.1'))"
rm -f /tmp/sec_ss.$$

# ---- T4c: docker published ports ----
if have docker; then
  echo "== docker ps =="
  docker ps --format '{{.Names}}\t{{.Ports}}'
  while IFS=$'\t' read -r n ports; do
    for m in $(echo "$ports" | tr ',' '\n' | grep -o '0\.0\.0\.0:[0-9]*->[0-9]*\|\[::\]:[0-9]*->[0-9]*'); do
      hp="${m%%->*}"; hp="${hp##*:}"
      if echo " $SENSITIVE " | grep -q " $hp "; then fail "T4 $n publishes $hp on ALL interfaces"; else warn "$n publishes $hp on all interfaces"; fi
    done
  done < <(docker ps --format '{{.Names}}\t{{.Ports}}')

  # ---- T4d: DOCKER-USER (Docker bypasses ufw) ----
  if [ "$(id -u)" = 0 ] && have iptables; then
    du=$(iptables -S DOCKER-USER 2>&1)
    echo "$du"
    echo "$du" | grep -Eq -- '-j (DROP|REJECT)' && pass "T4 DOCKER-USER has a DROP/REJECT rule" \
      || fail "T4 DOCKER-USER has no DROP/REJECT rule: published ports bypass ufw (add: iptables -I DOCKER-USER -i eth0 ! -s <lan> -j DROP)"
  else warn "iptables check needs root"; fi

  # ---- T5: segmentation, from a throwaway container on the compose network ----
  echo "== T5 in-network reachability (netshoot on $NET) =="
  if docker network inspect "$NET" >/dev/null 2>&1; then
    reach() {  # name host port
      docker run --rm --network "$NET" nicolaka/netshoot nc -z -w 3 "$2" "$3" >/dev/null 2>&1
    }
    # intended: the network's front door
    reach proxy proxy 443 && pass "T5 proxy:443 reachable (intended)" || warn "proxy:443 not reachable"
    for t in mariadb:3306 redis:6379 minio:9000 mpi:8100 backend:8000; do
      if reach x "${t%%:*}" "${t##*:}"; then
        flat "T5 ${t} reachable from a generic container on '$NET' (web/cloudflared share this network; split edge/internal)"
      else pass "T5 ${t} not reachable"; fi
    done
    # redis auth: a bare PING answered with +PONG = no requirepass
    r=$(docker run --rm --network "$NET" nicolaka/netshoot sh -c "printf 'PING\r\n' | nc -w 3 redis 6379" 2>/dev/null | tr -d '\r')
    case "$r" in *PONG*) fail "T5 redis answers PING unauthenticated (set --requirepass)";; *NOAUTH*|*DENIED*) pass "T5 redis requires auth";; *) warn "redis PING inconclusive: '$r'";; esac
    # minio anonymous
    code=$(docker run --rm --network "$NET" nicolaka/netshoot curl -s -o /dev/null -w '%{http_code}' -m 5 http://minio:9000/ 2>/dev/null)
    code_b=$(docker run --rm --network "$NET" nicolaka/netshoot curl -s -o /dev/null -w '%{http_code}' -m 5 http://minio:9000/clarion-documents/ 2>/dev/null)
    case "$code_b" in 200) fail "T5 minio lists a bucket anonymously ($code_b)";; 000) warn "minio unreachable";; *) pass "T5 minio anonymous bucket access refused ($code_b)";; esac
    # mariadb: default / blank credentials must be refused (docker exec, no secrets needed)
    db=$(docker ps --format '{{.Names}}' | grep -E 'mariadb' | head -1)
    if [ -n "$db" ]; then
      cli=$(docker exec "$db" sh -c 'command -v mariadb || command -v mysql')
      for cred in "-uroot" "-uroot -pchange-me-root" "-uclarion_app -pchange-me-app" "-uclarion_migrate -pchange-me-migrate" "-u anonymous"; do
        # shellcheck disable=SC2086
        if docker exec "$db" $cli $cred -e 'select 1' >/dev/null 2>&1; then fail "T5 mariadb accepted '$cred'"; else pass "T5 mariadb refused '$cred'"; fi
      done
    else warn "no mariadb container found"; fi
  else warn "docker network $NET not found (set NET; 'docker network ls')"; fi
else
  warn "docker not available"
fi
nmap_scan
echo "exposure_scan: $fails FAIL"
exit $((fails > 0))
