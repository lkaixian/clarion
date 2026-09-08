# MariaDB encryption key material (P2.7)

Holds the data-at-rest encryption key for the MariaDB service. **git-ignored**
(except this file); starts empty.

## Provision (once, before the first `docker compose up` of `mariadb`)

```
bash backend/db/mariadb/generate-encryption-key.sh
```

Writes `keyfile` — one line `1;<64 hex>` (a 256-bit AES key), mode `0400`.
`docker-compose.yml` mounts this directory read-only at
`/etc/mysql/encryption/`; `encryption.cnf` sets
`file_key_management_filename = /etc/mysql/encryption/keyfile`.

If the directory is empty when `mariadb` starts, the plugin fails to load
and the server won't come up — that is the intended "provision the key
first" gate.

## After first start

`innodb_encryption_threads` sweeps every existing tablespace. Confirm:

```
docker compose exec mariadb mariadb -uroot -p \
  -e "SHOW STATUS LIKE 'Innodb_encryption%'"
```

`Innodb_num_pages_encrypted` climbing then settling well above
`Innodb_num_pages_decrypted` means it worked.

## Rotate

Append a line `2;<new 64 hex>` to `keyfile`, point new writes at it
(`innodb_encryption_key_id = 2` or per-table), then force a re-encrypt:

```
SET GLOBAL innodb_encryption_rotate_key_age = 1;
-- wait for Innodb_encryption_rotation_pages_flushed to stop climbing
SET GLOBAL innodb_encryption_rotate_key_age = 86400;
```

Keep the old key line in `keyfile` until the rotation is complete.

## Back this up — SEPARATELY from the database

Losing `keyfile` = unrecoverable data. Keeping it in the same backup stream
as the DB defeats the point. Store it in the org secret manager / a sealed
envelope, not next to the `restic` repo. See `docs/deployment.md` →
"Encryption at rest".

## Hardening beyond the demo

- **Encrypt the keyfile itself** (verified against the MariaDB KB). Create a
  random file-key, encrypt `keyfile` with it (AES-256-**CBC**, the only mode
  MariaDB supports for this), then reference both:
  ```
  openssl rand -hex 128 > keyfile.key
  openssl enc -aes-256-cbc -md sha256 -pbkdf2 \
      -pass file:keyfile.key -in keyfile -out keyfile.enc   # MariaDB >= 12.0.1
  # MariaDB < 12.0.1: use `-md sha1` and no `-pbkdf2`
  ```
  then in `encryption.cnf`:
  `file_key_management_filename = /etc/mysql/encryption/keyfile.enc` +
  `file_key_management_filekey = FILE:/etc/mysql/encryption/keyfile.key`.
  See <https://mariadb.com/kb/en/file-key-management-encryption-plugin/>.
- **HSM / HashiCorp Vault / KMIP**: MariaDB **Enterprise Server** only — the
  schema and `innodb_encrypt_*` settings don't change, only the plugin lines.
