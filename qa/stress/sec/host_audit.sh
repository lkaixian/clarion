#!/usr/bin/env bash
# A9/A10/A11 (+ A12 file perms): host hardening review. Run ON the Pi (Ubuntu 22.04) as root:
#   sudo REPO=/opt/clarion SSH_TARGET=pi@192.168.1.50 ./host_audit.sh
# Env: REPO (default: repo containing this script), COMPOSE (default docker-compose.pi.yml),
#      SSH_TARGET (user@host to probe password-auth refusal from THIS machine; skipped if unset),
#      SKIP_TRIVY=1 / SKIP_LYNIS=1 (slow on a Pi). Nothing here writes outside $SEC_OUT.
# No brute force is attempted (hydra against your own sshd belongs in a lab, not in a default run);
# A9 is judged from sshd config + fail2ban state instead.
set -u
REPO="${REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}"
COMPOSE="${COMPOSE:-docker-compose.pi.yml}"
OUT="${SEC_OUT:-$(dirname "$0")/results}"; mkdir -p "$OUT"
fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails+1)); }
warn() { echo "WARN $*"; }
skip() { echo "SKIP $*"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "== A10 sshd effective config =="
if have sshd && [ "$(id -u)" = 0 ]; then
  cfg="$(sshd -T 2>/dev/null)"
  v() { echo "$cfg" | awk -v k="$1" '$1==k{print $2; exit}'; }
  [ "$(v permitrootlogin)" = no ] && pass "A10 permitrootlogin no" || fail "A10 permitrootlogin=$(v permitrootlogin)"
  [ "$(v passwordauthentication)" = no ] && pass "A10 passwordauthentication no" || fail "A10 passwordauthentication=$(v passwordauthentication)"
  [ "$(v kbdinteractiveauthentication)" = no ] && pass "A10 kbdinteractiveauthentication no" || fail "A10 kbdinteractiveauthentication=$(v kbdinteractiveauthentication)"
  [ "$(v pubkeyauthentication)" = yes ] && pass "A10 pubkeyauthentication yes" || fail "A10 pubkeyauthentication=$(v pubkeyauthentication)"
  [ "$(v permitemptypasswords)" = no ] && pass "A10 permitemptypasswords no" || fail "A10 permitemptypasswords=$(v permitemptypasswords)"
  mt="$(v maxauthtries)"; [ "${mt:-6}" -le 4 ] && pass "A10 maxauthtries $mt" || warn "A10 maxauthtries=${mt:-6} (suggest <= 4)"
else skip "sshd -T needs root and openssh-server"; fi

if [ -n "${SSH_TARGET:-}" ]; then
  echo "== A10 remote probe from this machine =="
  o="$(ssh -o BatchMode=yes -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ConnectTimeout=8 \
        -o StrictHostKeyChecking=accept-new "$SSH_TARGET" true 2>&1)"
  echo "$o" | grep -qi 'permission denied (publickey' && pass "A10 password auth refused (publickey only)" \
    || { echo "$o" | grep -qi 'permission denied' && warn "A10 denied but password method offered: $o" || warn "A10 inconclusive: $o"; }
  ro="$(ssh -o BatchMode=yes -o ConnectTimeout=8 "root@${SSH_TARGET#*@}" true 2>&1)"
  echo "$ro" | grep -qi 'permission denied' && pass "A10 root login refused" || fail "A10 root login not refused: $ro"
fi

echo "== A9 fail2ban =="
if have fail2ban-client && [ "$(id -u)" = 0 ]; then
  st="$(fail2ban-client status sshd 2>&1)"; echo "$st"
  echo "$st" | grep -q 'Currently banned\|Status for the jail' && pass "A9 sshd jail active" || fail "A9 sshd jail not active"
  mr="$(fail2ban-client get sshd maxretry 2>/dev/null)"; bt="$(fail2ban-client get sshd bantime 2>/dev/null)"
  [ -n "$mr" ] && { [ "$mr" -le 5 ] && pass "A9 maxretry=$mr bantime=$bt" || warn "A9 maxretry=$mr (suggest <= 5)"; }
else fail "A9 fail2ban not installed/running (apt install fail2ban)"; fi

echo "== A11 image scan (trivy) =="
if [ "${SKIP_TRIVY:-0}" = 1 ]; then skip "trivy (SKIP_TRIVY)"
elif have trivy; then
  imgs="$(grep -E '^\s+image:' "$REPO/$COMPOSE" | awk '{print $2}' | sort -u)"
  for i in $imgs; do
    case "$i" in *:local) i="${i}";; esac
    j="$OUT/trivy-$(echo "$i" | tr '/:' '__').json"
    if trivy image --quiet --severity CRITICAL --ignore-unfixed --format json -o "$j" "$i" >/dev/null 2>&1; then
      n=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(sum(len(r.get("Vulnerabilities") or []) for r in d.get("Results",[])))' "$j" 2>/dev/null || echo ?)
      [ "$n" = 0 ] && pass "A11 $i no fixable CRITICAL" || fail "A11 $i has $n fixable CRITICAL ($j)"
    else warn "A11 could not scan $i (image not present locally? run docker compose build/pull)"; fi
  done
  trivy fs --quiet --severity CRITICAL --ignore-unfixed --exit-code 1 "$REPO/backend" >/dev/null 2>&1 \
    && pass "A11 trivy fs backend/ clean" || fail "A11 trivy fs backend/ has CRITICAL findings"
else skip "trivy not installed (https://aquasecurity.github.io/trivy)"; fi

echo "== A11 dependency audits =="
if have pip-audit; then
  pip-audit -r "$REPO/backend/requirements.txt" --progress-spinner off >"$OUT/pip-audit.txt" 2>&1 \
    && pass "A11 pip-audit clean" || fail "A11 pip-audit findings (see $OUT/pip-audit.txt)"
else skip "pip-audit not installed (pipx install pip-audit)"; fi
if have npm && [ -f "$REPO/web/package-lock.json" ]; then
  (cd "$REPO/web" && npm audit --omit=dev --audit-level=high >"$OUT/npm-audit.txt" 2>&1) \
    && pass "A11 npm audit (prod deps, >= high) clean" || fail "A11 npm audit findings (see $OUT/npm-audit.txt)"
else skip "npm audit (no npm or lockfile)"; fi

echo "== A11 lynis =="
if [ "${SKIP_LYNIS:-0}" = 1 ]; then skip "lynis (SKIP_LYNIS)"
elif have lynis && [ "$(id -u)" = 0 ]; then
  lynis audit system --quick --no-colors >"$OUT/lynis.txt" 2>&1
  grep -E 'Hardening index|Warnings \(|Suggestions \(' "$OUT/lynis.txt" | sed 's/^/INFO /'
  hi=$(grep -o 'Hardening index : [0-9]*' "$OUT/lynis.txt" | grep -o '[0-9]*$')
  [ -n "${hi:-}" ] && { [ "$hi" -ge 65 ] && pass "A11 lynis hardening index $hi" || warn "A11 lynis hardening index $hi (< 65)"; }
else skip "lynis needs root + install (apt install lynis)"; fi

echo "== A12 secret file permissions =="
found=0
while IFS= read -r f; do
  found=1
  m=$(stat -c '%a' "$f"); o=$(stat -c '%U' "$f")
  [ "$m" = 600 ] || [ "$m" = 400 ] && pass "A12 $f mode $m owner $o" || fail "A12 $f mode $m (want 0600) owner $o"
done < <(find "$REPO" -maxdepth 2 \( -name '.env' -o -name '.env.*' \) ! -name '*.example' -type f 2>/dev/null; \
         find "$REPO/proxy/certs" "$REPO/backend/db/mariadb/encryption" -type f \( -name '*.key' -o -name '*keyfile*' -o -name '*.pem' \) 2>/dev/null)
[ "$found" = 0 ] && skip "A12 no .env* files under $REPO"
git -C "$REPO" ls-files --error-unmatch .env .env.docker .env.tunnel >/dev/null 2>&1 && fail "A12 a real .env file is tracked by git" || pass "A12 no real .env file tracked by git"

echo "host_audit: $fails FAIL"
exit $((fails > 0))
