#!/bin/sh
# CLARION runtime config injector.
#
# Dropped into /docker-entrypoint.d/ by the Dockerfile. The official nginx
# image runs it (via /docker-entrypoint.sh) before `nginx -g 'daemon off;'`.
#
# It materialises a tiny /config.js from the $API_BASE env var so the same
# built image can be pointed at any backend without a rebuild:
#
#     window.__CLARION_API_BASE__ = "<API_BASE>";
#
# index.html loads this as a classic script ahead of the module bundle, and
# web/src/api/client.js reads window.__CLARION_API_BASE__ first (then
# VITE_API_BASE, then http://localhost:8000). Set $API_BASE to "/api" for the
# same-origin nginx proxy (no backend CORS needed), or to a full backend URL
# (e.g. the Cloudflare-tunnel origin) for a direct cross-origin call.
set -eu

: "${API_BASE:=}"

CONFIG_PATH="/usr/share/nginx/html/config.js"

# $API_BASE is interpolated raw into a JS double-quoted string literal below,
# so a value containing a quote, backslash, newline or "<" could break out
# and inject script that runs on every page load (and the app sends its
# bearer token to whatever host this resolves to). It is operator-set, not
# user input, but validate anyway: allow only an empty value, a root-relative
# path ("/api"), or an http(s) URL -- built from an unreserved character set
# (letters, digits and . _ - ~ : /). Anything else is dropped with a warning,
# so the SPA falls back to its safe localhost default rather than running
# injected code.
case "$API_BASE" in
    "" ) ;;
    *[!A-Za-z0-9._~:/-]* )
        echo "[clarion] WARNING: API_BASE has characters outside [A-Za-z0-9._~:/-] -- ignoring it" >&2
        API_BASE="" ;;
    /* | http://?* | https://?* ) ;;
    * )
        echo "[clarion] WARNING: API_BASE must be empty, '/'-rooted, or http(s):// -- ignoring '$API_BASE'" >&2
        API_BASE="" ;;
esac

cat > "$CONFIG_PATH" <<EOF
// Generated at container start by entrypoint.sh -- do not edit, do not cache.
window.__CLARION_API_BASE__ = "${API_BASE}";
EOF

echo "[clarion] wrote ${CONFIG_PATH} (API_BASE='${API_BASE}')"
