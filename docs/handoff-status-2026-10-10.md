# CLARION -- status handoff, 2026-10-10

Written to start a fresh session without re-deriving anything. Source of truth
for detail: `healthcare/Implementation Roadmap.md` (changelog, entries dated
2026-10-10) and `docs/deployment.md`. `AGENTS.md` has the project rules.

## 1. Where the code is

- Branch `main`, **pushed**, head `770336e`. Recent commits this session:
  `284a995` web fixes, `09e1ba5` encrypted NFC tag, `2b137b5` federation,
  `1787b71` central-node fix + admin reset CLI, `770336e` auth overhaul +
  status page + app download.
- Left local on purpose (not mine): `.agents/`, `qa/`,
  `clarion-architecture.png`, `docs/not-done-yet.txt` (now partly stale, see
  section 5), an edit to `healthcare/Security & Stability Test Suite.md`, a
  `.claude/worktrees/...` marker.
- Not in git by design: `web/public/downloads/clarion.apk(.sha256)`,
  `.local-secrets/admin-password.txt`, `.env.docker`, `.env.tunnel`.
- Checks at head: backend **617 passed, 1 skipped**; `check_schema` PASS;
  web `npm run build` + `npm run lint` clean; `flutter analyze` clean.
  (`mobile_flutter/test/widget_test.dart` was already failing before this work.)

## 2. What is running

Central node = `docker-compose.pi.yml`, compose project `clarion-pi`, public at
**https://clarion.larmkx.com** through the cloudflared tunnel.

```
export CENTRAL_DB_PORT=13306      # Windows blocks 3306 on this machine
docker compose -f docker-compose.pi.yml --env-file .env.docker --env-file .env.tunnel up -d --build
```

Services (all healthy at last check): backend, web, proxy (Caddy), mariadb
(TDE), minio, redis, mpi, cloudflared. MariaDB is the DB (not SQLite).
`docker-compose.yml` (the full demo stack, project `clarion`, ports
18080/18443) may also still be running from earlier -- check `docker ps`.
`docker-compose.spoke.yml` is the shared-DB hospital-spoke alternative
(verified once locally, not deployed).

Public pages: `/` landing, `/login`, `/security`, `/status` (expandable cards),
`/get-app` (APK download), `/mpi/healthz`. `/api/readyz|metrics|docs` and
`/mpi/admin/*` are blocked at the edge.

## 3. Access and secrets

- Admin: `admin@clarion.demo`; password is in
  `.local-secrets/admin-password.txt` (gitignored). First sign-in forces:
  authenticator-app enrolment (QR + recovery codes) -> password change.
- All five seeded demo accounts had their passwords rotated to unrecorded
  random values (their old ones were printed in a chat transcript). Only the
  admin was given a known one. Recovery tool:
  `backend/db/reset_admin_password.py <email>` (run inside the backend
  container; prints a one-time password to the terminal).
- `MPI_ADMIN_TOKEN` is **unset** -> hospital registration at central is
  disabled until set (>= 24 chars).
- `CLARION_MFA_REQUIRED_ROLES` defaults to `admin,clinician,records_officer`
  in the central compose; the app default is empty (opt-in).
- MinIO backend password is still the default `change-me-minio-backend`.
- The MariaDB TDE key file (`backend/db/mariadb/encryption/keyfile`) exists
  only on this machine and is not backed up.

## 4. Built this session (all committed)

1. **Encrypted offline NFC tag** -- AES-GCM blob bound to the tag UID with a
   sealed expiry (`app/tag_crypto.py`); `GET /emergency/tag-keys`,
   `POST /emergency/offline-reads` + `offline_tag_reads`; Flutter opens tags
   offline with 72 h-cached keys, 1500 ms scan cap, hash-chained read log.
   NTAG213/215/216 keep working with a "no read counter" warning on web and
   mobile. NTAG 424 DNA counter = phase 2 (needs hardware).
2. **Federation (federated, not shared-DB)** -- `backend/mpi/` central record
   locator (HMAC(pepper, NRIC) -> newest-3 pointers per hospital, Ed25519
   signatures, nonce/audience/replay cache), `app/mpi_client.py`,
   `routers/federation.py`, publish hook on consultation sign-off,
   optional `CLARION_PEER_KEYS` pinning.
3. **Auth overhaul** -- TOTP MFA with recovery codes and forced enrolment,
   session list/revoke, uniform login timing, audited failures, new-device
   and security-change emails, two-path login page, `/security` page, mobile
   code step. Refresh tokens carry `mfa_ok`.
4. **Public site** -- expandable status cards (API split into 6 server-side
   probes, typical/p95 latency baselines, outage impact), `/get-app` page,
   login logo/"home" does a real page load.
5. **Ops** -- central node rebuilt; nginx security-header snippet; admin
   reset CLI; docs and roadmap updated.

## 5. Known gaps and open decisions

Decisions that are the product owner's call:
- **Consent / presence proof** for cross-hospital reads: today any registered
  hospital that knows an NRIC + the pepper can fetch that patient's recent
  signed visits (audit trail is the only control).
- **Pepper strength:** the NRIC space is small; a leaked pepper + a central
  DB dump re-identifies everyone (needs an OPRF / keyed lookup service).
- **First-enrolment takeover window:** a required-but-unenrolled account can
  be enrolled by anyone with its temporary password. Mitigated only by email
  + audit. Option: admin-issued one-time enrolment code.

Not done:
- **Backups for the central node** (MariaDB + MinIO); no restore drill.
- Cloudflare Access gate and origin-TLS verification (dashboard-side).
- Never built/run on ARM64 (the Pi); no load test with a real capacity number.
- NTAG 424 DNA provisioning + counter checks (hardware).
- Redis-backed replay cache for the MPI and peer route (currently
  per-process; MPI runs one worker on purpose).
- APK is signed with the **debug key**; not installed or tried on a device;
  mobile Settings help text still mentions 10.0.2.2 / LAN IPs.
- MFA enrolment exists on web only (mobile prompts for the code).
- New-device / security email text was written against Mailtrap, which the
  owner says now works, but no real message has been confirmed.
- `docs/not-done-yet.txt` is stale: ESLint note (project uses oxlint), the
  3 flaky analytics tests, "nothing pushed", "no hospital nodes" and "docs not
  updated" are no longer true.

## 6. Environment gotchas

- `flutter test` / `flutter build apk` fail with the SDK path containing a
  space: use the junction `C:\flutter_nospace` (PATH) and set
  `ANDROID_HOME`/`ANDROID_SDK_ROOT=D:\AndroidStudioSDK` for the command (the
  shell's `ANDROID_HOME` is wrong).
- Git Bash mangles `/paths` in `docker exec -w`; use `MSYS_NO_PATHCONV=1`.
- Large inline python heredocs with `'''` break the Bash tool; write the
  script with the Write tool and run it.
- Host port 3306 is blocked on Windows here -> `CENTRAL_DB_PORT=13306`.
- Backend venv: `backend/venv/Scripts/python.exe -m pytest tests -q` (~6-8 min).
- Rebuilding the `web` image is what publishes a new APK / static page.

## 7. Suggested next steps

1. Install the APK on a phone; sign in with MFA; confirm the offline-tag flow.
2. Set `MPI_ADMIN_TOKEN`; register a first hospital; run a publish -> lookup
   -> fetch end to end across two real nodes.
3. Decide the consent model and the enrolment-code option above.
4. Add central backups (MariaDB dump + binlog shipping, MinIO mirror) and
   copy the TDE keyfile somewhere safe.
5. Refresh `docs/not-done-yet.txt` from this file.
