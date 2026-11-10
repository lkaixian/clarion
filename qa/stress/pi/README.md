# qa/stress/pi - Raspberry Pi stress, fault and durability drivers

Implements sections A (network), B (hardware), D (durability) and G (order) of
`docs/stress-and-security-test-protocol.md`. Bash + coreutils + apt tools only.
Target: Pi 4, Ubuntu 22.04 arm64, `docker-compose.pi.yml` (project `clarion-pi`), run as root.

## Prerequisites

    sudo ./setup_pi.sh            # prints what it would do
    sudo ./setup_pi.sh --apply    # apt tools, watchdog, journald cap, docker log rotation + live-restore
    chmod +x *.sh                 # or call them with `bash`

Environment (all optional except `BASE_URL`):

| Var | Meaning |
|---|---|
| `BASE_URL` | what the probe curls, e.g. `https://clarion.larmkx.com` (public, crosses cloudflared and the Pi uplink) |
| `CURL_EXTRA` | e.g. `--resolve clarion.larmkx.com:443:172.29.0.2` to hit Caddy directly from the Pi |
| `LOCUST=1` | use `backend/loadtest/locustfile.py` (headless, `LOCUST_USERS`=20) instead of the curl loop; install locust off the Pi where possible |
| `LOGIN_USER` / `LOGIN_PASS` | a throwaway test account for the login checks (visible in `ps` while curl runs) |
| `IFACE`, `NS_CONTAINER` | interface to shape; or shape inside a container netns (e.g. `NS_CONTAINER=cloudflared`) so SSH is untouched |
| `POWER_CYCLE_CMD` | D5 only: your smart-plug command. Never guessed. |

Every threshold is a variable at the top of each script. `--dry-run` on any script prints the
mutating commands and changes nothing.

## Safe vs destructive

| Safe (read-mostly, no flag) | Needs a flag | Why |
|---|---|---|
| `net_scenarios.sh` N1-N7 (shaping auto-removed by a dead-man switch) | `--disruptive` N8-N11 | slowloris, blackout, tunnel stop, DNS block |
| `hw_stress.sh` H1 H3 H4 H6 H8 H9 H12 | `--i-know-this-kills` H5 H10 H13 | OOM killer, disk full, combined worst case |
| `durability.sh` D9, D10 (config checks) | `--destructive` D1 D2 D3 D4 D5 D6 D12; `--panic` for the real D9 | kills containers, restarts docker, reboots, skews the clock |
| | explicit only: H2 (30 min), H7 (24 h), H11 (run twice ~24 h apart) | long |

Staging copy or a declared maintenance window only. `run_all.sh` refuses destructive groups without
`--destructive`, and never runs D5 implicitly (it power-cycles the box and spans reboots).

`netem.sh` always arms a dead-man switch (`DEADMAN`, default 600 s, cannot be 0) before shaping.

## Typical order

    sudo ./durability.sh --destructive D5      # staging first; after boot: sudo ./verify_after_boot.sh --continue
    sudo BASE_URL=... ./run_all.sh             # hw, net, durability config checks
    sudo BASE_URL=... ./run_all.sh --destructive --i-know-this-kills
    HOOK_RACE_CMD='...' HOOK_SEC_CMD='...'     # plug the py / sec suites in at spec order

For D5 across 20 boots: export `POWER_CYCLE_CMD`, and call `verify_after_boot.sh --continue` from a
root `@reboot` cron entry (with that variable set).

## Reading results

Each run writes `results/<timestamp>/` (override with `RESULTS_DIR`):

- `results.txt` - lines `PASS|FAIL|SKIP|INFO <id> <detail>`; the script ends with `SUMMARY pass= fail= skip=`
  and exits nonzero on any FAIL.
- `collect.csv` (temp, `get_throttled`, ARM clock, mem, swap, load, disk sectors, iowait every 5 s),
  `docker_stats.csv`, `iostat.log`, `events.log` (timestamped scenario markers, use them to correlate a slow request
  with a throttle flag, swap or iowait spike).
- `<id>.probe.csv` (per-request code and curl DNS/connect/TLS/TTFB/total timings), `*.hook`, `mariadb-check.*.txt`.

`get_throttled` is sticky since boot, so a test fails only on bits that became set during it.
SKIP means not checkable here (no `vcgencmd`, no login creds, manual step), not a pass.
Thresholds measure client RTT; true server p95 needs Caddy/uvicorn logs or `/metrics`.
