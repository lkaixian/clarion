# Raw test evidence, 2026-11-12

Unmodified copies of the result folders and run logs written by the scripts in `qa/stress/pi/`, pulled from the two Raspberry Pi nodes on 2026-11-12. Nothing here was edited after collection. `SHA256SUMS` lists a checksum of every file; verify with `sha256sum -c SHA256SUMS` from this folder.
Interpretation, tables and caveats are in [`../stress/result.md`](../stress/result.md).

Secrets and personal data: the files were scanned for passwords, tokens, API keys, e-mail addresses and NRIC-like numbers before being stored; none were found. Latency numbers are client round trip (curl), not server time.

## Hosts

| Folder | Host | Role |
|---|---|---|
| `production-pi/` | `uthm-pr-emos-0g12` (192.168.1.10) | live demo node behind the Cloudflare tunnel |
| `test-pi/` | `uthm-pr-emos-000m` (192.168.1.7) | controlled test node, LAN only, cloned setup (see `result.md`) |

## What each folder is

Each `results/<timestamp>/` has `results.txt` (PASS/FAIL/SKIP/INFO lines), `events.log` (timestamped markers), `*.probe.csv` (one row per request, with DNS/connect/TLS/first-byte/total timings), and, for load tests, `collect.csv` (temperature, throttling, memory, swap, iowait every 5 s), `docker_stats.csv`, `iostat.log` and `*.fio.txt`. The `*.ms` files are the latency lists the percentiles were computed from.

### production-pi/results

| Folder | What it is |
|---|---|
| `20261112-140256` | speed baseline, exploratory (1 run, 10 s tunnel probe) |
| `20261112-140432` | speed baseline used in the journal (3 runs, 60 s tunnel probe): internet speed, ping, tunnel latency |
| `20261112-140756` | dry run of a test group (no real load), invocation not recorded in the conversation |
| `20261112-140837` | the same baseline against the origin (`--resolve` straight to Caddy); 43 of 103 requests were HTTP 429 from the rate limiter |
| `20261112-141627` | `run_all.sh --dry-run`, includes the real read-only D9/D10 config checks |
| `20261112-142259` | H1, H3, H12 CPU stress, origin probe |
| `20261112-145111` | dry run of the network scenarios with `NS_CONTAINER=cloudflared` (the one reviewed before the real run) |
| `20261112-145159` | real run, N1 control only; the N2 start aborted on a wrong container name before any shaping |
| `20261112-150512` | real run, N2 to N7 (shaping inside the cloudflared container) |
| `20261112-153510` | H8, H9 at 256 MB and H6. **H6 is invalid**: the memory limit was discarded by Docker (memory cgroup off); see `tmp/prod_hw.log` and the correction in `result.md` |

### test-pi/results

| Folder | What it is |
|---|---|
| `20261112-153040` | hardware group (H1, H3, H4, H6, H8, H9, H12), plus the speed baseline, full size. Complete run (script summary 14 passed, 2 failed). The 2 failures are both H4: swap rate 502 pages/s against a limit of 100 (genuine), and "cloudflared not running" (false failure: the test Pi has no tunnel). **H6 is invalid** here too, for the same reason as production. `tmp/hw.log` is the full log |

### test-pi/results, update 2026-11-13

| Folder | What it is |
|---|---|
| `20261112-153040` | the full hardware group before the memory cgroup was enabled (H6 void; `docker_stats.csv` memory columns are all zero). Its console log `/tmp/hw.log` was lost: the Pi rebooted afterwards (clearing `/tmp`) before it was archived. `results.txt` and the CSV and fio files are intact |
| `20261112-161440` | H4 and H6 rerun after enabling the memory cgroup (`cgroup_enable=memory cgroup_memory=1`) and rebooting; cloudflared excluded from the core-service check. Console log: `tmp/h46.log`. The log ends with a shell error because `hw_stress.sh` was overwritten while it was running; it appears after all results were written |

Production, still collecting: an H7 24-hour memory soak started 2026-11-12 about 16:22 Pi time (host-side RSS sampler), and the H11 first reading (baseline sectors written) saved at 16:23. Their folders will be added when they finish.

### Production runs added 2026-11-13

| Folder | What it is |
|---|---|
| `production-pi/results/20261112-162149` | first H7 attempt (host-side memory sampler, 24 h), stopped after about 10 minutes so the disruptive tests could run; partial data only |
| `production-pi/results/20261112-162341` | H11 first reading (baseline only, no verdict until the second reading, due about 24 h later) |
| `production-pi/results/20261112-163355` and `tmp/prod_n8.log` | N8, N9, N10, N11 on production (disruptive; owner notified). N9 FAIL: 15.1 s to first request after a 60 s blackout |
| `production-sec/` | full security suite (CK, T, A, run from the laptop) against the public URL. **Contaminated**: it overlapped the N9/N10 tunnel outage, so many failures and skips show Cloudflare status 530/502 and are not findings. Kept as run |
| `production-sec-rerun/` | rerun after the outage of the cookie, transport and app-attack tests (the anonymous-route and role-matrix tests were not rerun): 78 passed, 14 failed, 6 xfailed, 7 skipped |

Redaction: `production-sec/sec.log`, `production-sec-rerun/sec-rerun.log` and `sec-rerun.xml` contain assertion output. Refresh-token strings, JWTs and the public demo passwords were replaced with `[redacted]`, `[jwt-redacted]` and `[demo-password]` before storing. Nothing else in these files was changed. This is the only edit made to any file in this folder.

### Status files, 2026-11-13

| File | What it is |
|---|---|
| `build_matrix.py` | reads the evidence above, applies explicit rules for which runs are valid (see `PI_RULES` in the script), and writes everything below. Rerun it after adding evidence |
| `matrix.json`, `matrix.csv` | one record per test or check: id, test, environment, status, detail, source file |
| `STATUS.md` | what is done, failed, void, in progress, not run, and open decisions |
| `laptop/races.xml`, `laptop/races.log` | the in-process race suite run (R1 to R15, A14) on SQLite |
| `production-sec/collected.txt` | the 483 security tests that exist (the denominator for the first run) |
| `measurements.json` | reference speed, ping and per-test latency numbers parsed from the raw results |
| `../stress/coverage-clean.svg`, `coverage-clean-detail.svg` | Clean Prod Pi (192.168.1.7): overview and every test (pilot shown separately, not counted) |
| `../stress/coverage-dirty.svg`, `coverage-dirty-detail.svg` | Dirty Prod Pi (192.168.1.10, old build): overview and every test |

### Clean Prod Pi campaign state, 2026-11-12

`clean-pi/campaign/` holds the campaign's `queue.log`, `config.txt` (build, versions, 343 API paths, cgroup), `not-run.txt` (what is deliberately not run and why) and `speed/results.txt` (the baseline). `build_matrix.py` reads `queue.log` to mark each campaign step running or queued in `../stress/coverage-clean*.svg`. As steps finish, pull their result folders here (`clean-pi/campaign/<step>/`), add them to `PI_RULES` / the sec and live parsers, and rerun the builder; until then a finished step's scenarios show as not yet filled in.
