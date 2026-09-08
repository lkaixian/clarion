#!/bin/bash
# CLARION -- MariaDB least-privilege accounts (roadmap P1.3).
#
# Runs once, from the mariadb image's /docker-entrypoint-initdb.d/ hook, on
# first container init (empty datadir). Idempotent anyway (CREATE USER IF NOT
# EXISTS + ALTER USER ... IDENTIFIED BY), so re-running by hand is safe.
#
# Three accounts, mapped to the three things that touch the DB:
#   clarion_app     -- the running FastAPI app. DML only, NO DDL. This is the
#                      account DATABASE_URL points at in production.
#   clarion_migrate -- deploy-time only: runs `alembic upgrade head`. Full
#                      rights on the clarion schema (needs DDL).
#   clarion_report  -- read-only. Reporting queries + future integrations.
#
# NOTE (P2.9): audit_logs is meant to be append-only for clarion_app
# (INSERT/SELECT, no UPDATE/DELETE). MariaDB has no partial_revokes, so a
# subtractive `REVOKE UPDATE, DELETE ON clarion.audit_logs` errors (ERROR
# 1147) -- the table doesn't exist yet at init time either. DELIVERED in
# migration b2d7e4a9c1f6 as BEFORE UPDATE / BEFORE DELETE triggers on
# audit_logs (alongside the hash chain) -- enforced regardless of grants,
# for every account including root. Retention is therefore a DDL job
# (clarion_migrate drops sealed partitions), never a DELETE. See
# docs/deployment.md "Audit hash chain".
set -euo pipefail

for v in MARIADB_ROOT_PASSWORD MARIADB_APP_PASSWORD MARIADB_MIGRATE_PASSWORD MARIADB_REPORT_PASSWORD; do
    if [ -z "${!v:-}" ]; then
        echo "10-accounts.sh: $v must be set" >&2
        exit 1
    fi
done

db="${MARIADB_DATABASE:-clarion}"

# MAX_USER_CONNECTIONS caps: clarion_app covers 4 workers x (pool_size 10 +
# max_overflow 30) = 160; a connection leak in the app can then never starve
# clarion_migrate / clarion_report / root out of the 200-slot server ceiling.
mariadb -u root -p"${MARIADB_ROOT_PASSWORD}" <<SQL
CREATE USER IF NOT EXISTS 'clarion_app'@'%'     IDENTIFIED BY '${MARIADB_APP_PASSWORD}';
ALTER  USER              'clarion_app'@'%'     IDENTIFIED BY '${MARIADB_APP_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON \`${db}\`.* TO 'clarion_app'@'%' WITH MAX_USER_CONNECTIONS 160;

CREATE USER IF NOT EXISTS 'clarion_migrate'@'%' IDENTIFIED BY '${MARIADB_MIGRATE_PASSWORD}';
ALTER  USER              'clarion_migrate'@'%' IDENTIFIED BY '${MARIADB_MIGRATE_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${db}\`.* TO 'clarion_migrate'@'%';

CREATE USER IF NOT EXISTS 'clarion_report'@'%'  IDENTIFIED BY '${MARIADB_REPORT_PASSWORD}';
ALTER  USER              'clarion_report'@'%'  IDENTIFIED BY '${MARIADB_REPORT_PASSWORD}';
GRANT SELECT ON \`${db}\`.* TO 'clarion_report'@'%' WITH MAX_USER_CONNECTIONS 20;
SQL

echo "10-accounts.sh: clarion_app / clarion_migrate / clarion_report created on \`${db}\`"
