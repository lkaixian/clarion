# Scaling the central node (theoretical)

Status: design note, **not built or load-tested**. The real demo is `docker-compose.pi.yml`
(one Raspberry Pi, SQLite, tunnel). The real tender scope is two campuses and about 23k
users, which the single-VM `docker-compose.yml` already targets. This note only answers
"what would change for much larger traffic", so nobody has to guess.

## Why one container never serves a country

| Layer | One box | At scale |
|---|---|---|
| Homepage, status page, images | Pi / nginx container | **CDN** (Cloudflare Pages or similar). Static files, no server to scale. |
| Edge / TLS | Caddy | Cloudflare in front, 2+ Caddy or nginx nodes behind a load balancer |
| API | 1 container, 2-4 gunicorn workers | **N stateless replicas** behind the load balancer |
| Rate limiting | Redis (1 node) | Redis with replica/sentinel. Already shared across workers, and falls back to in-memory if Redis is down (see `app/rate_limit.py`) |
| Database | **SQLite** (Pi) / MariaDB (single VM) | MariaDB primary + read replica(s) or Galera. SQLite cannot be shared by replicas. |
| Files | local dir | MinIO cluster (S3 API, already abstracted by `ObjectStore`) |

The API is already stateless apart from the database, Redis and the object store, so
replicas are a deployment change, not a rewrite.

## The three things that must change first

1. **Leave SQLite.** More than one API container needs the MariaDB path
   (`DATABASE_URL=mysql+pymysql://...`, then `alembic upgrade head`). The pool maths in
   `backend/Dockerfile` (workers x 40 connections against `max_connections=200`) must be
   redone per replica count.
2. **Load balancer in front of the replicas.** nginx `upstream` (or Caddy with dynamic
   upstreams). Plain Docker DNS round-robin is not a real balancer. Keep the trusted-proxy
   rule: backends trust `X-Forwarded-For` only from the balancer's address range.
3. **Move the static site to a CDN.** The status page already polls same-origin
   `/api/healthz`, so it keeps working if `/api/*` is routed to the API origin.

## What this does not solve

- **Capacity numbers.** P5.2 never produced one (single-client load test, one apparent IP).
  Any "N users per node" figure needs a distributed load run against a staging stack.
- **Data residency and PDPA.** Patient data stays on infrastructure the operator controls.
  Hosted databases (including Supabase cloud) are excluded by the on-prem and no-cloud rules
  in `AGENTS.md`. A static CDN is fine because it holds no patient data.
- **A national exchange.** Cross-organisation record sharing is a different system. See
  `healthcare/Nationwide Health Information Exchange.md` (out of build scope).
- **Regional sites.** The existing `branch-edge` profile is the pattern for a second site:
  an edge proxy with an offline emergency export, talking to the central API over the WAN.

## Hospital nodes joining the central node (design, not built)

Goal: a hospital (for example Hospital Main Campus) runs its own CLARION stack on its own
network, joins the central node at `clarion.larmkx.com`, and other nodes can see its results.

**Connectivity.** Each node dials *out* to the central node (Cloudflare Tunnel or VPN). The
hospital opens no inbound ports. Phones and browsers use the fixed name, never an IP.

**Start hub-and-spoke, not a full mesh.** Every node talks only to the central node:

1. A node pushes new records to central through an authenticated API call.
2. Other nodes pull what they are allowed to see with a cursor, `GET /federation/feed?since=<cursor>`.
3. True peer-to-peer mesh adds topology, conflict and replay problems for little gain. Add it
   only if nodes must work with the central node down.

**What already exists to build on.** The cross-facility model (a record recorded by another
facility is read-only on the receiving side), `resource_identifiers` (stable external ids for
de-duplication), the read-only FHIR facade, and the `branch-edge` pattern for a remote site.

**What must be added.**
- Node identity: one credential per node (mTLS or a signed token), revocable by central.
- `ingest` and `feed` endpoints with cursors, idempotency keys and replay protection.
- De-duplication by (origin node, resource id). Records are append-only and signed by the
  originating facility, so there is no merge conflict to resolve, only duplicates to ignore.
- Access rules on the feed. Copying every patient to every node widens the PHI exposure under
  PDPA. Prefer central as an index plus fetch-on-demand (audited, like break-glass), and
  replicate only what consent and clinical need justify.
- A first load test of the sync path before claiming anything about scale.
