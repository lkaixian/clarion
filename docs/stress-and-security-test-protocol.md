# CLARION stress, fault and security test protocol

Target: central node on Raspberry Pi 4 (64-bit OS, 2 GB RAM, 16 GB eMMC), Docker Compose
(`docker-compose.pi.yml`): internet -> Cloudflare -> `cloudflared` -> Caddy `proxy` -> `backend`
(gunicorn, 4 workers) -> `mariadb` / `minio` / `redis`; `mpi` beside them. Clients: web SPA, Flutter app.

Every test has: **Objective**, **Method**, **Pass/Fail**, **If it fails**. Thresholds reuse the paper's own
criteria (p95 server <= 100 ms, median RTT <= 1 s, max RTT <= 10 s, check-pass >= 99.9 %, uptime >= 99 %).
Run destructive tests (R, S, D groups) on a staging copy or in a declared maintenance window, never on the
live demo. Every run records: `vcgencmd measure_temp get_throttled`, `free -m`, `docker stats --no-stream`,
`iostat -x 1`, and the Locust CSV, into one timestamped folder, so each paper number is traceable.

## 0. Method and tooling

| Need | Tool | Why |
|---|---|---|
| Network shaping, kernel level | `tc qdisc ... netem` (+ `ifb` for ingress) | delay, jitter, loss, reorder, duplicate, rate; works per interface |
| Network shaping, per connection | Toxiproxy (`ghcr.io/shopify/toxiproxy`) | latency, bandwidth, slow_close, timeout, reset_peer, limit_data; scriptable per toxic |
| CPU / RAM / IO load | `stress-ng`, `fio`, `dd`, `cpulimit` | repeatable, bounded by timeout |
| Container limits | `docker update --memory --cpus`, compose `mem_limit` | prove limits, not just assume |
| Load + latency | Locust (`backend/loadtest`), `wrk2`, `hey` | wrk2 avoids coordinated omission; Locust gives the paper's RTT figures |
| Race tests | `pytest` + `asyncio.gather` / `httpx`, `curl --parallel`, Turbo-Intruder style single-packet bursts | many identical requests at the same instant |
| Security | `nmap`, `testssl.sh`, `trivy`, `lynis`, OWASP ZAP baseline, `mitmproxy`, `tcpdump`, `sqlmap` (staging only) | |
| Power loss | smart plug / relay, `echo b > /proc/sysrq-trigger` for hard reboot | |

Rules for valid numbers: warm up 60 s and discard it; run each scenario at least 3 times and report median and
worst; keep the load generator off the Pi; measure client RTT (Locust) and server time (Caddy/uvicorn log or
`/metrics`) separately, because the gap between them is the network. Report the 99th and max, not only the p95.

Scenario shorthand: **SERVER-side shaping** = applied on the Pi; **CLIENT-side shaping** = applied on the
load generator or phone; **BOTH** = both at once.

---

## A. Network degradation (throttling one side, or both)

Setup helper (Pi, run as root; `IF` is the uplink, usually `eth0`):

```bash
# netem.sh  -  usage: netem.sh <iface> "<netem args>" | netem.sh <iface> off
IF=$1
if [ "$2" = off ]; then tc qdisc del dev $IF root 2>/dev/null; tc qdisc del dev $IF ingress 2>/dev/null
  tc qdisc del dev ifb0 root 2>/dev/null; exit 0; fi
modprobe ifb numifbs=1; ip link set ifb0 up
tc qdisc replace dev $IF root netem $2                                  # egress  (Pi -> client)
tc qdisc replace dev $IF handle ffff: ingress
tc filter replace dev $IF parent ffff: protocol all u32 match u32 0 0 \
   action mirred egress redirect dev ifb0                               # ingress (client -> Pi)
tc qdisc replace dev ifb0 root netem $2
```

Always arm a dead-man switch before shaping over SSH: `( sleep 600; /root/netem.sh eth0 off ) &`.
Shape the Pi's uplink only for server-side tests; do not shape the interface your SSH session uses
without the switch.

| ID | Scenario | Method | Pass | If it fails |
|---|---|---|---|---|
| N1 | Baseline | Locust 50 users, 10 min, no shaping | p95 server <= 100 ms; median RTT <= 1 s; check-pass >= 99.9 % | fix before anything else |
| N2 | SERVER-side bandwidth cap 1 Mbit/s up/down | `netem.sh eth0 "rate 1mbit"` | login and `/readyz` still succeed; median RTT <= 3 s; no 5xx; static assets served compressed | enable Caddy `encode zstd gzip` on web, split big payloads, lazy-load SPA chunks |
| N3 | CLIENT-side bandwidth cap 256 kbit/s (3G-like) | same on the load generator, or Toxiproxy `bandwidth` | emergency scan and login complete within 10 s (the paper's max criterion); no server worker pinned | add timeouts + progress UI, shrink emergency payload |
| N4 | BOTH sides 200 ms +/- 50 ms, 1 % loss | netem on both | check-pass >= 99.9 %; zero duplicated writes (see R group); max RTT <= 10 s | tune Caddy/uvicorn keep-alive, client retry with backoff + idempotency key |
| N5 | High loss 10 % one side, then 10 % both | `loss 10%` | requests either succeed or fail cleanly (no hang > 10 s, no half-written record) | client request timeout, server `--timeout`, atomic transactions |
| N6 | Reorder + duplicate packets | `delay 100ms reorder 25% 50% duplicate 5%` | no application error; TCP absorbs | investigate only if errors appear |
| N7 | Asymmetric: upload dead, download fine | `loss 100%` on ingress only, 30 s | clients time out within 10 s; server logs no stuck requests; recovers within 5 s after removal | request body timeout in Caddy (`read_body`), gunicorn `--timeout` |
| N8 | Slow client / Slowloris | `slowhttptest -c 500 -H -i 10 -r 100 -t GET -u https://HOST/api/healthz` | legit requests still served; Caddy drops slow headers at its configured timeout; backend workers never occupied | tighten `servers { timeouts { read_header ... } }`, Cloudflare rate rules |
| N9 | Hard blackout then restore | `loss 100%` 60 s -> off | no restart of any container; recovery of first request <= 5 s; WebSocket/long poll reconnects | check cloudflared reconnect, Docker DNS, client retry |
| N10 | Tunnel outage | `docker stop cloudflared` 2 min -> start | site down only for that period; auto reconnect <= 30 s; no data loss at origin | `restart: unless-stopped`, run two tunnel replicas, alert on tunnel health |
| N11 | DNS failure for upstream calls | block `53` egress from backend | emergency scan and login unaffected (no external dependency in the hot path); NIH RxClass calls degrade, not fail | cache, short DNS timeout, offline path |
| N12 | Offline-first check (mobile) | airplane mode, scan NFC tag | on-tag sealed record opens with zero network; read log queued; uploads on reconnect, no loss, no duplicate | fix queue persistence, dedupe by log hash chain |

Latency attribution for the paper's single 19,208 ms outlier (Run 2): rerun Run 2's scenario with
`wrk2 -R` fixed rate and record per-request timestamps; correlate each > 5 s request with (a) `vcgencmd
get_throttled`, (b) `docker stats` memory/swap, (c) `iostat` await, (d) Caddy and cloudflared logs, (e) the
client's DNS/TLS/connect timings (`curl -w` with `time_namelookup time_connect time_appconnect
time_starttransfer`). The outlier is explained when exactly one of these shows a spike at that timestamp.
Report which, instead of "once".

---

## B. Hardware resource pressure (Pi 4, 2 GB)

Apply load while running a **constant probe**: `Locust` 20 users on the critical path (login, emergency scan,
patient list). The pass criterion is always "critical path stays within the paper's thresholds or degrades
predictably", plus no core container killed.

| ID | Scenario | Method | Pass | If it fails |
|---|---|---|---|---|
| H1 | CPU saturation | `stress-ng --cpu 4 --cpu-method matrixprod --timeout 600s` | probe median <= 1 s; p95 server <= 250 ms; `get_throttled` = `0x0` | add heatsink/fan; limit workers to 3; `nice` batch jobs; cgroup `cpus` on exporter/backups |
| H2 | CPU + thermal soak | H1 for 30 min in a closed case, then open | temp < 80 C (soft limit 80, hard 85); no `0x50005` flags | passive -> active cooling; lower `arm_freq` or governor |
| H3 | Thread starvation | `stress-ng --cpu 8 --cpu-load 100` (more hogs than cores) | emergency scan p95 <= 500 ms | raise service priority (`CPUWeight`, `cpu_shares`), cap noisy services |
| H4 | RAM pressure, no OOM | `stress-ng --vm 2 --vm-bytes 60% --timeout 300s` | probe works; swap used but `si/so` (vmstat) < 100 pages/s sustained | add `zram` (not SD swap), lower mariadb `innodb_buffer_pool_size`, gunicorn workers 4 -> 2 |
| H5 | RAM exhaustion, OOM killer | `stress-ng --vm 1 --vm-bytes 110% --oom-pending` (staging) | `dmesg` kill victim is the stressor, not mariadb/backend/proxy; all core containers still `running`; DB consistent after (`mariadb-check`) | set `oom_score_adj` (-900 mariadb, +500 observability), `mem_limit` per service, remove memory-hungry profiles on the Pi |
| H6 | Container memory ceiling | `docker update --memory 256m backend`, then Locust | backend restarts cleanly if killed (`restart: unless-stopped`), no data loss, `RestartCount` increments by <= 1 | tune `--max-requests`, find leak with `tracemalloc` |
| H7 | Memory leak soak | Locust 24 h moderate load; sample RSS every minute | RSS growth < 5 %/12 h per container | recycle workers (`--max-requests` + jitter already in), fix leak |
| H8 | IO saturation (writes) | `fio --name=w --rw=randwrite --bs=4k --size=1g --iodepth=16 --runtime=300 --time_based --direct=1` on the eMMC | probe p95 server <= 250 ms; mariadb commit latency < 100 ms; iowait recorded | `innodb_flush_log_at_trx_commit` review, `ionice -c3` backups, move MinIO objects to external SSD |
| H9 | IO saturation (mixed + sync) | `fio --rw=randrw --rwmixread=70 --fsync=1` | no DB stall > 2 s; no `InnoDB: long semaphore wait` in log | separate volumes, lower flush pressure |
| H10 | Disk full | `fallocate -l <free-1G> /var/lib/docker/fill.bin` | backend returns clean 503/507 on uploads, DB read still works, `/readyz` flags it, alert fires at 75 % / 90 %; after deleting the file service recovers without manual repair | quota per volume, reserve space, prune job, MariaDB `innodb_data_file_path` autoextend limit |
| H11 | eMMC write endurance | before/after 24 h: `smartctl -a /dev/mmcblk0` or `mmc extcsd read /dev/mmcblk0 | grep -i life`; `iostat -d` sectors written | extrapolated write volume keeps life estimate > 5 years; log + DB writes < 5 GB/day | `log2ram` or tmpfs for logs, lower DB binlog, `journald Storage=volatile`, `noatime` |
| H12 | Under-voltage | `vcgencmd get_throttled` during H1 | bit 0/16 not set | official 5.1 V 3 A supply, short cable |
| H13 | Combined worst case | H1 + H4 (60 %) + H8 + N4 together | emergency scan still <= 10 s, auth still correct, no 5xx > 0.1 % | this is the headline "degraded but safe" result; if it fails, shed load (disable observability profile, reduce workers) |

---

## C. Race conditions (application)

Method for all: fire N identical requests at the same instant from one process with a barrier
(`asyncio.gather` + `httpx.AsyncClient`, HTTP/2 single-connection for a tighter burst, and a second variant
from two hosts), then assert on the database, not on the HTTP status. Run each on SQLite (demo) **and**
MariaDB (production), because `SELECT FOR UPDATE` is a no-op on SQLite and the project already relies on
`payments._lock`.

```python
# race.py  - run with: python race.py <url> <token> <n>
import asyncio, httpx, sys
async def burst(method, url, n, **kw):
    async with httpx.AsyncClient(http2=True, verify=False, timeout=30) as c:
        go = asyncio.Event()
        async def one():
            await go.wait(); return await c.request(method, url, **kw)
        tasks = [asyncio.create_task(one()) for _ in range(n)]
        await asyncio.sleep(0.2); go.set()
        return await asyncio.gather(*tasks, return_exceptions=True)
```

| ID | Scenario | Assertion (pass) | If it fails |
|---|---|---|---|
| R1 | 20 parallel payment webhook deliveries for one intent | exactly 1 `Payment` row; ledger total equals bill amount | enforce unique constraint on `(intent_id)`; keep `settle_intent` compare-and-set |
| R2 | 20 parallel "pay bill" posts, same bill, different intents | sum of payments <= bill total; no negative balance | lock bill row (`payments._lock`) in the same transaction |
| R3 | Refund approval raced by 2 different admins, and by requester + approver | one refund; requester cannot approve own; status transitions once | conditional `UPDATE ... WHERE status='pending'` and check rowcount |
| R4 | Double booking: 20 patients book the same slot | exactly 1 booking, rest get 409 | DB unique constraint on (doctor, slot) (already added; verify on MariaDB) |
| R5 | Room claim: 2 staff claim one room | one active claim (generated-column unique) | verify unique index exists after migration |
| R6 | Purchase order receipt: same line received twice in parallel | stock increased once | per-line compare-and-set; SQL arithmetic in `_apply_restock` |
| R7 | Stock decrement: 30 dispenses against stock 10 | stock never < 0; exactly 10 succeed | `UPDATE ... SET qty=qty-n WHERE qty>=n` |
| R8 | Refresh-token rotation race: same refresh token used 5x at once | exactly 1 new token pair; others rejected; reuse of a rotated token revokes the family | rotate inside a transaction with conditional update |
| R9 | Login lockout race: 50 wrong passwords in parallel | lockout counter reaches threshold exactly once, cannot be bypassed by parallelism; correct password afterward is refused until lockout ends | atomic `UPDATE failed=failed+1` |
| R10 | Rate-limit race: 200 requests at once to a 10/min endpoint | <= limit succeed (+ small documented tolerance), rest 429 | Redis `INCR` atomic; check fallback in-memory path with 4 workers |
| R11 | Patient registration with same NRIC x 20 | one patient; others 409 | unique normalised NRIC index |
| R12 | Concurrent clinical-record edit (two clinicians) | no lost update; second gets 409 or merges via version column | optimistic `version` check |
| R13 | Sign-off while the patient is being merged/deleted | no orphan rows; FK errors return 409 not 500 | transaction ordering, FK `ondelete` |
| R14 | Federation fetch while origin visit is updated | fetched content hash matches origin's signed hash or fetch fails closed | verify-then-use, never partial |
| R15 | Offline-read log upload twice, concurrently | hash chain stays valid; duplicate entries ignored | unique on chain hash |

### C2. Race conditions specific to degraded networks

These are the cases a clean LAN never shows. Each is run with netem N4/N5 applied.

| ID | Scenario | How | Pass | If it fails |
|---|---|---|---|---|
| RN1 | **Timeout-then-retry duplicates a write.** Server commits, response is lost (loss 100 % on the egress for the response window), client times out and retries | Toxiproxy `timeout` toxic after upstream request, downstream direction; POST payment/booking/register with the same body | exactly one record after retry; retry returns the original result | require `Idempotency-Key` header on all non-idempotent POSTs, store key + response for 24 h |
| RN2 | **Lost refresh response.** Server rotates the refresh token, response never reaches client, client retries with the old token | `limit_data`/`reset_peer` on the downstream of `/auth/refresh` | user is NOT logged out for a single lost response (grace window of a few seconds for the previous token), but a replay after the grace window revokes the family | add short rotation grace period; this is a real UX/security trade-off, document it in the paper |
| RN3 | **Slow upload overlapping a second submit.** User taps twice on a 256 kbit/s link | N3 + UI double tap (Playwright) | button disabled while pending; server still creates one record | disable on submit + idempotency key |
| RN4 | **Out-of-order responses.** Request A slow, request B fast; UI shows A's stale data last | netem `delay 2s` on first request only (Toxiproxy per-connection) | UI shows the newest request's result (the stale-response race fixed earlier must not return) | sequence counter / abort previous request with `AbortController` |
| RN5 | **Token expiry during a slow request.** 15-min access token expires mid-upload | start upload at minute 14:50 on a 100 kbit/s link | upload completes or fails cleanly and refresh-and-retry replays once; no duplicate | check interceptor replays idempotent requests only once |
| RN6 | **Two tabs/devices refreshing at once on a flaky link** | 2 clients, same session, loss 5 % | both end authenticated or one cleanly re-logs-in; no infinite refresh loop | single-flight refresh in client |
| RN7 | **Webhook retries from the gateway during a network brownout** | replay signed webhook 10x with delays 0-5 s under loss | single settlement; bad signature rejected; old timestamp rejected | signature + timestamp + intent state CAS |
| RN8 | **Half-open connection** (peer vanishes) | `iptables -I OUTPUT -p tcp --sport 443 -j DROP` mid-request | server frees the worker after its timeout (<= configured), no leak in `ss -s` | keep-alive and gunicorn timeouts, Caddy `idle` timeout |
| RN9 | **Retry storm** after N9 blackout ends | 100 clients retry simultaneously | recovery without cascading 5xx; clients use jittered exponential backoff | add jitter, cap retries, 429 with `Retry-After` |
| RN10 | **Offline write queue replay** (mobile) after N12 | queue 50 events offline, reconnect on a lossy link | server ends with exactly 50, in order, none duplicated | client-generated UUID per event, server dedupe |

---

## D. Reliability, persistence, availability (the "81 % uptime" row)

The paper's weakest row is uptime (about 81 %, 5.7 days off; 99.5 % after 23 October). It needs a
**classified outage log**, not a single percentage. Add an external probe (UptimeRobot / a second machine
curling `/healthz` every 30 s) and classify every gap as: power, Pi/OS, Docker, tunnel/Cloudflare, application,
deliberate maintenance. Report availability with and without planned maintenance.

| ID | Scenario | Method | Pass | If it fails |
|---|---|---|---|---|
| D1 | Container kill | `docker kill -s KILL backend` (each service in turn) | back and healthy in <= 30 s, no manual action | `restart: unless-stopped` + `healthcheck`, `depends_on: condition: service_healthy` |
| D2 | Process crash inside container | `docker exec backend kill -9 1` / kill one gunicorn worker | master re-spawns the worker; no request error beyond in-flight ones | gunicorn arbiter, `--max-requests` |
| D3 | Docker daemon restart | `systemctl restart docker` | all containers return; cloudflared reconnects <= 60 s | `live-restore: true`, restart policies |
| D4 | Clean reboot | `sudo reboot` | full stack serving <= 3 min; DB consistent | systemd unit ordering, wait-for-DB |
| D5 | **Hard power loss x 20** | smart plug cycles while Locust writes (create patients/payments) | after every boot: MariaDB starts without manual recovery; `mariadb-check` clean; acknowledged writes present; no half-applied payment | `innodb_flush_log_at_trx_commit=1`, `sync_binlog`, UPS/supercap HAT, ext4 `data=ordered`, avoid SD for DB |
| D6 | Persistence across `down/up` | `docker compose down && up`, compare checksums of patients/payments/objects | identical | named volumes only, never anonymous |
| D7 | Volume corruption injection | truncate a MinIO object; flip a byte | `ObjectStore.get_checked` sha256 mismatch is detected and refused | already implemented; verify alert |
| D8 | Backup restore drill | restore the latest `age`-encrypted backup to a clean machine | RTO <= target, RPO <= backup interval, row counts match | fix runbook, test monthly |
| D9 | Watchdog | `echo c > /proc/sysrq-trigger` (kernel panic) / freeze the Pi | hardware watchdog (`dtparam=watchdog=on`, systemd `RuntimeWatchdogSec=15`) reboots within 1 min | enable watchdog |
| D10 | Log rotation | `docker inspect -f '{{.HostConfig.LogConfig}}'` for each service; generate 1 GB of logs | `json-file` with `max-size=10m max-file=3` on every service; journald capped (`SystemMaxUse=200M`); logrotate runs for host files | add `logging:` to compose defaults, `x-logging` anchor |
| D11 | Long soak | 7 days normal load with the external probe | availability >= 99.5 % excluding declared maintenance; zero unexplained gaps | classify each gap and fix the top cause |
| D12 | Time sync loss | stop `chrony`, skew clock 10 min | JWT/webhook timestamps behave deterministically (reject, not crash) | NTP + monitor |

---

## E. Security: network, TLS, cookies, application

### E1. Cookie handling and sniffing (the refresh token cookie)

| ID | Test | Method | Pass | If it fails |
|---|---|---|---|---|
| CK1 | Cookie attributes | `curl -sSI -c - https://HOST/api/auth/login ...`; inspect every `Set-Cookie` | refresh cookie: `HttpOnly; Secure; SameSite=Strict` (or Lax with justification), `Path` limited to `/api/auth`, finite `Max-Age`, ideally `__Host-` prefix | fix `set_cookie` in `auth_router.py` |
| CK2 | No cookie over plaintext | `curl -i http://HOST/...` and sniff `tcpdump -A -i any port 80` while logging in via an `http://` link | HTTP redirects 308 before any cookie is read or set; no `Set-Cookie` on the HTTP response | redirect-only port 80, HSTS |
| CK3 | Sniffing on the wire | `tcpdump -i eth0 -w c.pcap port 443` + Wireshark | no cookie, token or NRIC visible in plaintext (TLS only) | n/a if TLS holds; check no HTTP leg between cloudflared and Caddy |
| CK4 | **Internal-leg sniffing** | `tcpdump` on the docker bridge between cloudflared, proxy, backend | cloudflared -> Caddy leg is TLS (it is, via the Caddy root CA); Caddy -> backend is on an isolated network; document the residual cleartext hop | TLS or mTLS on the last hop if the threat model includes the Pi host |
| CK5 | HSTS stripping / downgrade | `sslstrip`/`mitmproxy --mode transparent` on a LAN test rig; first visit over http | with max-age 300 s the protection is weak: record it. With a 1-year max-age + `includeSubDomains`, a returning browser refuses http | raise HSTS max-age (the paper's "HSTS too short" finding); only after TLS is confirmed stable |
| CK6 | Token in URL / storage | grep SPA for `localStorage.setItem` of tokens; check access token never in query strings or logs | refresh token not reachable from JS; access token in memory only | move to memory, scrub logs |
| CK7 | Session fixation / replay | log in, copy cookie, replay from another IP and User-Agent; then after logout | replay after logout = 401; refresh-token reuse revokes the family | server-side revocation list (exists), bind to device optionally |
| CK8 | CSRF on cookie-auth endpoints | cross-origin form POST to `/auth/refresh` and `/auth/logout` from a different origin | blocked by SameSite and CORS (credentials only for the allowed origin; no wildcard with credentials) | strict CORS allowlist, `Origin` check, CSRF header |
| CK9 | XSS cookie theft attempt | inject `<img onerror=fetch(...document.cookie)>` into free-text fields (notes, bio, announcements) | payload rendered inert; cookie unreadable | output encoding, CSP `script-src 'self'` |
| CK10 | Subdomain cookie scope | inspect `Domain` attribute | no `Domain=` (host-only) | remove Domain |
| CK11 | Cookie on cached responses | `Cache-Control` on auth responses and Cloudflare cache status | `no-store` on anything with `Set-Cookie`; `CF-Cache-Status: DYNAMIC/BYPASS` | `Cache-Control: no-store`, Cloudflare cache rule bypass for `/api/*` |

### E2. Transport, headers, exposure

| ID | Test | Method | Pass | If it fails |
|---|---|---|---|---|
| T1 | TLS audit | `testssl.sh --severity MEDIUM https://HOST` | TLS 1.2/1.3 only; no RC4/3DES/CBC-SHA1 weak; A/A+ | edit Caddy `tls` protocols/ciphers |
| T2 | Headers | `curl -sI https://HOST/` + `curl -sI https://HOST/api/healthz` | HSTS (>= 1 year for production, 300 s only in demo), CSP, X-Frame-Options DENY, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP/CORP; no `Server`/`X-Powered-By` | `proxy/Caddyfile` (`CLARION_HSTS`) |
| T3 | Redirects | `curl -sI http://HOST/` | 308 to https, no content served | |
| T4 | Port exposure | from outside: `nmap -sS -sU -p- PI_PUBLIC_IP`; on the Pi: `ss -tlnp`, `docker ps --format '{{.Names}} {{.Ports}}'`, `iptables -S DOCKER-USER` | only the tunnel is reachable from the internet; 3306, 9000, 6379, 2575, 8000 not reachable from LAN unless intended; DB/MinIO bound to `CENTRAL_BIND_IP` only | bind to 127.0.0.1 / private IP; add `DOCKER-USER` DROP rules (Docker bypasses ufw) |
| T5 | Internal segmentation | `docker run --rm --network <edge> nicolaka/netshoot nc -zv mariadb 3306` | edge network cannot reach data tier; DB rejects no-password / wrong-account connections; Redis requires `requirepass`; MinIO rejects anonymous | network split, per-service accounts |
| T6 | Metrics / readyz exposure | `curl https://HOST/api/metrics /api/readyz` | 404/403 from the public side | Caddy block rule |
| T7 | Cloudflare origin bypass | request the Pi's origin IP directly with `Host:` header | origin refuses non-tunnel traffic | no public origin port at all |

### E3. Application attack surface

| ID | Test | Method | Pass |
|---|---|---|---|
| A1 | Broken access control matrix | table of role x endpoint (patient, doctor, nurse, pharmacist, cashier, admin, other-facility staff, anonymous); script asserts expected 200/403/404 | 100 % of forbidden requests refused (paper: 9 of 9; extend to the full matrix, hundreds of cases, generated from the route table) |
| A2 | IDOR | iterate patient/bill/receipt/document ids with another user's token | 404/403, cross-facility attempts audit-logged |
| A3 | Rate limit + lockout | 200 logins/min from one IP; then via spoofed `X-Forwarded-For` | 429; spoofed header ignored |
| A4 | Injection | `sqlmap --level 3 --risk 1` on staging; ZAP active scan; NoSQL/LDAP filter injection strings in the LDAP login | no findings |
| A5 | Path traversal / uploads | `../../etc/passwd`, `%2e%2e%2f`, zip-slip, polyglot images, oversized upload, wrong MIME | rejected; files never served from a user-controlled path; EXIF stripped |
| A6 | Info leakage | trigger 404/500/validation errors; check stack traces, framework banners, `/docs`, `/openapi.json`, `.git`, `.env`, backup files | none exposed in production |
| A7 | JWT | `alg=none`, expired, wrong key, tampered claims | all rejected |
| A8 | SSRF / open redirect | URL fields (webhooks, registry base URL) pointing to `169.254.169.254`, `http://mariadb:3306` | blocked |
| A9 | Brute force, host level | `hydra -l admin -P rockyou.txt ssh://PI` | fail2ban bans after N attempts; password auth disabled |
| A10 | SSH hardening | `ssh -o PreferredAuthentications=password`, `ssh root@PI`; `sshd -T | egrep 'permitrootlogin|passwordauthentication'` | both refused; keys only |
| A11 | Dependency / image scan | `trivy image <each image>`, `trivy fs backend/`, `pip-audit`, `npm audit`, `lynis audit system` | no unpatched CRITICAL; HIGH triaged with owner and date |
| A12 | Secrets in repo and env | `gitleaks detect`, `docker inspect` env check | none; `.env` files 0600 |
| A13 | Audit-log integrity | attempt `UPDATE/DELETE` on `audit_logs` as the app account | trigger refuses |
| A14 | Tag crypto | tamper with ciphertext, replay old tag, wrong key | AES-GCM auth fails; replays visible in the offline read log (note: NTAG213/215 have no tamper-proof counter, state this limit) |

---

## F. Mapping to the paper's table

| Paper row | Strengthen with | Status to aim for |
|---|---|---|
| Automated test pass rate (988/988) | add R, RN, CK, A groups as automated pytest/CI jobs; run the suite on SQLite **and** MariaDB; report flaky re-run (the AI-setting one) as a fixed dependency on config, not luck | Met |
| Server processing p95 <= 100 ms | repeat under H1, H4, H8, H13; report the worst case, not only the idle case | Met under load |
| Client RTT median / slowest | repeat under N2-N5; attribute the 19,208 ms outlier (section A) | slowest -> Met or explained |
| Check-pass rate >= 99.9 % | keep during H13 and N4 | Met |
| Uptime >= 99 % | classified outage log + D1-D12, hardware watchdog, UPS; report 99.5 % post-23 Oct with the explanation of the 5.7 days | Not met -> Partly met with root cause and fix |
| Access control 9/9 | full matrix A1/A2 | Met, N cases |
| Rate limiting | A3 + R10 including the multi-worker and Redis-down fallback | Met |
| Security headers (HSTS short) | T2 with production HSTS value; CK5 | Met after raising HSTS |

Suggested new rows for the table: *Race-condition suite (duplicate writes = 0)*, *Degraded-network suite
(duplicate writes = 0 at 10 % loss)*, *Cookie flags and plaintext leak (0 findings)*, *OOM/disk-full
behaviour (core services alive)*, *Hard power-loss recovery (20/20 clean boots)*.

## G. Suggested run order and scripts layout

1. D5 first on a staging Pi (finds corruption risk early), then B, then A, then C and C2 (use A's shaping),
   then E, then D11 (7-day soak) last.
2. Keep scripts in `qa/stress/`: `netem.sh`, `race.py`, `toxiproxy_scenarios.py`, `collect.sh` (temperature,
   free, docker stats, iostat to CSV every 5 s), and one `run_all.sh` that writes a results folder per run.
3. Gate: CI runs C, CK1/CK6/CK8, A1-A7 on every merge (no root, no hardware needed); hardware groups B/D and
   network groups A/N run per release on the Pi.

## H. Caveats to state in the paper

- netem shapes this host's interface, so it models the last mile, not Cloudflare's path; say so.
- A single load generator behind one IP shares one rate-limit bucket, so it cannot reach the DB-pool
  ceiling (already noted for the earlier Locust run); use two generators or a staging-only bypass.
- OOM, disk-full and power-loss tests damage state by design; staging only, with a verified backup.
- NTAG213/215 offline reads cannot be made tamper-proof without NTAG 424 DNA hardware; report as residual risk.
