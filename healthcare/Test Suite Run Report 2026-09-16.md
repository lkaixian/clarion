---
title: Test Suite Run Report 2026-09-16
type: test-report
updated: 2026-09-16
tags: [security, testing, qa, clarion, report]
---

# Test Suite Run Report — 2026-09-16

First execution of [[Security & Stability Test Suite]] (209 cases) against the real
system. **Derived by running the stack — not by reading code paths for answers**
(code was consulted only to correct *my own* probe bugs and interpret live results).

## Environment

| | |
|---|---|
| Host | Windows 11, git-bash; **no Docker daemon/CLI available** |
| Backend | fresh `uv` venv, deps per `requirements.txt` (all pins honoured) |
| Full pytest | `tests/` → **561 passed, 1 skipped (no `age` binary), 0 failed** (12 m 17 s) |
| Live stack | `uvicorn app.main:app --workers 1` on 127.0.0.1:8123, throwaway `liverun.db` (SQLite, demo seeded, `CLARION_STORAGE_BACKEND=local`, `LOG_FORMAT=json`) |
| Static gates | ruff (CI config, all 4 trees) · bandit -ll · shellcheck-py · PyYAML compose parse · git-ls-files secret scan · npm build + oxlint |

## Result summary

| Status | Cases | Meaning |
|---|---|---|
| **PASS (live)** | 34 | verified by direct HTTP/CLI/DB probe this session |
| **PASS (pytest)** | 83 | verified via the named test file in the green 561-suite |
| **PARTIAL** | 20 | half-proven here (e.g. single-worker rate limiting; mocked-storage; live half needs Docker) |
| **FAIL** | 1 | `I-T-001` CI hard gate — see F-RUN-2 |
| **BLOCKED (docker/env/tooling)** | 70 | needs the composed stack (proxy/TLS/networks, Redis/MinIO/MariaDB/Orthanc/HL7-socket drills), LDAP server, MITM, flutter, semgrep/osv/trivy |
| **NOT RUN** | 1 | `S-B-015` display-token hardening — trivial, next session |

Per-case status + evidence is machine-readable: **`healthcare/testcases-security-stability.csv`**
(columns `run_status_2026-09-16`, `run_evidence`).

## Headline live confirmations (all PASS)

- **Audit tamper-evidence for real** — raw `UPDATE`/`DELETE` on `audit_logs` abort with
  *"audit_logs is append-only (P2.9)"*; chain `ok=true, state_matches_tip=true` (S-J-001/002).
- **Refresh-token compromise model exact** — replay of a rotated token **beyond** the 8 s
  grace ⇒ 401 **and every family token revoked**; **within** grace ⇒ only that request
  fails, replacement survives (S-A-007/008/009 = SA-M4 + CR10 behaviour).
- **Global rate limit proven** — 70 GETs on an *undecorated* route ⇒ **exactly** 60×200 + 10×429
  (S-I-002, the P5.2 SlowAPIMiddleware-no-op fix holds); 40-login burst ⇒ 5×401 (per-account
  lockout) then 429s (S-I-001 half, single worker).
- **Auth negatives** — alg=`none` 401, tampered sig 401, enumeration-symmetric
  (identical status+body), `SECRET_KEY` missing ⇒ import fails closed (S-A-014/015/019).
- **RBAC live spot** — pharmacist→`/emergency/issue` 403, patient→`/patients` 403,
  admin→`/admin/inventory` 200 vs clinician 403, unauth `/emergency/scan` 404 (public by design).
- **Cookie posture** — `HttpOnly; SameSite=Strict; Path=/` (Secure off only in demo, by design).
- **Password-change revocation** — old access token dead immediately after change (S-A-012).
- **Upload cap** — 17 MB ⇒ 413 `max 15MB` pre-processing (S-G-001).
- **Schema backbone** — fresh-DB full-chain `upgrade head` + `downgrade base→head` round-trip +
  autogenerate-zero-drift + `check_schema` refusing an empty `SECRET_KEY` (I-L-001/002/004, S-J-006).
- **Supply hygiene** — ruff all trees green; shellcheck 0 findings on every ops script; no secret/PHI
  artifacts tracked in git (CR1 class clear); npm build+lint clean (I-T-002/004/005/006).

## Findings (new this run)

| # | Sev | Case | Finding | Suggested action |
|---|---|---|---|---|
| **F-RUN-1** | Medium (policy gap) | S-G-002 | `POST /ai/digitise/{patient_id}` **stores** a PE binary renamed `scan.jpg` (200, `raw_text="[OCR skipped: not an image format"`), same for broken-PNG (`"image failed safety"`). M5's *remediation wording* implies reject; actual posture = store-anything-but-process. No exec risk observed (served opaque), but WORM buckets may accumulate arbitrary binaries under patient records. | Either reject non-image/non-PDF with 4xx, or re-word the M5 closure note to "archived unprocessed". One-line gate in `digitise_document`. |
| **F-RUN-2** | Low (CI hygiene) | I-T-001 | `ci/run.sh`'s **bandit hard gate is red** on current tree: `B104` `hl7_listener.py:163` (bind 0.0.0.0 — by design for MLLP) + `B324` `patients.py:1210`, `pharmacy.py:343` (SHA1 used for **ETag**, non-security). Docs claim all gates green; last full run predates P4.8/P1.7b. | `# nosec B104` + justification; `hashlib.sha1(..., usedforsecurity=False)`; re-run `ci/run.sh` incl. semgrep/osv/trivy on a box that has them. |
| **F-RUN-3** | Info | S-A-006 | Access-token claims are `exp/sub/role` — **no `iat`**; TTL assertions still pass via pytest. | Add `iat` for session-age analytics if ever needed; harmless to leave. |
| **F-RUN-4** | Info | S-H-006 / I-K-006 | `grafana` publishes `${GRAFANA_PORT:-3000}` to the host under the `observability` profile — deviation from the architecture note's "only the proxy publishes". Profile-gated + `GRAFANA_ADMIN_PASSWORD:?` required, so acceptable; must be re-checked at deploy. | Document in deployment.md go-live gates, or bind `127.0.0.1:3000`. |
| **F-RUN-5** | Info | I-K-010 | All images are **tag**-pinned, none digest-pinned; offline `docker save`/registry + Docker secrets remain TODO (matches P1.11's own open items — not drift, just confirming). | Track under P1.11 leftovers. |
| **F-RUN-6** | Info | S-J-009 | A successful staff login wrote **no** `audit_logs` row in the live DB (only explicit `log_access` call sites do). Intentional? anomaly/AI-audit features would benefit from login events. | Decide intent; if yes, add `log_access` on login success. |

**Re-confirmed documented residuals (not new):** `SA-L1` bcrypt 72-byte truncation —
**live-confirmed collision** (two 74+-char passwords differing only after byte 72 both
authenticate). Everything else in the accepted-residuals register (`S-J-011`) still matches docs.

## What the next (Docker-equipped) session must run

1. `I-K-001/002/003/005` — from-zero MariaDB-profile boot, minio-init idempotency, real `docker compose config`.
2. `S-H-*` — TLS floor, header set, **`/api/metrics|readyz` edge 404** (the P5.1 "not yet verified live" flag), XFF spoof, CORS matrix.
3. `S-I-001/004` — 4-worker shared-counter burst, Redis-stop drill (healthz/emergency 200).
4. `I-M/I-N/I-L-005` — pool saturation, MinIO-stop blast radius + WORM delete refusal, the **owed `b2d7e4a9c1f6` on real MariaDB**.
5. `I-P-*` — timed restore drill (RTO ≤ 4 h), PITR (RPO), pre-update gate, restic check --verify.
6. `I-R-*` — branch-edge boot, https-scheme refusal, tc-netem WAN, appliance round-trip (needs `age`).
7. `I-S-*` — Locust baseline, soak, audit-storm.

## Method notes for future QA runs (self-inflicted traps, recorded so nobody repeats them)

- The agent/tooling layer **redacts literal password-looking values in payloads**
  (`"password":"<literal>"` reaches the file as `***`); build credentials at runtime from
  variables and the login contract is **OAuth2 form** (`username=`/`password=` urlencoded).
- A persistent `httpx.Client` carries the refresh **cookie**, which the endpoint prefers over
  the JSON body — replay tests must use **stateless** `httpx.post`, or the "replay" silently
  presents the rotated token and every assertion inverts.
- Repeated probe failures **do** trip the real per-account lockout (20 min) — reset
  `login_failed_count/login_locked_until` between test batteries.

Raw evidence: `pytest_run.log`, `live_probes*.json`, `live_final4/5.json` kept in the QA scratch dir.
Feeds: [[Security & Stability Test Suite]] run history, [[Implementation Roadmap]] next cleanup pass.
