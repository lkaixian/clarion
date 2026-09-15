# CLARION — Programming Manual

Tender clause **7.1(b)**. For a developer picking up this codebase: where
things live, how the pieces fit, and the workflow for changing them safely.
Pairs with the [Data Dictionary & ERD](data-dictionary.md) (schema, clause
) and `AGENTS.md` (project status/history for an AI coding agent —
read that first if you're an agent, not a human).

## 1. Stack & repo layout

FastAPI (Python) + SQLAlchemy/Alembic backend, React (Vite) web console,
Flutter mobile app, SQLite for local dev / MariaDB for production, MinIO
(S3-compatible) for file storage, Orthanc for DICOM/PACS. Deliberately kept
**language-independent at the architecture level** (backend/web/mobile own
their persistence access, no shared ORM) — see `healthcare/Designing for the
PHP Port.md` — because the long-term plan is a CodeIgniter 4 port for the
actual tender submission; this repo is the competition
demo.

```
backend/          FastAPI app, tests, Alembic migrations, db/ scripts
  app/
    models.py       SQLAlchemy ORM models — single source of truth for schema
    schemas.py       Pydantic request/response models
    database.py      engine/session setup, naming conventions, Base
    main.py          app factory, middleware, CORS, startup schema check
    auth.py          JWT issue/verify, password hashing, refresh tokens
    permissions.py    role → page/action checks (require_page_access etc.)
    ldap_auth.py       LDAP/AD bind + role resolution (P1.10)
    storage.py         ObjectStore abstraction (Local/MinIO backends)
    imaging.py / derived.py   image/PDF normalisation + thumbnail cache
    ai/                 local-LLM (Ollama) features — summarize, nric_ocr,
                         cds_hint, voice_soap, interactions, audit_intelligence
    security_analytics.py / data_quality.py   rule-based anomaly/DQ engines
    hl7v2.py / hl7_client.py / hl7_listener.py   lab-analyser integration (P4.8)
    pacs.py            Orthanc REST client + facility-scoping boundary
    routers/           one file per feature area — see § 3
  alembic/versions/    one migration per schema change, in order
  tests/               pytest — conftest.py has the shared fixtures
  db/                  operational scripts: check_schema, migrate_*,
                       gen_data_dictionary, seal_audit_day, verify_audit_chain
  loadtest/            Locust suite (P5.2)
  backup/              backup/restore/DR scripts + runbook (P2.8)
web/               React (Vite) console — src/{pages,components,api,lib}
mobile_flutter/    Flutter app — lib/{screens,widgets,providers,services,models}
proxy/             Caddy — the one TLS-terminating edge, security headers
observability/     Prometheus/Grafana/Alertmanager/Loki config (P5.1)
docs/ this manual + deployment.md + data-dictionary.md
healthcare/        Obsidian vault — research, roadmap, compliance matrix, audits
```

## 2. Backend request flow

`main.py` wires: CORS (fail-closed off the `demo` env) → rate-limit
dependency (`rate_limit.py::enforce_rate_limits`, Redis-backed, fails open on
Redis outage — P5.2) → auth (`auth.py`, JWT bearer, 15-min access + rotating
refresh token) → router. Every router function that touches patient data
calls a `require_page_access`/facility-scoping helper near the top —
`patients.py`'s `_facility_known_patient_ids` /
`_patient_known_to_facility` is the canonical pattern most other routers
(`ancillary.py`, `fhir.py`, `pacs.py`, `emergency.py`) reuse rather than
reimplement. **Any new endpoint touching patient data must call one of
these, not invent its own check** — see `healthcare/Security Audit.md` for
what happens when a router skips it (P3.1/P4.5 both shipped RBAC bugs this
way, caught in review, see `healthcare/Implementation Roadmap.md`
changelog).

## 3. Router index (backend/app/routers/)

| Router | Covers |
|---|---|
| `auth_router.py` | login/logout/refresh, password reset/change, LDAP |
| `patients.py` | patient CRUD, facility-scoped list/search, full record |
| `reception/` (package: `checkin.py`, `queue.py`, `rooms.py`, `stations.py`, `admissions.py`) | check-in, queue, room claims, calling-system TV |
| `consultation.py` | clinician consult flow, sign-off, CDS hint, voice-to-SOAP |
| `ancillary.py` | Procedure/Laboratory/X-ray/Physiotherapy shared order/result engine |
| `dental.py` | FDI tooth chart module (thin — reuses ancillary/consultation) |
| `pharmacy.py` | inventory, dispensing, purchase-approval, prescription screen |
| `billing.py` | charges, invoices, service catalog |
| `emergency.py` | unauthenticated emergency-scan intake (kept reachable no matter what — see Operations Manual § incidents) |
| `appointments.py` | booking, self-service (mobile), double-book guard |
| `admin.py` | users, roles, facilities/sections, LDAP mappings, security/DQ alerts (largest file — 100K+, candidate to split if it grows further) |
| `pdpa.py` | consent, data-subject requests (no erasure — Malaysia has none) |
| `fhir.py` | read-only FHIR façade over 8 resource types |
| `pacs.py` | DICOM study list/viewer proxy to Orthanc |
| `reporting.py` | dashboards, predictive analytics, NL narrative |
| `self_registration.py` | patient self-service signup/booking (mobile) |
| `display.py` | public waiting-room TV display (no auth, read-only) |
| `profile.py` | own-account settings, signature pad |
| `staff.py` | clock-in/out, room claims |
| `dashboard.py` | landing-page summaries per role |

## 4. Making a schema change

1. Edit `app/models.py` (the only place columns/tables are declared).
2. `alembic revision --autogenerate -m "..."`, then **read the generated
   file** — autogenerate misses some MariaDB-specific things (see existing
   migrations for the `TZDateTime`/`Computed`-column patterns already
   worked around).
3. `python -m db.check_schema` — must PASS on SQLite; also run against a
   real MariaDB before merging if the change touches a MariaDB-specific
   type or the DATETIME(6) family.
4. `python -m db.gen_data_dictionary` — regenerates `docs/data-dictionary.md`
   from the new metadata. Commit the regenerated file alongside the
   migration (it's generated, but generated-and-committed is the tender's
   own ask — the tender wants the documentation to exist, not just be
   regenerable).
5. Run the full test suite (`pytest` from `backend/`).

## 5. Making an endpoint change

1. Add/change the route in the right `routers/*.py` file (§ 3).
2. Reuse the facility-scoping helper for that data type (§ 2) — never
   write a new one inline.
3. Add/update the Pydantic schema in `schemas.py`.
4. Add a test in `backend/tests/` — this codebase's convention is one
   `test_<feature>.py` per feature, using `conftest.py`'s
   `test_client`/`db_session`/`make_user`/`auth_headers` fixtures.
5. If the change is security-relevant (auth, RBAC, PHI exposure, injection
   surface), get a `voltagent-qa-sec:security-auditor` review before
   merging — this has been standard practice every phase (see
   `healthcare/Implementation Roadmap.md`'s changelog for the pattern: it
   has caught a real bug in nearly every phase).

## 6. Testing

```bash
cd backend && venv/Scripts/python.exe -m pytest -q        # Windows venv, this repo's default
python -m db.check_schema                                  # schema/migration gate
python -m db.gen_data_dictionary                            # after any model change
```

`web/`: `npm run build` (must stay clean — CI-equivalent gate) and
`npm run lint`. `mobile_flutter/`: `flutter analyze` + `flutter test`.

## 7. Local-only AI (never regress)

the tender forbids third-party AI cloud APIs. All inference in
`app/ai/` goes through `ai/local_llm.py` (Ollama). There is no cloud
fallback path left in the codebase (`_cloud_guard.py`/`anthropic` dependency
were removed at P4.3) — do not reintroduce one. See `healthcare/Security
Audit.md` finding C1 and `healthcare/On-Prem Clinical AI.md`.

## 8. Coding conventions specific to this repo

- Comments over docstrings for **why**, not what — this codebase leans
  heavily on inline rationale for non-obvious decisions (see any router for
  examples); match that style rather than adding a design-doc comment block.
- No new dependency without checking the ladder first: stdlib → native →
  already-installed. See `healthcare/Implementation Roadmap.md`'s
  changelog for repeated examples of picking the dependency-free path
  (e.g. `predictive_analytics.py`'s hand-rolled EWMA, `hl7v2.py`'s
  hand-rolled encode/decode instead of a third-party HL7 library).
- Every AI feature is advisory, never authoritative on its own — a human
  always signs off (consultation sign-off, lab-result review, etc.).
- Migrations are additive; nothing gets dropped from a live schema without
  a documented reason (see `models.py`'s `reset_attempt_count` comment for
  the pattern: leave vestigial columns in place with a comment rather than
  risk a drop against a seeded DB).
