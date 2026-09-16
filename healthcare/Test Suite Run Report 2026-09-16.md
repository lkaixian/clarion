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
| **F-RUN-2** | Low (CI hygiene) | I-T-001 | `ci/run.sh` **two hard gates are red**: ① bandit -ll exit 1 (`B104` `hl7_listener.py:163` bind 0.0.0.0 by design; `B324` ×2 ETag SHA1) ② osv-scanner exit≠0 (see F-RUN-8). ruff, semgrep (16 INFO `broad-except-pass` advisories filtered by the ERROR/WARNING gate → green), check_schema, pytest all GREEN. | `# nosec B104` + justification; `usedforsecurity=False`; bump pycryptodome; re-run `ci/run.sh` end-to-end. |
| **F-RUN-3** | Info | S-A-006 | Access-token claims are `exp/sub/role` — **no `iat`**; TTL assertions still pass via pytest. | Add `iat` for session-age analytics if ever needed; harmless to leave. |
| **F-RUN-4** | Info | S-H-006 / I-K-006 | `grafana` publishes `${GRAFANA_PORT:-3000}` to the host under the `observability` profile — deviation from the architecture note's "only the proxy publishes". Profile-gated + `GRAFANA_ADMIN_PASSWORD:?` required, so acceptable; must be re-checked at deploy. | Document in deployment.md go-live gates, or bind `127.0.0.1:3000`. |
| **F-RUN-5** | Info | I-K-010 | All images are **tag**-pinned, none digest-pinned; offline `docker save`/registry + Docker secrets remain TODO (matches P1.11's own open items — not drift, just confirming). | Track under P1.11 leftovers. |
| **F-RUN-6** | Info | S-J-009 | A successful staff login wrote **no** `audit_logs` row in the live DB (only explicit `log_access` call sites do). Intentional? anomaly/AI-audit features would benefit from login events. | Decide intent; if yes, add `log_access` on login success. |
| **F-RUN-7** | Medium (CI supply) | I-T-001 | The repo's documented dev install `pip install -r requirements.txt -r requirements-dev.txt` is **UNRESOLVABLE today**: `requirements.txt` pins `wrapt==2.3.0`, `semgrep==1.176.1` requires `wrapt<2.0.0` (live uv resolution failure). P2.11's "all hard gates green" can't be reproduced via the documented path. Local workaround used: separate CI venv. | Reconcile the pin (allow wrapt<2 or bump semgrep when compatible); note in ci/README. |
| **F-RUN-8** | High→triage | I-T-003 | osv-scanner (hard gate) live: **3 HIGH** — `ecdsa 0.19.2` PYSEC-2026-1325 (CVSS 7.4, **no fix**, python-jose dep — extends the SA-L1 family), `pycryptodome 3.9.9` PYSEC-2026-1811 (CVSS 7.1, **fixable → 3.19.1**, transitive via ldap3) — the latter is a NEW untriaged HIGH. | Bump/pin pycryptodome ≥3.19.1; record ecdsa as accepted residual next to L1. |
| **F-RUN-9** | Medium | I-N/S-F hardening | trivy misconfig (soft gate): `DS-0002` **HIGH ×2 — backend and web Dockerfiles run as root** (no USER). Docker-on-Windows mitigates somewhat; tender OWASP/ASVS posture expects non-root. | Add `USER app` (non-root) to both Dockerfiles at next container pass (P1.11 leftovers). |

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

## Toolchain installed during this session (all on D: per user request)

| Tool | Version | Location | Unblocks |
|---|---|---|---|
| Backend venv (runtime deps) | py3.11 + all pins | `D:\CLARION\clarion\backend\.venv` | pytest/live-stack (used) |
| CI venv (semgrep 1.176.1, locust 2.46.5, ruff, bandit, shellcheck-py, mitmproxy 12.2.3) | — | `D:\CLARION\tools\ci-venv` | I-T-001 ✓ran, S-E-003, loadtests |
| osv-scanner | 2.6.0 | `D:\CLARION\tools\` | I-T-003 ✓ran → F-RUN-8 |
| trivy (+ cached DBs) | 0.74.0 | `D:\CLARION\tools\` | I-T-003/I-N hardening ✓ran → F-RUN-9 |
| age / age-keygen | 1.3.2 | `D:\CLARION\tools\` | I-F-005/006, I-R-006, un-skips 1 pytest |
| restic | 0.19.1 | `D:\CLARION\tools\` | I-P-* backup/restore drills |
| testssl.sh | latest | `D:\CLARION\tools\testssl.sh` | S-F-008/S-H-008 TLS probes |
| Flutter stable | 3.47.4 | `D:\flutter` | I-T-007 release-signing |
| **Docker Desktop** | latest (winget) | `C:\Program Files\Docker` | **53 BLOCKED(docker) cases** |
| **WSL2 + Virtual Machine Platform** | enabled | system | Docker backend |

`D:\CLARION\tools` added to user PATH. **A reboot is required** before WSL2/Docker
will start (feature-enable pending). Note: Docker Desktop's VM data can be pointed to
`D:` from Settings → Resources → Advanced → *Disk image location* on first launch.

## Tooling provisioned 2026-09-16 (post-run), all on D:

| Tool | Version | Location | Unblocks |
|---|---|---|---|
| semgrep (CI-pinned 1.176.1) | 1.176.1 | `D:\CLARION\tools\ci-venv` | S-D-014, I-T-001 full gate |
| locust | 2.46.5 | app `.venv` (pin-matched) | I-S-001 load runs |
| ruff / bandit / shellcheck-py / pytest | current pins | app `.venv` | I-T-* |
| trivy / osv-scanner / gitleaks / age / restic | 0.74.0 / 2.6.0 / 8.30.1 / 1.3.2 / 0.19.1 | `D:\CLARION\tools\bin` | I-T-003, I-P-*, F-* crypto drills |
| testssl.sh | clone | `D:\CLARION\tools\testssl.sh` | S-F-010, S-H-010 TLS suites |
| Flutter / Dart | 3.47.4 / 3.13.3 | `D:\CLARION\tools\flutter` | I-T-007 — first `flutter analyze` ran; enable Windows **Developer Mode** (`start ms-settings:developers`) for symlink-based plugin builds |
| MariaDB native | 11.4.5 winx64 | `D:\CLARION\tools\db` | I-L-005 owed MariaDB runs, I-M-* pool tests |
| Redis native | 8.10.1 winx64 | `D:\CLARION\tools\redis` | S-I-001 shared-counter (multi-process) |
| mitmproxy | latest | app `.venv` | S-E-003 NIH payload capture |

PATH persisted (user scope): `D:\CLARION\tools\bin`, `D:\CLARION\tools\flutter\bin`.

**Still blocked:**
- **Docker engine** — Docker Desktop 29.8.0 is *installed* but the VM cannot start:
  `HypervisorPresent=False` (virtualisation off in firmware). Needs a UEFI reboot to enable
  VT-x/AMD-V (then likely `wsl --install` from an admin shell). Unblocks the 53 `BLOCKED (docker)`
  cases — bootstrap trio, edge/TLS/header/XFF probes, Redis/MinIO outage drills, backup restores,
  branch-edge, WORM enforcement.
- **MinIO native binary** — `dl.min.io` now returns **410 Gone** (upstream retired, matching
  the vault's "MinIO is dead upstream" note); only the quay.io *container* images remain, so
  MinIO-dependent cases also wait on virtualisation.
- **LDAP server** for live AD drills — docker-only (e.g. `osixia/openldap`) ⇒ same gate.
- **F-RUN-7 (new, low)** — `requirements-dev.txt` (semgrep 1.176.1 → `wrapt<2`) is
  **incompatible with** `requirements.txt` (`wrapt==2.3.0`) in a single venv; CI/dev setup needs
  two envs (as done here) or a semgrep bump. Repo hygiene note.

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
