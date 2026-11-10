#!/usr/bin/env bash
# CK2/CK3/CK4: capture traffic on the Pi during a scripted login and grep the capture for leaks.
#   sudo BASE_URL=https://clarion.example.com SEC_USER=u SEC_PASS=p ./sniff_cookies.sh
# Ubuntu 22.04:  sudo apt install tcpdump tshark   (tshark optional, only for the TLS-bytes sanity line)
# Captures: (1) host NIC on :80/:443  (2) docker bridge of the compose network (cloudflared<->Caddy<->backend).
# The bridge hop Caddy->backend is plaintext by design (isolated network); hits there are REPORTED as
# "residual" (CK4), hits on the host NIC are FAIL (CK3).
set -u
: "${BASE_URL:?}"; : "${SEC_USER:?}"; : "${SEC_PASS:?}"
NET="${COMPOSE_NET:-clarion-pi_app}"
IF_HOST="${IF_HOST:-$(ip route show default | awk '{print $5; exit}')}"
BR="$(docker network inspect "$NET" -f '{{.Id}}' 2>/dev/null | cut -c1-12)"; BR="${BR:+br-$BR}"
OUT="${SEC_OUT:-$(dirname "$0")/results}/sniff-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$OUT"
API="${API_PREFIX:-/api}"
[ "$(id -u)" = 0 ] || { echo "run as root (tcpdump)"; exit 2; }

tcpdump -i "$IF_HOST" -s 0 -U -w "$OUT/host.pcap" '(tcp port 80 or tcp port 443)' 2>/dev/null & P1=$!
if [ -n "$BR" ]; then tcpdump -i "$BR" -s 0 -U -w "$OUT/bridge.pcap" 2>/dev/null & P2=$!; fi
sleep 2

# scripted traffic: https login (cookie jar), refresh, logout, plus plaintext attempts that must only redirect
J="$OUT/jar.txt"
HEADERS="$OUT/https-login.hdr"
curl -sS -D "$HEADERS" -c "$J" -o "$OUT/login.json" -d "username=$SEC_USER" --data-urlencode "password=$SEC_PASS" "$BASE_URL$API/auth/login" >/dev/null
curl -sS -b "$J" -c "$J" -X POST -o /dev/null "$BASE_URL$API/auth/refresh"
ACCESS="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("access_token",""))' "$OUT/login.json" 2>/dev/null)"
REFRESH="$(awk '/clarion_refresh_token/{print $7}' "$J" | tail -1)"
curl -sS -H "Authorization: Bearer $ACCESS" -o /dev/null "$BASE_URL$API/auth/me"
curl -sS -m 8 -o /dev/null -D "$OUT/http-redirect.hdr" "http://${BASE_URL#*://}/" || true
curl -sS -m 8 -o /dev/null -d "username=$SEC_USER" --data-urlencode "password=$SEC_PASS" "http://${BASE_URL#*://}$API/auth/login" || true
curl -sS -b "$J" -X POST -o /dev/null "$BASE_URL$API/auth/logout"
sleep 2; kill $P1 ${P2:-} 2>/dev/null; wait 2>/dev/null

fail=0
scan() {  # $1 pcap  $2 label  $3 severity(FAIL|NOTE)
  [ -s "$1" ] || { echo "SKIP $2: no capture"; return; }
  tcpdump -nn -A -r "$1" 2>/dev/null > "$1.txt"
  local hits=0
  for pat in "clarion_refresh_token" "Set-Cookie" "Authorization: Bearer" "access_token" "eyJ[A-Za-z0-9_-]\{10,\}" \
             "[0-9]\{6\}-[0-9]\{2\}-[0-9]\{4\}" "$SEC_PASS" ${REFRESH:+"$REFRESH"}; do
    n=$(grep -c -- "$pat" "$1.txt" 2>/dev/null); n=${n:-0}
    if [ "$n" -gt 0 ]; then echo "$3 $2: pattern '${pat:0:24}' x$n"; hits=$((hits+n)); fi
  done
  if [ "$hits" -eq 0 ]; then echo "PASS $2: no cookie/token/NRIC/password in plaintext"; fi
  [ "$3" = FAIL ] && [ "$hits" -gt 0 ] && fail=1
  return 0
}
scan "$OUT/host.pcap"   "host NIC :80/:443 (CK3)" FAIL
scan "$OUT/bridge.pcap" "docker bridge $BR (CK4 residual hop)" NOTE
# Port 80 must only have carried redirects: any Set-Cookie in plaintext HTTP response headers = FAIL (CK2)
if grep -qi '^set-cookie' "$OUT/http-redirect.hdr" 2>/dev/null; then echo "FAIL CK2 Set-Cookie on plaintext redirect"; fail=1; else echo "PASS CK2 plaintext redirect has no Set-Cookie"; fi
grep -qi 'HTTP/.* 30[1278]' "$OUT/http-redirect.hdr" 2>/dev/null && echo "PASS CK2 http:// answered with a redirect" || echo "NOTE CK2 http:// did not redirect (port closed?)"
grep -qi '^cache-control:.*no-store' "$HEADERS" && echo "PASS CK11 login Cache-Control no-store" || echo "FAIL CK11 login lacks Cache-Control: no-store"
echo "pcaps + text dumps in $OUT"
exit $fail

# ------------------------------------------------------------------------------------------------
# CK5 HSTS downgrade (manual, LAN test rig, NEVER against other people's traffic)
# 1. Rig: a laptop as gateway/AP for ONE test client you own; install mitmproxy (pip install mitmproxy).
# 2. Transparent mode (Linux gateway):
#      sudo sysctl -w net.ipv4.ip_forward=1
#      sudo iptables -t nat -A PREROUTING -i wlan0 -p tcp --dport 80  -j REDIRECT --to-port 8080
#      mitmproxy --mode transparent --showhost -s strip_https.py     # or: mitmweb --mode transparent
#    (strip_https.py: rewrite 'https://' -> 'http://' in Location headers / HTML and drop Secure from
#     Set-Cookie; ~15 lines of mitmproxy addon API: def response(flow): ...)
# 3. First visit, fresh browser profile, type the bare hostname (so it starts on http://): record whether the
#    page can be stripped. With max-age=300 the pin lapses after 5 minutes - wait 6 min, repeat: stripping works
#    again. With max-age=31536000 a returning browser upgrades internally and mitmproxy sees only TLS.
#    NOTE: behind Cloudflare, enable "Always Use HTTPS" + HSTS at Cloudflare too; first-visit exposure
#    remains unless the domain is on the preload list (a deliberate, near-irreversible choice; not set).
# 4. Cleanup: sudo iptables -t nat -F PREROUTING; sudo sysctl -w net.ipv4.ip_forward=0
# ------------------------------------------------------------------------------------------------
