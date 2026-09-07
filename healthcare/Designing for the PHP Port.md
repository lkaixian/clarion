---
title: Designing for the PHP Port
type: research
updated: 2026-08-30
tags: [research, codeigniter, php, portability, architecture]
---

# Designing for the PHP Port

Tender clause **** mandates PHP CodeIgniter 4. CLARION's demo is FastAPI.
The bet: build the demo now, port later — and shape the demo so the port is a
re-implementation behind stable boundaries, not a redesign.

## CodeIgniter 4 in one paragraph
MIT licence, PHP 8.1+. Synchronous MVC. `ResourceController` + `$routes->resource('x')`
auto-maps REST verbs to `index/show/create/update/delete`. Models are an Active-Record
**query builder**, not a full ORM (`$allowedFields`, `$validationRules`, `$returnType`).
Entities represent single rows and hold mutators/accessors (e.g. field encryption).
Filters = middleware. Migrations via `forge`. CLI = `php spark make:*` / `migrate` / `routes`.

## Effort estimate
Re-implementing a ~30-table clinical REST API in CI4: **2–4 person-months (~300–600 h)**
for a mid-to-senior dev. Breakdown: schema & migrations 1–2 wk, core CRUD + routing
2–3 wk, **clinical business logic + access control 4–6 wk (the hard part)**, validation
+ test rewrite 2–4 wk.

## What makes the port CHEAP
- [ ] **OpenAPI contract is the source of truth.** FastAPI emits it free; treat that
      spec as what the PHP side is written against.
- [ ] **Business rules in a service layer**, not in route handlers or SQLAlchemy chains.
      Logic in plain functions is transcribed; logic tangled in decorators is reverse-engineered.
- [ ] **Portable SQL only.** No Postgres JSONB querying / arrays, no SQLite pragmas.
      Every column explicit type + length. JSON columns OK but **never a server-side default**
      (MariaDB forbids it).
- [ ] **Mirror the MVC layout now:** `routers/` → controllers, `schemas/` → entities,
      `crud/` or `services/` → models. One-to-one folder map = mechanical port.
- [ ] **Background work on an explicit queue** (Redis + worker), not FastAPI's async loop
      or `BackgroundTasks`. CI4 is synchronous.
- [ ] **Alembic migration history** is a language-independent deliverable — runs from the
      deploy pipeline regardless of app language, and is the spec for CI4's migration
      classes. Replaces the hand-rolled `_migrate_lightweight()` (which also doesn't port
      and is a security concern — see [[Security Audit#M9]]).

## What makes it EXPENSIVE
- Heavy SQLAlchemy ORM graph, lazy-loading, unit-of-work, deep relationship joins.
- Validation tightly coupled to advanced Pydantic validators.
- Pervasive `async/await` and in-loop background tasks.

## Tooling (thin for CI4 specifically)
- `openapi-generator-cli` — PHP client SDKs + Slim/Laravel/Symfony server stubs. **No
  CI4 server template.** Useful for base DTOs.
- `zircote/swagger-php` — PHP 8 attributes → OpenAPI spec, to document the ported API.
- `jivtesh/ci4-api-generator` — community scaffolder, DB schema → CI4 controllers/models.
- JanePHP — typed DTOs from OpenAPI, Symfony-leaning.
- None replace the business-logic work.

## Sources
CodeIgniter docs: [RESTful handling](https://codeigniter.com/user_guide/incoming/restful.html),
[entities](https://codeigniter.com/user_guide/models/entities.html).
[OpenAPI Generator](https://openapi-generator.tech/), [swagger-php](https://zircote.github.io/swagger-php/).
Full detail: `scratchpad/agy-research-full.md` Part 1 Topic A. See also [[Sources]].
