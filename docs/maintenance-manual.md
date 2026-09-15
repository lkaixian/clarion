# CLARION — Maintenance Manual

Tender clause **7.1(c)**. Scheduled/preventive upkeep, separate from the
[Operations Manual](operations-manual.md)'s day-to-day running and the
[Backup & DR runbook](../backend/backup/README.md)'s incident recovery.

## Maintenance schedule

| Interval | Task | How |
|---|---|---|
| Every 15 min | Binlog backup | automatic (`backup` service cron) |
| Nightly (per campus with an edge appliance) | Offline emergency-export refresh | `db/emergency_export_appliance.py build ...` (P5.3) — cron it alongside `backup.sh`; carry the new `.age` file to the appliance, don't leave the previous night's file as the only copy in transit |
| Daily (Mon–Sat) | Incremental DB + object-store backup | automatic |
| Weekly (Sun) | Full backup + prune + integrity check | automatic |
| Quarterly | Restore drill | automatic (`restore-test.sh`) — **file the signed report with the University**, the tender |
| Quarterly | Certificate expiry check | `openssl x509 -enddate -noout -in proxy/certs/<cert>`; renew if < 90 days left |
| Quarterly | Dependency audit | `pip list --outdated` (backend), `npm outdated` (web), `flutter pub outdated` (mobile); prioritise anything with a CVE |
| Quarterly | Review open security/data-quality alerts for false-positive tuning | `GET /admin/security-alerts`, `/admin/data-quality-alerts` — thresholds are hardcoded per tender wording (P4.5/P2.12), a threshold change is a code change + review, not a config toggle |
| Semi-annual | Re-verify LDAP TLS cert chain (`LDAP_CA_CERT_FILE`) | LDAP bind fails closed on an invalid cert (P1.10 H4) — rotate before AD's own cert rotates |
| Semi-annual | Re-run `db/check_schema.py` against a MariaDB clone of production | catches drift between `models.py` and the live schema before it becomes an incident |
| Annually | Rotate `SECRET_KEY` / `OTP_HMAC_KEY` / MinIO service-account keys | invalidates all outstanding JWTs — schedule for a maintenance window |
| Annually | Re-run the load test against current hardware/traffic | `backend/loadtest/README.md` — re-baseline capacity as usage grows toward the 23k-user target |
| On MinIO image update | Re-check upstream availability | Docker Hub `minio/minio` is dead (see `healthcare/Implementation Roadmap.md`'s MinIO note) — this stack is pinned to the `quay.io` mirror; don't blindly `docker compose pull` that service |

## Log & storage housekeeping

- **Object store**: `clarion-derived` (thumbnails/previews) has an ILM rule
  auto-expiring at 180 days — self-healing, nothing to do. Clinical-document
  and imaging buckets are WORM (object-lock + retention) — **never** attempt
  manual deletion; use the retention/PDPA flow (`retention.py`,
  `pdpa.py`) if a record must be handled per policy.
- **Audit logs**: append-only, hash-chained (P2.9). `db/seal_audit_day.py`
  seals a day's chain; `db/verify_audit_chain.py` checks it end-to-end —
  run the latter after any suspected tampering or before a compliance
  audit. Never delete rows from `audit_logs` directly.
- **Application logs**: structured JSON (P5.1, `log_context.py`), shipped to
  Loki when the `observability` profile is enabled — retention is Loki's own
  config in `observability/`, tune there if disk pressure shows up.
- **Disk pressure**: Prometheus fires at 75%/90% (see `docs/deployment.md` §
  Observability). If it fires, check object-store growth first (imaging is
  the largest and least compressible tier) before assuming DB growth.

## Dependency & security patching

- Backend: `backend/requirements.txt` is pinned (exact versions) —
  bump deliberately, one dependency at a time, re-run the full test suite +
  `db/check_schema.py` after each bump. `ldap3`'s TLS defaults
  (`validate=CERT_NONE`) bit this project once (P1.10 H4) — re-verify any
  security-relevant library's defaults against its actual installed
  behaviour after a major-version bump, not just its changelog.
- Web/mobile: `npm audit` / `flutter pub outdated` — same one-at-a-time
  discipline.
- Base images (`proxy/Caddyfile`'s Caddy, `docker-compose.yml`'s
  MariaDB/Orthanc/MinIO/Redis images): pinned to a specific tag, not
  `latest`. Bump on a schedule, verify `docker compose config` +
  `check_schema` + a smoke test before rolling to production.
- CI gate (`ci/`, P2.11): runs `check_schema`, pytest, and an
  AI-assisted code-quality/OWASP pass on every change — don't merge around
  a red gate.

## When something breaks between scheduled windows

That's the [Operations Manual](operations-manual.md) § 5 (Common incidents)
and, for anything DB/data-loss shaped, the
[Backup & DR runbook](../backend/backup/README.md) — this manual only covers
the preventive schedule above.

## Physical/hardware notes (tender 7.1(d)/(e), not applicable)

CLARION is software running on general-purpose server/client hardware
supplied per the tender's own hardware schedule — there is no
CLARION-specific electrical wiring/circuit diagram or special-function
manual beyond what's in this document set. The one piece of real hardware
this project integrates with (lab analysers via HL7 v2, P4.8) is the
analyser vendor's own equipment; its maintenance is the analyser vendor's
manual, not this one — `docs/deployment.md` § Lab-analyser HL7 v2 covers
only the integration point.
