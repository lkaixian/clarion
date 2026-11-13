#!/usr/bin/env bash
# campaign_env.sh - sourced by the campaign wrappers (Clean Prod Pi). One place for host, URLs, logins and secrets.
# shellcheck disable=SC2034
CAMPAIGN_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_C=$(cd "$CAMPAIGN_DIR/../../.." && pwd)

export PROBE_GAP=${PROBE_GAP:-1.1}                       # the app allows 60 req/min per IP
export HOST=${CAMPAIGN_HOST:-clarion-testnet.larmkx.com}
export BASE_URL=https://$HOST                             # public path through Cloudflare
export ORIGIN_RESOLVE="--resolve $HOST:443:172.29.0.2"    # straight to Caddy (pinned address in the compose file)
export NS_CONTAINER=${NS_CONTAINER:-clarion-pi-cloudflared-1}
export LOGIN_USER=receptionist@clarion.demo LOGIN_PASS=receptionist123    # demo-seeded, low privilege, no MFA
export VENV=${VENV:-/home/pi/qa-venv}                     # sudo may change HOME, so absolute

env_get() { grep -E "^$1=" "$REPO_C/.env.docker" 2>/dev/null | head -1 | cut -d= -f2-; }
export PAYMENTS_WEBHOOK_SECRET=$(env_get PAYMENTS_WEBHOOK_SECRET)
export MARIADB_APP_PASSWORD=$(env_get MARIADB_APP_PASSWORD) MARIADB_DATABASE=$(env_get MARIADB_DATABASE)
