---
title: On-Prem Architecture
type: architecture
updated: 2026-08-30
tags: [architecture, mariadb, minio, backup, deployment, on-prem]
---

# On-Prem Architecture — University HealthCare

Right-sized for a two-campus university clinic (~23k users, ~150 encounters/day),
hosted on campus-provided VMs. Described in **stack-neutral tiers** so the mandated
[[Designing for the PHP Port|CI4 rewrite]] replaces only the app + worker containers;
DB, object store, PACS, proxy, backup all carry over.

Full text: `scratchpad/architecture.md`.

## Tiers
`reverse proxy → app → worker → DB → object store → PACS → cache → auth`

## Database — MariaDB 11.4 LTS + Alembic
- InnoDB, `utf8mb4`, TLS-only, binlog ROW (for point-in-time recovery).
- **Encryption at rest (P2.7):** InnoDB + Aria TDE (`innodb_encrypt_tables=FORCE`),
  `innodb_encrypt_log`, `encrypt_binlog`, `encrypt_tmp_files` — keys via the
  Community `file_key_management` plugin (0400 keyfile on the LUKS volume;
  `backend/db/mariadb/encryption.cnf` + `generate-encryption-key.sh`). Enterprise
  Server buys Vault / KMIP key management with no schema change. LUKS FDE of the
  data LUN sits underneath (physical-theft layer). ~3–10% overhead.
- **Three least-privilege accounts:** `clarion_app` (DML only; `UPDATE`/`DELETE`
  revoked on `audit_logs`), `clarion_migrate` (DDL, deploy-time only), `clarion_report`
  (read-only for reporting + integrations).
- **Alembic now:** add a `MetaData` naming convention → generate a reviewed baseline →
  `stamp head` → **delete `_migrate_lightweight()` + `create_all()`**. The Alembic
  history survives the CI4 port as the schema spec.
- **Volumes (10 yr):** MariaDB total only **~15–40 GB** (encounters ~400k,
  observations ~3–4M, audit ~8–10M — partition monthly by year from day one). The real
  growth is **imaging: 2–4 TB in the object store**. No sharding; one optional async
  replica for DR/reporting.
- **Pooling:** SQLAlchemy `pool_size=10, max_overflow=10, pool_pre_ping=True,
  pool_recycle=1800`; 4 uvicorn workers ⇒ ≤ 80 conns; `max_connections=200`.

### SQLite-isms in `models.py` that break on MariaDB (12)
1. **Every `Column(String)` has no length** — fatal for indexed/unique/PK `VARCHAR`.
   Add explicit lengths (`String(36)` UUIDs, `String(255)` general).
2. `RoomClaim`'s two `sqlite_where=` **partial unique indexes** — unsupported. Replace
   with a virtual generated column (`IF(released_at IS NULL, room_id, NULL)`) + plain
   `UniqueConstraint`.
3. Raw `CREATE ... IF NOT EXISTS ... WHERE` in `main.py` — SQLite syntax; disappears
   when the migration runner is deleted.
4. `check_same_thread` connect-arg — remove, replace with pool args.
5. Date-as-string columns (`date_of_birth`, `diagnosed_at`, `start_date`) — portable
   but lose `DATE` semantics.
6. Naive `datetime.utcnow` → `DATETIME(6)` + tz-aware UTC.
7. `JSON` columns OK but **never a server-side JSON default** (MariaDB forbids it;
   current Python-side defaults are fine).
8. ORM `cascade` with no DB `ondelete=` + SQLite never enforced FKs — InnoDB will;
   needs orphan pre-check + seed insert ordering.
9. Case-insensitive `LIKE` behaviour shifts with collation.
10. UUID PKs = a portability win (no AUTOINCREMENT reconciliation); consider `BIGINT`
    surrogates on new high-volume tables.
11. `Boolean` → `TINYINT(1)` fine.
12. Decide `server_default=func.now()` for `created_at` so CI4 inherits it.

### Indexes to add
`encounters(patient_id, started_at)`, `audit_logs(patient_id, timestamp)` +
`(actor, timestamp)`, appointment/condition/medication patient composites,
`(code_system, code)` on every coded table, `observations(patient_id, code,
effective_at)`, FULLTEXT on `patients.full_name` and `clinical_documents.raw_text`.

## Object / image / DICOM storage — MinIO
Single-node on-prem, chosen over a bare filesystem for S3-API parity, **bucket
versioning**, **object-lock / WORM**, lifecycle (ILM), encryption, presigned URLs.
- **Do first:** an `ObjectStore` abstraction (`put/get/presign_get/delete/set_retention`);
  convert every `*_path` column → `*_object_key` + `sha256` + `bytes` + `mime`.
- **Buckets:** `clarion-documents` (WORM 7 yr), `clarion-signatures`, `clarion-medicine`,
  `clarion-derived` (thumbnails — *excluded from backup*, 30-day expiry),
  `clarion-scratch` (OCR/NRIC photos, **7-day expiry**), `clarion-dicom` (COMPLIANCE
  lock, 7 yr), `clarion-reports-archive` (WORM).
- **Hot/cold** = two MinIO storage classes on different disks + lifecycle transitions.
  **No HSM/tape/erasure-coding** — wrong scale for a clinic.
- **Image normalisation**: worker uses Pillow (already a dep) to
  strip EXIF, auto-orient, cap long edge 2500 px, progressive JPEG q82, 300 px thumb.
- **PACS:** Orthanc 1.12 container, PostgreSQL index, S3 plugin → `clarion-dicom`.
  Detail in [[PACS and DICOM]].

## FHIR-compatible schema
See [[FHIR Schema Readiness]].

## Deployment topology
- **One central stack at Main Campus; Branch over the University WAN** with a light edge proxy
  + Redis for static/SPA. The code already scopes everything per `facility_name`, so
  "two branches" is data partitioning, not two deployments. Degradation plan: a nightly
  encrypted **offline emergency-export appliance** (the `critical_for_emergency` subset)
  for WAN cuts.
- **VMs:** VM-APP (proxy, app gunicorn×4 / PHP-FPM, worker, redis — 4 vCPU / 8 GB) +
  VM-DATA (the "dedicated DB server" per the tender — mariadb, minio, orthanc,
  orthanc-postgres, backup, exporters — 8 vCPU / 24–32 GB + 2–4 TB growable LUKS
  volume) + optional VM-EDGE-BRANCH + VM-BACKUP (separate host — restic / registry /
  Gitea, 4–8 TB). Single-VM fallback for the pilot via the same Compose file.
  OS: Debian 12 or Rocky 9.
- **Containers:** Docker Engine 27 + Compose v2 (or Podman 5). **Offline delivery** =
  digest-pinned images as a `docker save` tarball or a private `registry:2` / Harbor
  on VM-BACKUP — nothing pulled from the internet. Docker secrets for
  `SECRET_KEY` / `OTP_HMAC_KEY` / DB / MinIO / LDAP / TLS. Three networks (`edge`,
  `data`, `observability`); only the proxy publishes 443.
- **Reverse proxy:** Caddy 2.8 (or nginx 1.27), **TLS from the University internal CA**,
  HTTP→HTTPS, HSTS, **CSP set here** (the app deliberately defers it), and a runtime
  `config.js` injecting the API base so the hard-coded `localhost` dies with no rebuild.
- **LDAP/AD:** see [[Integration Engine and LDAP]].

## Backup and DR
- **RPO** ≤ 1 h clinical (15-min binlog shipping, published as 1 h), ≤ 24 h object
  store. **RTO** ≤ 4 h full system, ≤ 1 h app-tier-only. ≥ 30-day rolling retention all
  tiers; **7-year WORM archive** for records / audit / imaging.
- **MariaDB:** weekly `mariadb-backup` full + daily `--incremental` + `mydumper`
  logical + binlog `rsync` every 15 min.
- **Object store:** MinIO versioning / object-lock + `mc mirror` / `restic`.
- **Orthanc:** `pg_dump` + WAL archiving, consistent with the DICOM bucket snapshot.
- Everything encrypted with `age` / GPG, landing in a **`restic`** repo on VM-BACKUP
  (`--keep-daily 30 --keep-weekly 12 --keep-monthly 84 --keep-yearly 7`, weekly
  `restic check`), plus a **monthly rotated offline disk** in a different building (3-2-1).
- **Pre-update full system image** is a hard pipeline gate: fresh DB
  backup + hypervisor snapshot + recorded Alembic `downgrade` target + previous image
  digests before any change.
- **Quarterly restore test** on VM-BACKUP's sandbox: restore full + incremental +
  binlog replay, bring up the stack, run a smoke suite, reconcile row counts /
  checksums, file a **signed test report** with the University. DR runbook ships in the
  Maintenance manual.

## Observability & ops
- **Structured logging:** JSON formatter, request-ID middleware binding
  `request_id` / `user_id` / `role` / `facility`; never log PHI / OTP / token / raw
  NRIC OCR. stdout → Promtail → Loki (30–90 day retention, on-prem).
- **Audit tamper-evidence:** grant `INSERT,SELECT` only on `audit_logs`; add
  `prev_hash` + `row_hash` **SHA-256 hash chain** (BEFORE INSERT trigger); **daily
  seal** writes the chain head + row count to `clarion-reports-archive` (WORM) + emails
  University ICT; 24-month hot in monthly partitions, then signed-Parquet export to 7-year
  WORM + `DROP PARTITION`. This is the substrate the tender's AI
  anomaly / audit-intelligence consumers need.
- **Health/metrics:** `/healthz` (liveness) + `/readyz` (MariaDB `SELECT 1`, MinIO
  HEAD, Redis PING, Orthanc `/system`); `prometheus-fastapi-instrumentator` +
  `mysqld-exporter` + `node-exporter` (**disk-full on the object volume is the #1 risk**
  — alert 75/90%); Grafana (doubles as a data source for the Dashboard module);
  Alertmanager → email + WhatsApp.
- **Offline CI:** Gitea + Gitea Actions / Woodpecker on VM-BACKUP against a local
  `devpi` mirror; per-PR: ruff / mypy → pytest (ephemeral MariaDB; prioritise
  auth / RBAC / cross-facility immutability / FHIR façade) → **SAST bandit + semgrep
  OWASP/ASVS** (covers + the deterministic core of the tender) → pip-audit +
  trivy → `alembic upgrade head` then `downgrade base` (rollback guarantee) →
  digest-pinned image + syft SBOM.

## Effort
**~110–150 person-days** to productionise the Python system to this target —
**excludes** the CI4 rewrite and the AI-engine workstream. The CI4 port reuses the
schema, Alembic history, MinIO buckets / object-key columns, Orthanc, proxy / TLS /
Compose topology, backup stack, `ldap_role_map`, role/page-permission model and FHIR
mapping spec — re-implementing only handlers, ORM layer, FHIR serialisers and worker jobs.

## Migration sequencing (19 steps)
See `scratchpad/architecture.md` §7 for the ordered, tender-mapped, effort-sized list.
Summarised in [[Implementation Roadmap]].
