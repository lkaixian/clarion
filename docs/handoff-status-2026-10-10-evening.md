# CLARION -- status handoff, 2026-10-10 (evening session)

Continues `docs/handoff-status-2026-10-10.md` (read that first for the central
node, federation and secrets background). This file is what changed after it.
Roadmap detail still lives in `healthcare/Implementation Roadmap.md`.

## 1. Where the code is

- Branch `main`, pushed, head **`9b49e9d`**. Commits this session, oldest first:
  `2f2d1d7` (UI overhaul, tamper seal, audit archive, update check),
  `06cdfd6` (card launches the app, v1.5.0), `6d7e5c3` (password policy,
  status history, settings, Android 10+), `9b49e9d` (security-review fixes,
  v1.6.1).
- Left uncommitted on purpose (not mine): `.agents/`, `qa/`,
  `clarion-architecture.png`, `docs/not-done-yet.txt`, an edit to
  `healthcare/Security & Stability Test Suite.md`, a `.claude/worktrees` marker.
- Checks at head: backend **640 passed, 1 skipped, 1 flaky**
  (`test_mfa_auth.py::test_forced_enrolment_then_verify_flow` -- depends on the
  30 s TOTP step boundary, passes alone); `check_schema` PASS; web build clean;
  `flutter analyze` 0 issues, `flutter test` 7/7.

## 2. What is running

- Central node `clarion-pi` (https://clarion.larmkx.com) and the standalone
  demo stack `clarion` were both rebuilt at `9b49e9d`; all healthy.
- Alembic head is **`e5b7c1d9a3f4`** (`status_daily`), on top of
  `d3a91c5e7b20` (tamper-seal columns).
- Published APK: **1.6.1+9**, ARM64 only, Android 10+ (minSdk 29), debug-signed.
  `web/public/downloads/clarion.apk` + `.sha256` are gitignored; rebuilding the
  `web` image is what publishes them.
- Deploy commands (both stacks):
  `CENTRAL_DB_PORT=13306 docker compose -f docker-compose.pi.yml --env-file .env.docker --env-file .env.tunnel up -d --build backend web`
  and `docker compose -f docker-compose.yml --env-file .env.docker up -d --build backend web`
  (the demo stack needs `--env-file .env.docker`).

## 3. Accounts (central node `clarion-pi` only)

| Account | Hospital / patient | Password |
|---|---|---|
| `admin@clarion.demo` | Hospital Sejahtera admin | `.local-secrets/admin-password.txt` |
| `admin_hpinang@clarion.demo` | Hospital Pulau Pinang admin (already existed, MFA enrolled) | owner knows it |
| `admin_hmain@clarion.demo` | **Hospital Main Campus** admin (new) | `.local-secrets/admin-hmain-password.txt` |
| `patient2@clarion.demo` | Nur Aisyah binti Rahman, NRIC 950520-14-5678 (new) | `.local-secrets/patient-demo-password.txt` |

A "hospital" is only a facility name on staff accounts; Pulau Pinang and Main Campus have no settings, rooms, staff or patients yet. Other seeded demo accounts
still have unrecorded rotated passwords (`backend/db/reset_admin_password.py`).
No NFC cards are registered on either stack; raw UIDs are never stored (HMAC +
last 4 only, Security Audit M7).

## 4. Built this session

1. **Web UI overhaul** -- sidebar shell (`components/Layout.jsx`), semantic
   classes in `index.css` (`card`, `field-input`, `btn-primary`...), redesigned
   patient record, per-viewer watermark on every page (`Watermark.jsx`).
2. **Signature download closed** -- `/staff/{id}/signature` and
   `/patients/{id}/annotations/{id}/signature` removed; PDFs print typed name +
   a digital seal code, never the signature image. Only `GET /me/signature`
   (own) remains.
3. **Tamper seal** (`backend/app/seal.py`) -- Ed25519 over signer, signature
   hash, content and time for encounters, annotations, ancillary results and
   dental entries. `seal_status` = valid / altered / unsealed / unknown_key,
   shown as badges on web. A missing seal on a row signed after
   `SEAL_CUTOVER` (2026-10-10 09:30Z) reads "altered". Signed encounters can
   no longer be PATCHed (409). Key: `CLARION_SEAL_PRIVATE_KEY`, else the
   federation key, else derived from `SECRET_KEY` (**set a real key for prod**).
4. **Audit log** -- `?days=N` window (web + mobile default 7 days), copy-only
   cold storage `db/archive_audit_logs.py` -> WORM `clarion-reports-archive`
   (`app/audit_archive.py`), re-verifiable from storage. Nothing is deleted
   from `audit_logs`; the partition drop stays a DBA step. Retention = 7 years.
5. **App update check** -- public `GET /app/version`
   (`CLARION_APP_LATEST_VERSION`, `CLARION_APP_MIN_VERSION`,
   `CLARION_APP_DOWNLOAD_URL`); Flutter banner (soft) or blocking card (below
   min). **Bump the env/compose default (`backend/app/main.py`,
   `docker-compose.pi.yml`) whenever a new APK ships.**
6. **Card launches the app** -- NFC writer prepends an `application/vnd.clarion`
   MIME record; manifest `NDEF_DISCOVERED` filter; `MainActivity.kt` hands UID +
   text to Dart (`services/launch_tag.dart`, `app.dart::_openPendingTag`). Only
   sealed tag data is shown on this path. Standardise cards on **NTAG215**.
   Old cards must be re-written once. Lock-screen display is OFF (unlock
   required). `FLAG_SECURE` blocks screenshots in the app.
7. **Password policy** -- 8+ chars, 1 number, 1 capital, 1 of `! @ # $ * . ?`
   (`schemas.password_rule_failures`; mirrored in `PasswordRules.jsx` and
   `widgets/password_rules.dart`) with a live checklist on change / forgot /
   self-register. Forced first-login change asks only new + confirm; voluntary
   change still needs the current password and is rate-limited.
8. **Friendly errors** -- lockout text shows local 12-hour time + minutes left;
   422 detail arrays no longer crash the web page (`errorMessage` in
   `api/client.js`, `_friendlyDetail` in `api_exception.dart`).
9. **Status page** (`web/public/status.html`, `status.css`, `site.js`) --
   banner, 90-day uptime bars from server-side samples
   (`status_daily`, 1/min sampler, `GET /status/history`), incident list, and
   separate "round trip from your device" vs "server processing" boxes. History
   only starts from 2026-10-10.
10. **Flutter** -- Material 3 theme, shared widgets, settings screen reduced to
    boxed Language + Theme (backend URL no longer exposed), Android 10+ only,
    audit window chips.

## 5. Open items

- **Device test** the APK: locked-phone card tap, settings, password checklist.
  Nothing was run on a physical phone.
- Set `CLARION_SEAL_PRIVATE_KEY` (and back it up) before real use; the TDE
  keyfile is still only on this machine.
- Schedule `python -m db.archive_audit_logs --verify` in cron (not scheduled).
- Real APK signing key (debug key today).
- Hospitals Pulau Pinang / Main Campus are empty shells; populate them like
  Hospital Sejahtera if the demo needs it, and register them at central once
  `MPI_ADMIN_TOKEN` is set (federation still disabled).
- Old open decisions from the first handoff still stand (cross-hospital
  consent, pepper/OPRF, first-enrolment takeover, central backups).
- Possible: PDF QR verification page, `tag_max_bytes` default (128) could be
  raised for NTAG215, per-screen redesign of the biggest pages.

## 6. Gotchas learned

- A long `python - <<'EOF'` heredoc containing `'''` breaks the Bash tool;
  write the script with the Write tool and run it.
- Piping pytest through a filter can hide the pass/fail summary (the tool caps
  output at ~200 lines); use `-q --disable-warnings | tail`.
- A backgrounded `( ... ) &` inside Bash is invisible to the user; use the
  tool's `run_in_background` so progress and completion are tracked.
- XML comments cannot contain `--` (broke the Android manifest merge).
- Flutter build: `PATH=/c/flutter_nospace/bin`, `ANDROID_HOME`/`ANDROID_SDK_ROOT`
  = `D:\AndroidStudioSDK`; ARM64 only: `flutter build apk --release --target-platform android-arm64`.
- Do not use `-x` with the full suite when hunting policy-change fallout; it
  stops at the first failure.
