# CLARION backup & DR runbook (P2.8, the tender)

One script bundle: `backup.sh` (scheduled), `restore-test.sh` (quarterly),
`pre-update-snapshot.sh` (deploy gate), `lib.sh` (shared config/logging).
It runs in the `backup` compose service (profile `backup`) or standalone on
a host with `mariadb-backup`, `mydumper`, `mc`, `restic`, and `age`.

## Objectives

| | Target | How |
|---|---|---|
| **RPO** — clinical DB | ≤ 1 h (published); ≈ 15 min real | binlog shipped every 15 min |
| **RPO** — object store | ≤ 24 h | daily `mc mirror` |
| **RTO** — full system | ≤ 4 h | full + incr restore + binlog replay + stack up |
| **RTO** — app tier only | ≤ 1 h | redeploy images against the live DB |
| Retention | ≥ 30 days all tiers; 7-yr WORM for records/audit/imaging | restic `--keep-daily 30 --keep-weekly 12 --keep-monthly 84 --keep-yearly 7`; MinIO object-lock |

## Schedule (cron in the `backup` service)

```
*/15 * * * *   backup.sh binlog
15   1 * * 1-6 backup.sh daily         # Mon-Sat: incr + logical + objectstore
15   1 * * 0   backup.sh weekly        # Sun: full + prune + restic check
0    3 1 */3 * restore-test.sh --report /backup/restore-report.json   # quarterly
```

`backup.sh` writes one JSON line per run to `/backup/status.jsonl`
Wire that into the P5.1 alerting (a `result != "ok"` line, or
no `binlog` line for > 45 min, pages the on-call).

## 3-2-1

- **restic repo** on VM-BACKUP (`RESTIC_REPOSITORY`) — encrypted, dedup'd,
  content-addressed. Weekly `restic check --read-data-subset`.
- **Monthly rotated offline disk** in a different building — `restic copy` to
  a second repo on a USB/LTO disk, then vault it. (Manual; log in the DR
  register.)
- The DB backup files are *also* `age`-encrypted before they hit restic
  (`AGE_RECIPIENTS`), so the offline disk carries no plaintext even if the
  restic password leaks.

## Restore (full system, RTO ≤ 4 h)

1. Fresh VM from the last pre-update image + `HYPERVISOR_SNAPSHOT_ID`.
2. `restic restore latest --tag mariadb-full` → decrypt (`age -d -i <key>`) →
   `mariadb-backup --prepare`.
3. For each incremental in date order:
   `mariadb-backup --prepare --target-dir=<full> --incremental-dir=<incr>`.
4. `mariadb-backup --copy-back --datadir=/var/lib/mysql`; fix ownership; start
   mariadbd.
5. **Point-in-time**: replay binlogs past the last incremental up to the
   target time — `mariadb-binlog --stop-datetime='...' clarion-bin.* | mariadb`.
6. Object store: `mc mirror /backup/minio/<bucket> clarion-minio/<bucket>` (or
   restore MinIO from its own versioned buckets if only app data was lost).
7. Bring the stack up **against the restored DB**, run
   `python -m db.check_schema` + the pytest smoke subset, reconcile row
   counts (`restore-test.sh` does this automatically on the sandbox).
8. File the signed restore report with the University.

## Pre-update gate

`pre-update-snapshot.sh "<what you're changing>"` — **must exit 0 before any
`alembic upgrade`, image bump, or config change.** It takes a fresh full +
logical backup, records the current Alembic head as the `downgrade` target,
captures running image digests, and prompts for the hypervisor snapshot id.
Rollback = restore that backup / snapshot, or
`alembic downgrade <recorded target>` + redeploy the previous images.

## Encryption at rest for the backup files

`mariadb-backup` has no `--encrypt` — the pipeline streams its (and
`mydumper`'s) output through `age` and into the restic repo, which is itself
encrypted. Both `RESTIC_PASSWORD` and the `age` identity must be stored in
the org secret manager, **not** on VM-BACKUP.

## Responsible contacts (fill in per deployment)

| Role | Name | Contact |
|---|---|---|
| Backup operator | _TBD_ | _TBD_ |
| DR coordinator | _TBD_ | _TBD_ |
| University PTM liaison | _TBD_ | _TBD_ |
| Data Protection Officer (P2.10) | _TBD_ | _TBD_ |
