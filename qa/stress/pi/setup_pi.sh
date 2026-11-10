#!/usr/bin/env bash
# setup_pi.sh - prepare Ubuntu 22.04 arm64 (Raspberry Pi 4) for the stress suite. Idempotent.
#   setup_pi.sh            print everything it WOULD do (nothing is changed)
#   setup_pi.sh --apply    do it
# Installs tools via apt; writes drop-ins for watchdog, journald cap, docker log rotation + live-restore.
# An existing /etc/docker/daemon.json is never overwritten: the suggested file is printed instead.
set -euo pipefail

APPLY=0
for a in "$@"; do
  case $a in --apply) APPLY=1 ;; --dry-run) ;; *) echo "unknown arg $a" >&2; exit 2 ;; esac
done

PKGS="stress-ng fio sysstat iproute2 nmap tcpdump curl util-linux iptables slowhttptest mmc-utils smartmontools libraspberrypi-bin"
BOOT_CFG=/boot/firmware/config.txt
JOURNALD_MAX=200M

# act CMD... : run with --apply, otherwise only print
act() { if [ "$APPLY" = 1 ]; then "$@"; else echo "DRY: $*"; fi; }

# put_file PATH <<EOF ... : write only if content differs (idempotent); print under dry run
put_file() {
  local dest=$1 tmp
  tmp=$(mktemp); cat >"$tmp"
  if [ -f "$dest" ] && cmp -s "$tmp" "$dest"; then echo "ok (unchanged): $dest"; rm -f "$tmp"; return 0; fi
  if [ "$APPLY" = 1 ]; then mkdir -p "$(dirname "$dest")"; install -m 0644 "$tmp" "$dest"; echo "wrote $dest"
  else echo "DRY: would write $dest:"; sed 's/^/    /' "$tmp"; fi
  rm -f "$tmp"
}

[ "$APPLY" = 0 ] || [ "$(id -u)" -eq 0 ] || { echo "ERROR: --apply needs root" >&2; exit 2; }

echo "== packages"
if [ "$APPLY" = 1 ]; then
  apt-get update -qq
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends $PKGS || echo "WARN: some packages unavailable on this release; the scripts name any tool they miss"
else
  echo "DRY: apt-get update && apt-get install -y --no-install-recommends $PKGS"
fi
echo "   (locust for LOCUST=1 probes: pip install locust, on the load generator, off the Pi)"

echo "== hardware watchdog (D9)"
if grep -qs '^dtparam=watchdog=on' "$BOOT_CFG"; then echo "ok: dtparam=watchdog=on already in $BOOT_CFG"
elif [ "$APPLY" = 1 ] && [ -f "$BOOT_CFG" ]; then echo 'dtparam=watchdog=on' >>"$BOOT_CFG"; echo "appended dtparam=watchdog=on to $BOOT_CFG (reboot to take effect)"
else echo "DRY: append 'dtparam=watchdog=on' to $BOOT_CFG"; fi
put_file /etc/systemd/system.conf.d/10-clarion-watchdog.conf <<'EOF'
[Manager]
RuntimeWatchdogSec=15
RebootWatchdogSec=2min
EOF

echo "== journald cap (D10)"
put_file /etc/systemd/journald.conf.d/10-clarion.conf <<EOF
[Journal]
SystemMaxUse=$JOURNALD_MAX
EOF

echo "== docker log rotation + live-restore (D3, D10)"
DJ=/etc/docker/daemon.json
DJ_WANT='{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}'
# shellcheck disable=SC2001
if [ -f "$DJ" ]; then
  if cmp -s <(echo "$DJ_WANT") "$DJ"; then echo "ok (unchanged): $DJ"
  else echo "SUGGEST: $DJ exists, not touched. Merge these keys by hand:"; echo "$DJ_WANT" | sed 's/^/    /'; fi
else
  echo "$DJ_WANT" | put_file "$DJ"
fi

echo "== apply changes"
act systemctl daemon-reload
act systemctl restart systemd-journald
echo "NOTE: log-opts apply to NEW containers: after 'systemctl reload docker', recreate the stack"
echo "      (docker compose -f docker-compose.pi.yml up -d --force-recreate). Reboot once for the watchdog."
echo "NOTE: set vm.swappiness low and use zram, not SD/eMMC swap, if H4 shows swap thrash."
