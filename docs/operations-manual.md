# CLARION — Operations Manual

Tender clause **7.1(a)**. Day-2 running of a live CLARION deployment: starting
and stopping the stack, routine checks, account/access administration,
monitoring, and incident response. This is the index a shift operator or IT
administrator works from — the deep technical detail for every item below
lives in `docs/deployment.md` (1000+ lines, organised the same way) and is
linked rather than repeated here.

See also: [Programming Manual](programming-manual.md) (for developers),
[Maintenance Manual](maintenance-manual.md) (scheduled upkeep), the
[Backup & DR runbook](../backend/backup/README.md) (incident recovery), and
`healthcare/Compliance Matrix.md` for which tender clause each feature meets.

## 1. Starting / stopping the stack

```bash
docker compose --env-file .env.docker up -d              # core: proxy, web, backend, redis, orthanc(+pg), minio
docker compose --env-file .env.docker --profile mariadb up -d      # + MariaDB (production DB, P1.3/P2.7)
docker compose --env-file .env.docker --profile backup up -d       # + scheduled backups (P2.8)
docker compose --env-file .env.docker --profile observability up -d # + Prometheus/Grafana/Loki/Alertmanager (P5.1)
docker compose down                                       # stop (add -v only to wipe volumes — destroys data)
```

Full service list, ports, and volumes: `docs/deployment.md` § Services. First
boot on a fresh DB runs Alembic migrations automatically
(`_ensure_schema()` — SQLite auto-upgrades; MariaDB must already be
stamped/migrated, see § 3).

> [!note] `docker compose` validates every service's required (`${VAR:?...}`)
> env vars at parse time for **any** invocation, regardless of which
> `--profile` flags you pass — found while validating P5.3's new
> `branch-edge` profile, when a plain `docker compose config` failed on the
> unrelated, profile-gated `GRAFANA_ADMIN_PASSWORD` (P5.1/`observability`,
> still `:?` — a real admin password deliberately has no guessable
> default). Fill in every `:?`-required var in `.env.docker` from
> `.env.docker.example` before first boot, even for profiles you don't plan
> to enable — `docker-compose.yml`'s own new `branch-edge` profile uses `:-`
> instead for exactly this reason.

## 2. Daily checks

| Check | How | Healthy |
|---|---|---|
| Stack is up | `docker compose ps` | all services `Up`/`healthy` |
| App reachable | `curl -k https://<host>/healthz` | `{"status":"ok"}` — checks DB + object store live |
| Ready for traffic | `curl -k https://<host>/readyz` | `200` |
| Backup ran | tail `/backup/status.jsonl` (see [DR runbook](../backend/backup/README.md)) | latest line `"result":"ok"`, binlog line < 45 min old |
| No open security/data-quality alerts | Grafana dashboard, or `GET /admin/security-alerts` / `GET /admin/data-quality-alerts` (admin token) | none unacknowledged > 24h |
| Disk headroom | Grafana "disk-full" panel or `df -h` on the data volume | < 75% (Prometheus alert fires at 75%/90%, see `docs/deployment.md` § Observability) |
| Cert validity | `openssl x509 -enddate -noout -in proxy/certs/<cert>` | > 30 days remaining |

`GET /metrics` (Prometheus format, admin-network only — proxied at
`/api/metrics` but blocked at the edge, see `docs/deployment.md` §
Observability) has per-route latency/error counts if a dashboard isn't handy.

## 3. Account & access administration

- **Local accounts**: `Admin` role → Access Control tab (web console) or
  `POST/PUT/DELETE /admin/users`. Role set: `admin`, `clinician`,
  `records_officer`, `receptionist`, `pharmacist`, `patient`,
  `emergency_responder`. Per-facility role→page matrix under the same tab
  (`healthcare` memory: `role-page-permissions`).
- **LDAP/AD-backed accounts** (P1.10): configure `LDAP_*` env vars per
  `docs/deployment.md` § LDAP; role is resolved from AD group membership via
  `Admin → LDAP Role Mappings` (`GET/POST/PUT/DELETE
  /admin/ldap-role-mappings`) — mappings are scoped to the admin's own
  facility, cannot be set cross-tenant.
- **Password reset (staff)**: Admin → Users → Reset Password issues a
  temp password, forces change on next login.
- **Locked-out account** (too many failed logins): `Admin → Users` shows
  `reset_locked_until`; clears automatically after the lockout window, or an
  admin can zero it directly via the same endpoint used for password reset.
- **Break-glass cross-facility patient search** (emergency access to a
  patient not registered at this facility) is logged and flagged in the
  audit trail — see `docs/deployment.md` § Audit hash chain.

## 4. Monitoring & alerting (P5.1)

Grafana (`:3000` on the `observability` profile) ships two dashboards
(request/error rates, DB/object-store health). Prometheus alert rules fire to
Alertmanager → email (SMTP configured in `.env.docker`; WhatsApp was
deliberately not wired — no real Meta/Twilio account for this demo, see
`healthcare/Implementation Roadmap.md`'s P5.1 entry). Full wiring detail:
`docs/deployment.md` § Observability.

Two more always-on detectors, no dashboard needed — check via their admin
endpoints:
- **Access-anomaly detection** (P4.5): `GET /admin/security-alerts` —
  fan-out (≥20 distinct patients/hour by one actor) and off-hours access
  (00:00–05:00 MYT). Each alert can be asked for a plain-language
  explanation: `POST /admin/security-alerts/{id}/explain`.
- **Data-quality monitoring** (P2.12, the tender): `GET
  /admin/data-quality-alerts` — missing values, duplicate patients,
  inconsistent coding.

## 5. Common incidents

| Symptom | First move | Reference |
|---|---|---|
| Site down / 502 at the edge | `docker compose logs proxy` then `web`/`backend` | `docs/deployment.md` § Troubleshooting |
| DB unreachable | `/readyz` will 503; check `mariadb` container health, connection count vs `max_user_connections` | `docs/deployment.md` § Services |
| Redis down | Rate limiting **fails open** (in-memory fallback, fixed P5.2) — `/healthz`/`/auth/login` stay up; restart `redis`, no data loss (cache-only) | `healthcare/Implementation Roadmap.md` P5.2 entry |
| Object store (MinIO) down | Uploads/thumbnails fail; existing files stay served from cache where possible | `docs/deployment.md` § Data / persistence |
| Suspected data loss / corruption | **Stop writes**, do not run migrations, go straight to the DR runbook | [`backend/backup/README.md`](../backend/backup/README.md) |
| Suspected breach / anomalous access | Check `/admin/security-alerts`, pull the audit hash-chain for the affected patient (`verify_audit_chain.py`), preserve logs before acting | `docs/deployment.md` § Audit hash chain |
| PACS/DICOM viewer errors | Check Orthanc container + its Postgres index; `docs/deployment.md` § PACS/DICOM | — |
| Lab analyser not delivering results | Check `hl7-listener` service logs (its own process, not a gunicorn worker) | `docs/deployment.md` § Lab-analyser HL7 v2 |
| Branch campus WAN cut | Staff on-site run `db/emergency_export_appliance.py query` against the last nightly export for critical patient info until the link is back | `docs/deployment.md` § Two-campus rollout |

Escalation / DR coordinator contacts: fill in per deployment in
`backend/backup/README.md`'s contacts table (same table serves both).

## 6. Deploying an update

Never skip the pre-update gate:

```bash
docker compose --profile backup run --rm backup "./pre-update-snapshot.sh '<what you are changing>'"
# then: alembic upgrade / image bump / config change
python -m db.check_schema --url "<staging-url>"    # schema gate before touching prod
```

Rollback = restore the pre-update backup, or `alembic downgrade <recorded
target>` + redeploy the previous images — see `backend/backup/README.md` §
Pre-update gate.
