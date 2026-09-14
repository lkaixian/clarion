#!/bin/sh
# CLARION -- MinIO least-privilege accounts (roadmap: MinIO IAM pass,
# 2026-09-14 -- follow-up from the voltagent review that flagged every
# service sharing the MinIO root key). Same shape as
# backend/db/mariadb/10-accounts.sh (P1.3): one scoped account per thing
# that touches the store, run from a one-shot init container (docker-
# compose.yml's `minio-init` service) rather than baked into an image --
# MinIO, unlike the mariadb image, has no /docker-entrypoint-initdb.d/
# equivalent that only fires on first boot.
#
#   clarion-backend -- the running FastAPI app (ObjectStore, app/storage.py).
#                      s3:* on clarion-* only -- it legitimately needs to
#                      create buckets, set versioning/retention and do every
#                      object op across all 7 buckets, but never MinIO's own
#                      admin API (no user/policy management, no server
#                      config) the way the root key it used to hold could.
#   clarion-orthanc -- s3:* scoped to ONLY clarion-dicom. Orthanc's S3
#                      storage plugin never creates the bucket itself
#                      (backend's ObjectStore bootstrap does, at its own
#                      startup -- see docs/deployment.md's ordering note)
#                      and has no business touching any other bucket.
#   clarion-backup  -- read-only (GetObject/ListBucket/GetBucketLocation) on
#                      the 6 buckets backup.sh's do_objectstore() mirrors
#                      (clarion-derived excluded there too -- regenerable).
#
# Idempotent best-effort: `mc admin policy create` overwrites an existing
# policy of the same name; `mc admin user add` on an existing user resets
# its password rather than erroring, on the mc/MinIO versions this was
# written against. `mc admin policy attach` is NOT idempotent the same way
# -- unlike the deprecated single-policy `policy set`, `attach` is the
# multi-policy command and errors ("already in effect"/"already attached")
# on a policy the user already holds, which would otherwise kill this
# script (set -e) on every `docker compose up` after the first and,
# because backend/orthanc/backup all gate on minio-init completing, wedge
# the whole stack from ever restarting. attach_policy() below tolerates
# exactly that one error class and still aborts on anything else (a typo,
# a permission problem). Not verified against a live server this session
# (no Docker daemon running) -- same verification ceiling as this
# session's other compose-only-validated infra changes.
set -eu

for v in MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_BACKEND_PASSWORD MINIO_ORTHANC_PASSWORD MINIO_BACKUP_PASSWORD; do
    eval "val=\${$v:-}"
    if [ -z "$val" ]; then
        echo "10-accounts.sh: $v must be set" >&2
        exit 1
    fi
done

mc alias set clarion-minio "${MINIO_ENDPOINT:-http://minio:9000}" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

for name in clarion-backend clarion-orthanc clarion-backup; do
    mc admin policy create clarion-minio "$name" "/policies/${name}.json"
done

attach_policy() {
    # $1=user $2=policy -- see the idempotency note above.
    out=$(mc admin policy attach clarion-minio "$2" --user "$1" 2>&1) && { [ -n "$out" ] && echo "$out"; return 0; }
    if printf '%s' "$out" | grep -qi "already"; then
        echo "10-accounts.sh: $2 already attached to $1 (ok)"
        return 0
    fi
    echo "$out" >&2
    return 1
}

mc admin user add clarion-minio clarion-backend "$MINIO_BACKEND_PASSWORD"
attach_policy clarion-backend clarion-backend

mc admin user add clarion-minio clarion-orthanc "$MINIO_ORTHANC_PASSWORD"
attach_policy clarion-orthanc clarion-orthanc

mc admin user add clarion-minio clarion-backup "$MINIO_BACKUP_PASSWORD"
attach_policy clarion-backup clarion-backup

echo "10-accounts.sh: clarion-backend / clarion-orthanc / clarion-backup provisioned on MinIO"
