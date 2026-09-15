# Branch campus edge (P5.3, tender: two-campus rollout)

`healthcare/On-Prem Architecture.md`'s deployment topology calls for "one
central stack at Main Campus; Branch over the University WAN with a light edge
proxy + Redis for static/SPA" plus "a nightly encrypted offline
emergency-export appliance ... for WAN cuts". This directory + the
`branch-edge` compose profile is the first half (the edge proxy); the export
appliance is `backend/db/emergency_export_appliance.py` (see
`docs/operations-manual.md` § 3 and `docs/deployment.md`).

**Scoped down, like every other item in this repo that needs real
multi-site hardware/network to fully validate** (same class as P4.7's
Modality Worklist, P1.9's real TLS cert): there is no real second campus or
WAN link here to test against. What's actually buildable and built:

- **The edge config itself** (this directory + `docker-compose.yml`'s
  `branch-edge` profile) -- a real, `docker compose config`-validated
  topology, isolated on its own network, whose only path to patient data
  is a WAN hop to the central site.
- **Local static serving**: `branch-web` runs the exact same
  `clarion/web:local` image the central `web` service builds -- no
  separate build, no sync mechanism to invent or maintain. That's the
  entire "static/SPA off the WAN" win.
- **A WAN-degradation validation procedure** (`simulate-wan.sh` + re-run
  P5.2's Locust suite), buildable and runnable on one machine today,
  standing in for a real cross-campus test.

**Not built, and why:**
- **Redis** ("light edge proxy + Redis for static/SPA" in the original
  architecture sketch) -- turned out unnecessary once the edge simply runs
  the pre-built static image: nginx already serves those files natively,
  there's no cache-miss cost to amortize with a cache layer, and Caddy has
  no built-in Redis-backed HTTP cache module (would mean a custom Caddy
  build via xcaddy -- a new toolchain dependency for a cache with nothing
  to cache).
- **A real WAN validation run** -- needs the actual Main Campus↔Branch link
  (or at minimum two real hosts and a real network path between them);
  `simulate-wan.sh` is the closest same-machine substitute.
- **Central proxy `Caddyfile`'s `strict_sni_host on` interaction** with
  this edge's `header_up Host {upstream_hostport}` hop -- reasoned through
  (see the Caddyfile's own comment) but not verified against a live
  central instance; verify at commissioning before relying on it.

## Bring it up

```bash
# central stack already running (docker compose up -d)
docker compose --env-file .env.docker \
  -e CLARION_CENTRAL_BACKEND_ORIGIN=https://clarion.example.edu.my \
  --profile branch-edge up -d
```

`CLARION_CENTRAL_BACKEND_ORIGIN` has no default -- it must be the central
site's real, reachable public HTTPS origin. `CLARION_BRANCH_SITE_ADDRESS`
defaults to `localhost` for the demo, same pattern as the central proxy's
`CLARION_SITE_ADDRESS`.

## WAN-degradation validation

```bash
# 1. bring up branch-edge (above), confirm it's healthy
docker compose ps branch-proxy branch-web

# 2. inject Branch-WAN-like conditions (defaults: 40ms delay, 10ms jitter, 0.5% loss --
#    adjust to the University's actual measured Main Campus<->Branch figures once known)
./proxy/branch-edge/simulate-wan.sh add

# 3. point the existing load test at the edge instead of the central site
cd backend/loadtest && locust -f locustfile.py --host https://localhost:8443 --headless \
  -u 20 -r 2 -t 5m --csv wan-run

# 4. inspect wan-run_stats.csv: p95 latency, failure rate. Acceptance target
#    (fill in from the tender's own SLA once confirmed) -- provisionally: no
#    request failures, p95 < 3s for the SPA shell, uploads/thumbnails degrade
#    gracefully (P1.7b already sized the "web preview" variant specifically
#    to keep large originals off the Branch WAN -- this is the test that
#    validates that choice actually helps).

./proxy/branch-edge/simulate-wan.sh clear
```

Every P5.2 finding (Redis-outage fail-open, rate-limit fixes) already
applies here unchanged -- this is the same backend, just reached over a
slower link.
