# Pi network baseline, 2026-11-12

Measured on the production Pi (`uthm-pr-emos-0g12`, compose project `clarion-pi`, all 8 services healthy, idle load)
with `qa/stress/pi/speedtest_baseline.sh`. Pi results folder: `results/20261112-140432/`.

## Method

| Path | How | Size |
|---|---|---|
| 1. Pi to internet (modem) | 4 parallel curl streams to Cloudflare speed endpoints, mean of 3 runs | download 4 x 25 MB, upload 4 x 10 MB per run |
| 2. Pi to 1.1.1.1 and 8.8.8.8 | `ping`, 20 packets, 0.2 s apart | 20 packets each |
| 3. Pi to tunnel | one fresh HTTPS request per iteration to `https://clarion.larmkx.com/api/healthz`, 0.2 s pause | 60 s, 90 requests |
| 4. Pi to origin (control) | same as 3 but `--resolve clarion.larmkx.com:443:172.29.0.2`, which goes straight to Caddy and skips Cloudflare and cloudflared | 30 s, 103 requests (60 succeeded, see note) |

Latency figures are client round trip time, not server time.

## Results

| Measure | Value |
|---|---|
| Download (to Cloudflare) | 366.0 Mbit/s |
| Upload (to Cloudflare) | 52.5 Mbit/s |
| Ping 1.1.1.1 | avg 28.7 ms (min 24.2, max 39.2), 0% loss |
| Ping 8.8.8.8 | avg 22.7 ms (min 18.2, max 30.1), 0% loss |
| Tunnel `/api/healthz` | avg 434.6 ms, median 300.9, p95 1040.3, p99 1240.5, max 1240.5; 90 of 90 succeeded |
| Origin (Caddy) `/api/healthz` | avg 47.3 ms, median 46.0, p95 55.0, p99 91.8, max 94.7; 60 successful requests |

Origin-run raw line: `n=103 fail=43 5xx=0`, 60 x HTTP 200 and 43 x HTTP 429.
That run repeated the speed and ping tests too (download 311.8, upload 52.0 Mbit/s, ping within 1 ms of the above).

### Where the tunnel time goes (average of 90 requests, 435 ms)

| Phase | ms |
|---|---|
| DNS | 34 |
| TCP connect | 65 |
| TLS | 117 |
| Wait for first byte | 218 |
| Download | 1 |

The five slowest requests (1.04 to 1.24 s) had normal DNS, TCP and TLS times and a first-byte wait of about 0.7 to 0.8 s.

## Findings

1. The modem line is healthy: 366 / 52 Mbit/s, 23 to 29 ms to public resolvers, no packet loss.
2. The Pi and backend are not the bottleneck. Straight to Caddy the request takes 47 ms average, 55 ms p95, with no tail.
3. Going through Cloudflare and the tunnel adds about 390 ms on average (435 vs 47) and a long tail (p95 1040 ms). That cost sits on the Cloudflare edge and tunnel path, not on the Pi.
4. About half of the tunnel time per request is connection setup (216 ms). Browsers reuse connections, so users mostly see the first-byte wait, not the setup. The probe opens a new connection each time.
5. The app's per-IP rate limit works at the origin: exactly 60 requests succeeded, then HTTP 429.

## Notes and limits

- The 43 failures in the origin run were HTTP 429 from the 60 requests per minute per-IP limit, not server errors. The probe sent about 200 requests per minute.
- The default probe rate (`PROBE_GAP=0.2`) exceeds that limit, so the stress scenarios must run with `PROBE_GAP=1.1` (about 54 requests per minute) or their p95 and ok% will be polluted by 429s.
- The tunnel and origin runs were one session each, not repeated at different times of day. Treat the tunnel tail (p95, p99, max) as indicative: 90 samples is a small sample.
- Tunnel throughput was not measured (`TUNNEL_DL_PATH` not set); only latency through the tunnel was.
- Not measured: server-side time (needs Caddy logs or `/metrics`), which Cloudflare edge location serves the Pi, and behaviour under load.

## Production Pi: CPU stress (H1, H3, H12), 2026-11-12

Probe: origin path (`--resolve clarion.larmkx.com:443:172.29.0.2`, goes straight to Caddy), `PROBE_GAP=1.1`. Pi results folder: `results/20261112-142259/`.

| Test | Load | n | Median | p95 | p99 | Max | Failed | New throttle bits |
|---|---|---|---|---|---|---|---|---|
| idle (reference) | none | 60 | 46.0 ms | 55.0 ms | 91.8 ms | 94.7 ms | 0 | n/a |
| H1 | `stress-ng --cpu 4 --cpu-method matrixprod`, 600 s | 467 | 85.1 ms | 113.3 ms | 126.3 ms | 137.0 ms | 0 | none |
| H3 | `stress-ng --cpu 8 --cpu-load 100`, 300 s | 224 | 105.1 ms | 141.5 ms | 187.5 ms | 211.7 ms | 0 | not checked |
| H12 | `stress-ng --cpu 4 --cpu-method matrixprod`, 120 s | 93 | 83.8 ms | 110.5 ms | 153.1 ms | 153.1 ms | 0 | none |

Thresholds met: H1 median at most 1000 ms, ok% at least 99.9, p95 at most 250 ms; H3 p95 at most 500 ms. All 6 checks passed.

- Full CPU load roughly doubles origin latency (p95 55 ms idle to 113 to 141 ms) and causes no failures.
- No under-voltage or thermal throttling in H1 or H12 (`get_throttled` 0x0 before and after).
- Latency is client round trip, not server time.

### Skipped on production, with reasons

| Test | Why skipped |
|---|---|
| H4 (memory pressure, 60% of RAM) | 714 MB available of 1849 MB with 283 MB swap in use; risk of OOM-killing MariaDB or the backend |
| H6 (backend 256 MB cap) | same memory headroom |
| H8, H9 (fio, 1 GB files) | root disk 15 GB, 2.6 GB free (82% used) after cleanup |

The 15 GB root disk at 82% use and about 700 MB free RAM with the full stack up are findings in themselves.

### Config checks D9 and D10 (read-only, before `setup_pi.sh --apply`)

D9: watchdog device present (PASS); `RuntimeWatchdogSec` not set and `dtparam=watchdog=on` missing (FAIL).
D10: no log rotation on any of the 8 containers (8 FAIL); journald has no `SystemMaxUse` cap (FAIL), 168 MB in use.

## Production Pi: network scenarios, 2026-11-12

Shaping inside the cloudflared container only (`NS_CONTAINER=clarion-pi-cloudflared-1`, so SSH and other traffic are untouched).
Probe: public URL `https://clarion.larmkx.com/api/healthz` through the Cloudflare tunnel, `PROBE_GAP=1.1`. Pi results folder: `results/20261112-145111/`.

### N1: unshaped control (60 s warm-up discarded, then 600 s)

| Phase | n | Median | p95 | p99 | Max | Failed |
|---|---|---|---|---|---|---|
| warm-up (not scored) | 39 | 314.3 ms | 865.9 ms | 1997.1 ms | 1997.1 ms | 0 |
| N1 | 402 | 302.0 ms | 607.9 ms | 746.1 ms | 1220.6 ms | 0 |

Thresholds: median at most 1000 ms (PASS, 302.0), ok% at least 99.9 (PASS, 100.000).

- Matches the earlier tunnel baseline (median 301 ms, p95 1040 ms, max 1240 ms): the tail is the Cloudflare path, not the Pi.
- p99 on the warm-up is the single slowest of 39 requests, not a separate finding.
- Latency is client round trip, not server time.
- A first attempt at N2 aborted before shaping anything (wrong container name `cloudflared`, real name `clarion-pi-cloudflared-1`); no shaping was applied and the qdisc was verified clean.

### N2 to N7: shaped runs (60 s probe each; N7 30 s)

Pi results folder for this run: `results/20261112-150512/`. Run summary: **15 passed, 0 failed, 0 skipped**.
Shaping applied to both directions inside cloudflared (egress `netem`, ingress redirected through an `ifb` device) unless noted.

| Scenario | Shaping | n | Median | p95 | p99 | Max | Failed | Checks |
|---|---|---|---|---|---|---|---|---|
| N1 (control) | none | 402 | 302.0 ms | 607.9 ms | 746.1 ms | 1220.6 ms | 0 | median 302 (limit 1000), ok% 100 |
| N2 | 1 Mbit/s | 38 | 343.8 ms | 818.6 ms | 1272.4 ms | 1272.4 ms | 0 | median 344 (limit 3000), 5xx 0, static asset served compressed, login 1073 ms (limit 3000) |
| N3 | 256 kbit/s | 37 | 427.1 ms | 812.9 ms | 1018.5 ms | 1018.5 ms | 0 | max 1018 (limit 10000), scan-path max 841 ms (limit 10000), login 1186 ms (limit 10000) |
| N4 | 200 ms delay, 50 ms jitter, 1% loss | 26 | 1140.5 ms | 1369.0 ms | 2204.0 ms | 2204.0 ms | 0 | ok% 100 (limit 99.9), max 2204 (limit 10000) |
| N5a | 10% loss, outbound only | 38 | 312.8 ms | 1188.5 ms | 1253.4 ms | 1253.4 ms | 0 | max 1253 (limit 11000) |
| N5b | 10% loss, both directions | 40 | 323.0 ms | 626.3 ms | 920.4 ms | 920.4 ms | 0 | max 920 (limit 11000) |
| N6 | 100 ms delay, 25% reorder, 5% duplicate | 32 | 701.0 ms | 873.2 ms | 923.2 ms | 923.2 ms | 0 | 5xx 0, ok% 100 |
| N7 | inbound 100% loss for 30 s | 15 | 259.4 ms | 9358.5 ms | 9358.5 ms | 9358.5 ms | 15 of 15 (5xx) | max 9358 (limit 11000), recovery 1910 ms after unblocking (limit 5000) |

The N3 note `no worker pinned` is informational (worker behaviour not inspected).

### Reading the results

- **Bandwidth limits barely matter for this request.** `/api/healthz` is tiny, so 1 Mbit/s and 256 kbit/s only moved the median from 302 ms to 344 and 427 ms. The login stayed near 1.1 to 1.2 s and the compressed static asset was served in N2.
- **Latency matters far more than bandwidth.** The 200 ms delay in N4 (each way, so about 400 ms added round trip) pushed the median to 1140 ms, nearly four times the control. N6 (100 ms delay plus reordering) gave 701 ms.
- **Packet loss was absorbed.** At 10% loss (N5) the median stayed near 313 to 323 ms, with a longer tail on the outbound-only case (p95 1188 ms). No request failed, and none hung past the 11 s limit.
- **A 30 s blackout (N7) failed every request, then recovered in 1.9 s.** All 15 probes failed during the block (the longest took 9.4 s, inside the 11 s limit, so nothing hung). The first request after unblocking succeeded within 1.9 s. The status codes behind the 15 failures are counted as 5xx; the summary does not say whether Cloudflare or the Pi returned them, so check `N7.probe.csv` before stating which.
- No scenario produced a failed request or a 5xx other than the full blackout.

### Limits of these numbers

- Each shaped scenario has only 26 to 40 requests (60 s at one request per 1.1 s), so p95, p99 and max are indicative and the max is a single request.
- The probe measures client round trip through the Cloudflare tunnel, not server time.
- Shaping applies to the cloudflared container only, which is the public path. It does not test the LAN side or the Pi's other interfaces.
- N4's "zero duplicated writes" and N5's "no half-written record" are asserted by the race (R/RN) test groups, not here.
- Not run on production: N8 to N11 (slowloris, blackout of the host, tunnel stop, DNS block), which are disruptive.

## Test Pi (controlled environment), set up 2026-11-12

Second Compute Module 4 (`uthm-pr-emos-000m`, 192.168.1.7), cloned from the production node (`uthm-pr-emos-0g12`, 192.168.1.10) so the "ideal" and "production" tables differ only where stated.

| | Production Pi | Test Pi |
|---|---|---|
| Hardware | IRIV PiControl CM4 | Raspberry Pi Compute Module 4 Rev 1.1, 4 cores, 1849 MB RAM, 15 GB root |
| OS | Debian 11 (bullseye), aarch64 | same, kernel 6.1.21 |
| Docker | 29.8.0, containerd 2.3.4, Compose 5.5.1 | same versions (pinned apt install from the same Docker source) |
| Swap | zram: zstd, 60% RAM (about 1.1 GB), priority 100; disk swap off | same config, same size |
| Images | built on the node | copied byte-for-byte with `docker save` / `docker load` (backend, web, minio, caddy 2.8, redis 7.4, mariadb 11.4) |
| Other workloads on the node | yes: AMBANG, emos-server, pi-server and others | none; CLARION only |
| Disk | 15 GB, 82% used (2.6 GB free) | 15 GB, about 55% used (6.2 GB free) |
| Public access | Cloudflare tunnel (`clarion.larmkx.com`) | none; LAN only (`https://clarion.test:18443`, `/etc/hosts` entry on the Pi, Caddy `tls internal`) |
| Data | demo data | freshly seeded fictional demo data; no data, volume or upload copied from production |
| Secrets | production | all regenerated on the test Pi; third-party tokens left empty; own database encryption key |
| Backend `APP_ENV` | demo-seeded accounts accept demo passwords | container runs `APP_ENV=production`; seed printed random per-account passwords |

Differences to state when comparing the two tables: the test Pi has no tunnel (so no Cloudflare path in its latency), no other workloads, and more free disk and RAM.

Setup notes (things that went wrong, for the record):
- The repo copy initially included production's database encryption keyfile; it was deleted and regenerated on the test Pi before any data was written.
- The new keyfile had to be owned by uid 999 (the MariaDB container user) at mode 0400; the first start failed with "Permission denied".
- The proxy has no host port in the production compose file (traffic enters through cloudflared), so the test Pi uses a local override `docker-compose.lan.yml` publishing 18443 and 18080. Caddy needs a hostname, not a bare IP, to pick a certificate.

## Production Pi: reduced disk and memory-cap tests (H8, H9, H6), 2026-11-12

Run in parallel with the test Pi's full hardware group. Probe: origin path, `PROBE_GAP=1.1`. Pi results folder: `results/20261112-153510/`. Script summary: 6 passed, 0 failed, but only the 4 H8 and H9 checks are valid (the 2 H6 passes are void, see the correction below).
These were run at a **reduced size** because of the node's disk headroom: `FIO_SIZE=256m` instead of 1 GB (H8, H9). H6 is **invalid, see the correction below**.

| Test | Load | n | Median | p95 | p99 | Max | Failed | Checks |
|---|---|---|---|---|---|---|---|---|
| H8 | fio random write, 4 KB, iodepth 16, 256 MB file, 300 s | 240 | 66.0 ms | 234.9 ms | 368.6 ms | 637.7 ms | 0 | p95 at most 250 ms (234.9, close to the limit); MariaDB commit 45 ms (limit 100) |
| H9 | fio 70/30 read-write with fsync, 256 MB file, 300 s | 228 | 58.6 ms | 167.6 ms | 455.9 ms | 705.2 ms | 0 | MariaDB commit 15 ms (limit 2000); semaphore waits 0 |
| H6 | INVALID: the 256 MB cap was never applied (see below) | 151 | 46.7 ms | 77.2 ms | 117.6 ms | 430.6 ms | 0 | the script reported PASS, but the test did not exercise a memory limit |

- Disk I/O load raises median latency by about 40% (46 ms idle to 66 ms) and pushes p95 to 235 ms under random-write load, within 15 ms of the 250 ms limit. Treat H8 as a marginal pass.
- H4 (memory pressure), H5, H10 and H13 were not run on production; see the skipped-tests list above.

### Correction: H6 did not test anything, and the memory cgroup is off on both Pis

The H6 log contains `Your kernel does not support memory limit capabilities or the cgroup is not mounted. Limitation discarded.` Docker silently dropped the 256 MB limit, so the backend ran unlimited and the script's PASS lines (`backend running+healthy`, `restart_delta=0`) are meaningless. The same happened on the test Pi (`mem_limit=0` on the backend afterwards).

Cause: on both Pis `/proc/cgroups` shows the `memory` controller disabled (enabled=0) and the kernel command line has no `cgroup_enable=memory cgroup_memory=1`. This is the Raspberry Pi OS default.

Consequences:
- On the current nodes Docker cannot enforce a memory limit on any container. A runaway container can take all RAM and leave the kernel OOM killer to choose a victim.
- Production has no `mem_limit` set in its compose file either, so nothing would be limited even with the cgroup on.
- The H6 and H5 results so far are void for the memory-limit behaviour. H6 has been changed to SKIP with a clear reason when the cgroup is off (`hw_stress.sh`).

Fix (needs a reboot): add `cgroup_enable=memory cgroup_memory=1` to the end of the single line in `/boot/cmdline.txt` (on this OS version; `/boot/firmware/cmdline.txt` on newer ones). To be applied on the test Pi after its current run; not on production without a window.

## Test Pi: hardware group (full size), 2026-11-12

Probe: `https://clarion.test:18443/api/healthz` on the Pi itself (LAN, no tunnel), `PROBE_GAP=1.1`. Raw data: `qa/result/final/2026-11-13/evidence/test-pi/results/20261112-153040/`.
Script summary: 14 passed, 2 failed (both H4, explained below). H6 is invalid (memory cgroup off, see the correction above).

| Test | Load | Test Pi median / p95 / max | Production median / p95 / max | Failed requests |
|---|---|---|---|---|
| H1 | 4 cores 100%, 600 s | 91.1 / 118.7 / 200.5 ms (n=462) | 85.1 / 113.3 / 137.0 ms (n=467) | 0 / 0 |
| H3 | 8 CPU hogs, 300 s | 114.3 / 161.4 / 256.0 ms (n=222) | 105.1 / 141.5 / 211.7 ms (n=224) | 0 / 0 |
| H4 | 2 memory hogs, 60% of RAM, 300 s | 142.4 / 195.1 / 255.4 ms (n=220) | not run | 0 |
| H8 | fio random write, 300 s | 61.5 / 92.8 / 172.7 ms (1 GB file) | 66.0 / 234.9 / 637.7 ms (**256 MB** file) | 0 / 0 |
| H9 | fio 70/30 with fsync, 300 s | 55.8 / 82.3 / 3309.5 ms (1 GB file) | 58.6 / 167.6 / 705.2 ms (**256 MB** file) | 0 / 0 |
| H12 | 4 cores, 120 s | 92.0 / 116.0 / 131.4 ms (n=93) | 83.8 / 110.5 / 153.1 ms (n=93) | 0 / 0 |

- **CPU stress: the two Pis behave the same.** Medians are within about 10 ms and p95 within about 20 ms, with zero failed requests and no throttle bits on either. The production node's other workloads cost it nothing measurable here.
- **Disk stress: the test Pi is faster even with the larger test file.** H8 p95 was 93 ms against 235 ms on production, and MariaDB commit time 23 ms against 45 ms. The sizes differ (1 GB vs 256 MB), so this understates the gap.
- **H9 has one 3.3 s outlier on the test Pi** (p99 was only 304 ms), which should be checked against `H9.fio.txt` and `iostat.log` before the paper claims a clean result.
- **H4 (memory pressure):** latency held (median 142 ms, 100% ok) but the swap rate was **502 pages/s against a limit of 100: a genuine FAIL.** The second H4 FAIL, `not running: cloudflared`, is an artefact: the script expects cloudflared in its core-service list and the test Pi has no tunnel. Rerun with `CORE_SERVICES` set without it.

## Test Pi: memory cgroup enabled, 2026-11-13

`cgroup_enable=memory cgroup_memory=1` appended to `/boot/cmdline.txt` (backup: `/boot/cmdline.txt.bak.20261113`) and the Pi rebooted. After the reboot: `/proc/cgroups` shows `memory ... enabled=1`; all 7 containers came back on their own (restart policy) and were healthy within about 30 s; `healthz` 200.
`docker stats` now reports real memory (before it showed `0B / 0B`): backend 297 MiB, mariadb 99 MiB, minio 75 MiB, mpi 55 MiB, proxy 32 MiB, web 14 MiB, redis 9 MiB, out of 1.8 GiB.
The backend already uses more than H6's 256 MB cap, so H6 now genuinely exercises the limit. Results from H4, H6 and H7 before this change are void for memory; rerun pending.
Production still has the memory cgroup off (changing it needs a reboot window).

## Test Pi: H4 and H6 rerun with the memory cgroup on, 2026-11-13

Raw data: `qa/result/final/2026-11-13/evidence/test-pi/results/20261112-161440/`. Core-service check without cloudflared (`CORE_SERVICES`), probe `https://clarion.test:18443/api/healthz`, `PROBE_GAP=1.1`.

| Test | Load | n | Median | p95 | p99 | Max | Failed | Result |
|---|---|---|---|---|---|---|---|---|
| H4 | 2 memory hogs, 60% of RAM, 300 s | 210 | 178.2 ms | 270.8 ms | 308.0 ms | 358.6 ms | 0 | median and ok% PASS; all core containers running PASS; **swap rate 322 pages/s against a limit of 100: FAIL (genuine)** |
| H6 | backend capped at 256 MB for 180 s (cap really applied this time) | 149 | 52.2 ms | 75.6 ms | 92.6 ms | 114.4 ms | 0 | backend healthy after the cap PASS; restart delta 0 (limit 1) PASS |

- H4 repeated its genuine failure: under memory pressure the Pi churns compressed swap at about 3 times the limit (322 vs 100 pages/s; the first run, before the cgroup change, gave 502). Latency still held (median 178 ms, 100% ok), and peak swap occupancy was small (81 MB), so this is churn rather than exhaustion. Peak memory used was 1141 MB of 1849 MB.
- H6 is now a valid pass: the backend survived a 256 MB memory cap with no restart and no failed request. The earlier H4 and H6 results are superseded.
- H4's swap-rate limit of 100 pages/s was set before zram was in use; with zram (about 1.1 GB compressed swap) some swap traffic is expected, so the threshold may be the wrong yardstick for this configuration. Report both the number and this caveat.

## Production Pi: long-run items started, 2026-11-13

- **H7 (memory growth soak):** started 2026-11-12 about 16:22 Pi time, 24 hours, probe 1 request per 1.1 s on the origin path. Because the memory cgroup is off there, it samples the sum of process RSS per container from the host (`docker top`), once a minute. First sample (MB): backend 125.7, minio 89.5, cloudflared 29.1, proxy 23.8, mariadb 23.0, mpi 9.6, web 3.4, redis 2.4. Sampler changed from `docker stats`, which reports 0 on this node.
- **H11 (SD/eMMC writes per day):** baseline saved at 16:23 Pi time (counter 374,337,038 sectors written on `mmcblk0`); the second reading is due after about 24 hours. Since boot the average was 8.6 GB/day (191.6 GB in 22.2 days) against the 5 GB/day limit, but that includes builds and upgrades. `mmc-utils` is not installed on production, so no wear counter was read.
- **Uptime and power:** 22.2 days without reboot and `get_throttled` 0x0 (no under-voltage or throttling events since boot); peak temperature 42.3 °C during the CPU stress runs.

## Production Pi: disruptive network tests N8 to N11, 2026-11-12/13

Run with the owner's notice, 16:33 to 16:39 UTC, shaping confined to the cloudflared container. Raw data: `qa/result/final/2026-11-13/evidence/production-pi/results/20261112-163355/`. Script summary: 7 passed, 1 failed. The production H7 soak was stopped before this run and restarted after it, so it is unaffected.

| Test | What | Result |
|---|---|---|
| N8 | slowloris, 500 slow connections for 60 s, via the public URL | PASS: 42 probes, 0 failed, median 284.9 ms, p95 328.5 ms; no restarts. This exercises Cloudflare's edge and the tunnel; whether Caddy drops slow headers needs the proxy logs |
| N9 | full loss both directions for 60 s | **FAIL: first successful request 15.1 s after the blackout against a 5 s limit**; no restarts. cloudflared needs about 15 s to rebuild its connections after a total loss (the shorter inbound-only block in N7 recovered in 1.9 s) |
| N10 | cloudflared stopped for 120 s, then started | PASS: reconnected in 2 s (limit 30 s); no other restarts |
| N11 | DNS blocked in the backend's namespace for 60 s | PASS: 42 probes, 0 failed, median 276.6 ms; login still succeeded (839 ms) |

After the run: all containers healthy, public URL 200, firewall rules and traffic shaping removed (checked).

## Production Pi: security suite (CK, T, A), 2026-11-13

Run from the laptop against `https://clarion.larmkx.com`. Raw data: `qa/result/final/2026-11-13/evidence/production-sec/` and `production-sec-rerun/` (secrets redacted, see its README).
The first full run (398 passed, 64 failed, 21 skipped, 19 min 42 s) overlapped the N9/N10 outage; about half of its failures and 11 skips are Cloudflare 530/502 responses and are not findings. A rerun of the cookie, transport and app-attack tests after the outage (78 passed, 14 failed, 6 xfailed, 7 skipped) is the valid record. The anonymous-route and role-matrix tests (A1) were not rerun and still need a clean run.

Known gaps recorded as expected failures (xfail): no `__Host-` cookie prefix; `/auth/refresh` and `/auth/logout` honour the cookie when sent with a foreign Origin (defence relies on SameSite=Strict); HSTS max-age 300 (demo mode).

Remaining 14 failures, sorted:

| Test | Finding | Kind |
|---|---|---|
| T1 (TLSv1, TLSv1.1) | the edge completes TLS 1.0 and 1.1 handshakes | real: set Cloudflare's minimum TLS version to 1.2 |
| CK2, T3 | plain `http://` returns 200 instead of redirecting | real: enable "Always Use HTTPS" in Cloudflare |
| CK1 | refresh cookie has `Path=/`, so it is sent to every route | real hardening: scope the cookie path |
| CK11 | login response lacks `Cache-Control: no-store` | real hardening |
| CK7 | reusing a rotated refresh token did not revoke the family | to check: the test may be inside the 8 s reuse grace window |
| T6 (`/metrics/`) | trailing-slash path answers 307 instead of 403/404 | probably benign (redirect to the blocked path); confirm |
| A6 (`/.env`, `/.env.docker`, `/.git/HEAD`, `/backend/.env`) | each returned HTTP 200 | **false positive**: the SPA catch-all returns `index.html`; the check matches an `=` or `ref:` inside the HTML. The test should compare content type or file signature |
| A5 `x\x00.png`, A7 empty `Bearer ` | client library refuses to send these | test-harness errors, not server behaviour |

### Deployed build is older than the repo (found by the A1 anonymous-route test)

19 routes that exist in the repository answer 404 on production: `/profiles`, `/profiles/switch`, `/profiles/guardians*`, `/auth/switch-role`, `/admin/users/{id}/roles*`, `/profile/directives*`, `/patients/{id}/directives`, `/emergency/location`, `/emergency/locations/{id}`, `/patients/campus-eligibility/{nric}`, `/pharmacy/dispense`, `/pharmacy/patients/{id}/prescription/pdf`. The production backend image (`clarion/backend:local`) was built about two weeks before this run, and the test Pi copy is the same image. Every result in this journal therefore describes the deployed build, not the current repository. Rebuilding and redeploying, then rerunning A1, would show whether the 19 become 401/403.
(Two more A1 "failures", `POST /emergency/scan` and `POST /emergency/nfc/scan` answering 422, are by design: they are public emergency endpoints that validate input before any auth.)

Verified 2026-11-13 against the running container (OpenAPI schema of the live app): production serves **328** API paths, the repository at HEAD (`72039b8`) **343**. Missing on production: `/profiles`, `/profiles/switch`, `/auth/switch-role`, `/admin/users/{user_id}/roles`, `/profile/directives`, `/emergency/location`, `/patients/campus-eligibility/{nric}`, `/pharmacy/dispense` (and the sibling routes listed above). `/emergency/scan` exists on both. The images (`clarion/backend:local`, `clarion/web:local`) were built 2026-10-24. The build dates do not explain every missing route: `profiles.py` is present in the image's routers folder but its routes are not registered, so the image was built from a partly stale source snapshot. Fix: rebuild both images from current `main`, redeploy, rerun A1. The test Pi runs the same old image, so its results (H, N, D) describe the old build too; the load and resource numbers are unlikely to change much, but the new routes are untested everywhere.

## Incident log, 2026-11-12/13

| When (UTC) | What | Effect | Resolution |
|---|---|---|---|
| 17:28 to 17:31 | The Clean Prod Pi (.7) was started with a `cloudflared` connector using the **same tunnel token as production** (same tunnel ID). Cloudflare balanced requests for both hostnames across the two connectors | about half of the requests to `clarion.larmkx.com` (and to the testnet hostname) answered 502/503 for about 3 minutes | connector on .7 stopped; production back to 200. A separate tunnel with its own token is needed for `clarion-testnet.larmkx.com` |
| 16:33 to 16:39 | N8 to N11 on production (planned, owner notified) | public demo down briefly during N9 and N10 | restored |

| 17:38 to 17:43 | Owner took the Dirty Prod Pi (.10) offline. The Clean Prod Pi (.7) connector started on the same tunnel and answered 503 ('No ingress rules were defined') | public URL 503 for about 5 minutes | **root cause: on .7, not in Cloudflare.** `proxy/certs/caddy-root.crt` was created by `docker cp` readable by root only; cloudflared (unprivileged) could not load it as its CA pool, rejected the whole ingress configuration ('Failed to update ingress ... unable to read the file'). `chmod 644` fixed it; `https://clarion-testnet.larmkx.com` then returned 200. (An earlier note in this log that blamed Cloudflare's configuration was wrong.) |

No test result recorded while the shared connector was running is used.


## Configuration: Clean Prod Pi vs Dirty Prod Pi

Both are Raspberry Pi Compute Module 4 nodes running the same Debian 11 and Docker. **Clean** is the system under test for the full campaign; **Dirty** is the long-running production node, kept as a labelled reference (old build, partial test set, now offline).

| | Clean Prod Pi (192.168.1.7) | Dirty Prod Pi (192.168.1.10) |
|---|---|---|
| Role | system under test (temporary production) | the live demo until 2026-11-12, now offline; reference only |
| Board | Raspberry Pi Compute Module 4 Rev 1.1 (carrier not recorded) | IRIV PiControl CM4 |
| RAM / storage | 1849 MB / 15 GB root, about 55% used after install | 1849 MB / 15 GB root, 82% used (2.6 GB free) |
| OS, Docker | Debian 11 (bullseye) aarch64, kernel 6.1.21; Docker 29.8.0, Compose 5.5.1 | same |
| Swap | zram, zstd, 60% of RAM (1.1 GB), priority 100; disk swap off | same |
| Memory cgroup | **on** (`cgroup_enable=memory cgroup_memory=1`); `docker stats` reports memory | **off**; `docker stats` memory reads 0 |
| Build | `HEAD` 72039b8 (343 API paths), images built on the device 2026-11-12/13 | images built 2026-10-24 (328 API paths; 15 routes missing) |
| MinIO | `clarion/minio:local` copied from Dirty (release 2025-09-07, with mc); the `quay.io` images in the repo now return HTTP 401 | the same image |
| Other workloads | none | other projects' containers and images on the same disk |
| Data | freshly seeded fictional demo data (known demo passwords, as production was seeded) | long-lived demo data |
| Secrets | regenerated on the device; third-party tokens empty | production secrets |
| Test-only flags | `PAYMENTS_ALLOW_MOCK=1` and a webhook secret (needed by the live race suite) | not set |
| Public access | Cloudflare tunnel, hostname `clarion-testnet.larmkx.com` (same tunnel as Dirty; Dirty is offline so no sharing) | Cloudflare tunnel, `clarion.larmkx.com` |
| Origin leg (cloudflared to Caddy) | TLS 1.3, **verified** against Caddy's local CA (`caPool`, `noTLSVerify` false) | the same setting |
| Hardening (fail2ban, watchdog, log rotation, journald cap) | not applied (baseline) | not applied |
| Tools installed for the full suite | stress-ng, fio, sysstat, nmap, tcpdump, slowhttptest, testssl, lynis, restic, age, gitleaks, trivy, pip-audit, mmc-utils, Toxiproxy image, Python venv with pytest/httpx/h2 | stress-ng, fio, sysstat, slowhttptest (nmap/tcpdump from the earlier setup) |

Verified at 2026-11-12 17:45 UTC from this laptop over the public URL: all five demo logins 200; the six routes that were 404 on the old build now answer 401; HSTS/CSP/X-Frame-Options present; TLS 1.3 at the edge.


### Pilot on the Clean Pi: network failures were a harness bug, not findings (2026-11-12)

The pilot's N1, N2, N3, N6, N8 and N11 "failures" were all HTTP 429 from the app's 60 requests per minute per-IP limiter (for example N1: 299 OK, 700 rate-limited). `overnight.sh` sourced `lib.sh` first, which set `PROBE_GAP=0.2`, so its later default of 1.1 s never applied. Fixed in `overnight.sh` (set before `lib.sh` loads) and `lib.sh` now defaults to 1.1 s. The pilot is not counted; the campaign reruns everything. The Dirty runs used `PROBE_GAP=1.1` from the shell and are not affected.
