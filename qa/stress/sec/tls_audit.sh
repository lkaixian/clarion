#!/usr/bin/env bash
# T1: wrap testssl.sh and fail on weak protocols / ciphers. Usage: tls_audit.sh HOST[:PORT]
# Note: behind Cloudflare this audits Cloudflare's edge policy (min TLS version is a dashboard setting),
# not Caddy. To audit Caddy itself, point it at the origin: tls_audit.sh ORIGIN_IP:443 (needs the port reachable).
set -u
T="${1:?usage: tls_audit.sh HOST[:PORT]}"; [[ "$T" == *:* ]] || T="$T:443"
OUT="${SEC_OUT:-$(dirname "$0")/results}"; mkdir -p "$OUT"; J="$OUT/testssl.json"; rm -f "$J"
BIN="$(command -v testssl.sh || command -v testssl || true)"
[ -n "$BIN" ] || { echo "SKIP testssl.sh not installed (git clone --depth 1 https://github.com/drwetter/testssl.sh)"; exit 0; }
"$BIN" --quiet --warnings off --severity MEDIUM --jsonfile "$J" "$T" >"$OUT/testssl.txt" 2>&1
[ -s "$J" ] || { echo "FAIL testssl produced no JSON (see $OUT/testssl.txt)"; exit 1; }
python3 - "$J" <<'EOF'
import json, sys
rows = json.load(open(sys.argv[1]))
bad = []
for r in rows:
    i, f, s = r.get("id", ""), r.get("finding", ""), r.get("severity", "")
    if i in ("SSLv2", "SSLv3", "TLS1", "TLS1_1") and f.startswith("offered"):
        bad.append(f"protocol {i} offered")
    elif s in ("MEDIUM", "HIGH", "CRITICAL") and i not in ("scanTime", "overall_grade"):
        bad.append(f"{s} {i}: {f[:90]}")
    elif i.startswith("cipher") and any(w in f for w in ("RC4", "3DES", "NULL", "EXP", "anon", "-CBC-SHA ")) and s not in ("OK", "INFO"):
        bad.append(f"weak cipher {f[:90]}")
for b in bad: print("FAIL", b)
print("PASS no weak protocols/ciphers" if not bad else f"{len(bad)} finding(s)")
sys.exit(1 if bad else 0)
EOF
