#!/bin/bash
# CLARION -- generate the MariaDB data-at-rest encryption key material
# (roadmap P2.7). Run ONCE per deployment, before the first `docker compose
# up` of the mariadb service. Output goes to backend/db/mariadb/encryption/
# which is git-ignored and mounted read-only into the container at
# /etc/mysql/encryption/.
#
#   bash backend/db/mariadb/generate-encryption-key.sh
#
# Produces:
#   encryption/keyfile   -- one line "1;<64 hex chars>" (a 256-bit AES key),
#                           mode 0400. Key id 1 is the active key.
#
# The file_key_management plugin reads this directly (encryption.cnf points
# file_key_management_filename at it). It sits on a LUKS-encrypted volume
# and is 0400 root-only.
#
# HARDENING (production, not the demo): encrypt this keyfile itself and pass
# the file-key via file_key_management_filekey -- see
# https://mariadb.com/kb/en/file-key-management-encryption-plugin/ -- or
# move to MariaDB Enterprise for Vault / KMIP. The encryption.cnf comments
# and encryption/README.md cover the switch.
#
# BACK THIS FILE UP SEPARATELY FROM THE DATABASE. Losing it makes the data
# unrecoverable, and keeping it in the same backup stream defeats the point.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/encryption"
mkdir -p "$DIR"

if [ -e "$DIR/keyfile" ]; then
    echo "refusing to overwrite existing key material at $DIR/keyfile" >&2
    echo "(rotating? add a line '2;<new 64 hex>' by hand -- see encryption/README.md)" >&2
    exit 1
fi

umask 077
printf '1;%s\n' "$(openssl rand -hex 32)" > "$DIR/keyfile"
chmod 0400 "$DIR/keyfile"

echo "wrote $DIR/keyfile (mode 0400)"
echo "next: docker compose --env-file .env.docker up -d mariadb"
echo "      (first start runs the background sweep over existing tablespaces)"
echo "verify: docker compose exec mariadb mariadb -uroot -p -e \"SHOW STATUS LIKE 'Innodb_encryption%'\""
