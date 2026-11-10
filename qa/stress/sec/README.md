# qa/stress/sec - live-URL security suite (protocol section E)

Target: Pi 4 / Ubuntu 22.04, Cloudflare tunnel -> Caddy -> FastAPI. Deps: `pip install httpx pytest`; curl, bash;
optional nmap, tcpdump, testssl.sh, trivy, pip-audit, lynis, gitleaks, fail2ban. All probes are non-destructive;
credentials come from env only.

```
BASE_URL=https://clarion.example.com SEC_USER=... SEC_PASS=... ./run_sec.sh          # from any machine
sudo -E ./run_sec.sh --host                                                          # on the Pi, adds sniff/exposure/host
```

| File | Tests | Needs |
|---|---|---|
| `test_cookies.py` | CK1-CK11, HSTS value | BASE_URL, SEC_USER/PASS (no-MFA account) |
| `test_transport_headers.py` | T1 (stdlib TLS floor), T2, T3, T6, T7 | BASE_URL; T7 needs ORIGIN_IP |
| `tls_audit.sh` | T1 via testssl.sh JSON | testssl.sh (skips otherwise) |
| `test_app_attack.py` | A1-A8, A12, A13 | see below |
| `sniff_cookies.sh` | CK2-CK5 pcap leak scan | root on the Pi, tcpdump |
| `exposure_scan.sh` | T4, T5 | root on the Pi, docker; nmap for `TARGET=<ip>` |
| `host_audit.sh` | A9-A11, A12 perms | root on the Pi |

Env: `API_PREFIX` (default `/api`), `SEC_INSECURE=1` (self-signed origin), `APP_ENV=demo` (short HSTS becomes xfail),
`SEC_BEHIND_CF=1` (default; `Server: cloudflare` accepted), `SEC_OUT` (results dir).

## What skips without env
- No `BASE_URL`: everything skips. No `SEC_USER/PASS`: all cookie and JWT tests that need a session.
- Role matrix / IDOR: `SEC_{ADMIN,CLINICIAN,PHARMACIST,RECEPTIONIST,PATIENT,OTHERFAC}_USER/_PASS`; IDOR also
  `SEC_FOREIGN_PATIENT_ID` (and `SEC_FOREIGN_BILL_ID`, ... any path-param name) = an id those users must not see.
- A3 burst (locks your IP out ~1 min): `SEC_RUN_BURST=1`. Upload abuse: `SEC_UPLOAD=/path:field`. SSRF: `SEC_SSRF='PUT /path field;...'`
  plus admin creds (a 2xx would store the URL, hence opt-in). CK6b log grep: `SEC_LOG_CMD='docker compose -f docker-compose.pi.yml logs --since 10m proxy backend'`.
  A12 container env: `SEC_DOCKER=1`. A13: `MARIADB_APP_PASSWORD` (+ `MARIADB_DATABASE`), on the Pi.
- Without a reachable `/openapi.json` (the edge blocks it) the A1 matrix imports `app.main` in-process against a
  throwaway SQLite (needs backend deps in the Python running pytest); or set `SEC_OPENAPI_FILE`.
- The 60/min global limiter paces A1 (`SEC_MATRIX_DELAY`, default 1.1 s/request, so hundreds of routes take minutes).

## Reading results
`xfail` = a known, named gap (HSTS short in demo, no `__Host-` prefix, cookie honoured with foreign Origin).
`FAIL` = a finding; the assertion message says the fix. CSVs: `public_routes.csv`, `role_matrix.csv`, `ssrf_candidates.csv`.
Behind Cloudflare, T1 and some header results describe Cloudflare's edge; use `ORIGIN_IP`/`tls_audit.sh ORIGIN:443`
from the LAN for Caddy itself.
