#!/usr/bin/env python3
"""build_matrix.py - one data file, three outputs.

Reads the raw evidence in qa/result/ (and the scenario titles in the protocol), applies EXPLICIT rules about which
runs count and which are void, and writes:
  qa/result/matrix.json + matrix.csv     one record per test / check / scenario, per environment
  qa/result/STATUS.md                    what is done, what is not, what is open
  qa/stress/coverage.svg                 overview: every spec scenario x environment, coloured by outcome
  qa/stress/coverage-detail.svg          long list: every test that ran (or did not), with its status
Run:  python qa/result/build_matrix.py        (stdlib only; needs pytest + httpx only to re-collect the sec test list)

Statuses: pass fail xfail skip | void (ran, but the result is not valid, reason given) |
          running (queued or in progress) | notrun
Environments: dirty = Dirty Prod Pi 192.168.1.10 (old build, offline since 2026-11-12), clean = Clean Prod Pi 192.168.1.7
              (HEAD build, system under test), lap = this laptop (in-process races on HEAD code, SQLite),
              pilot = runs on .7 before the rebuild (old build, not counted)
"""
import csv, glob, importlib.util, json, os, re, subprocess, sys, xml.etree.ElementTree as ET
from collections import Counter, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)                       # qa/result/final/<date>
EVID = os.path.join(ROOT, "evidence")               # raw evidence, never edited
REPORT = os.path.join(ROOT, "report")               # generated tables
QA = os.path.abspath(os.path.join(ROOT, "..", "..", ".."))
REPO = os.path.dirname(QA)
STRESS = os.path.join(QA, "stress")
spec = importlib.util.spec_from_file_location("report", os.path.join(STRESS, "report.py"))
rep = importlib.util.module_from_spec(spec); spec.loader.exec_module(rep)
esc, svg, t = rep.esc, rep.svg, rep.t

ENV = {"dirty": "Dirty Prod Pi", "clean": "Clean Prod Pi", "lap": "In-process (laptop)", "pilot": "Pilot on .7 (not counted)"}
ST = ["pass", "fail", "xfail", "skip", "void", "running", "queued", "excluded", "notrun"]
COL = {"pass": "#2ea043", "fail": "#da3633", "xfail": "#58a6ff", "skip": "#6e7681", "void": "#d29922",
       "running": "#bc8cff", "queued": "#6e5aa8", "excluded": "#7a4a1d", "notrun": "#21262d"}
LABEL = {"pass": "passed", "fail": "failed", "xfail": "known gap (xfail)", "skip": "skipped", "void": "void (invalid run)",
         "running": "running now", "queued": "queued (will run)", "excluded": "will not run", "notrun": "not run"}
BG, FG, GREY, LINE = "#0d1117", "#e6edf3", "#8b949e", "#30363d"
GROUPS = rep.GROUPS
COUNTS = rep.COUNTS
ORDER = list(COUNTS)
ID_RE = re.compile(r"^(?:test_)?(rn\d+|r\d+|ck\d+|t\d+|a\d+|n\d+|h\d+|d\d+)", re.I)
REC = []


def add(i, test, env, status, detail="", src="", note=""):
    REC.append({"id": i, "group": re.match(r"[A-Z]+", i).group(), "test": test, "env": env, "status": status,
                "detail": detail, "note": note, "src": src})


def rel(p):
    return os.path.relpath(p, EVID).replace("\\", "/")


# ------------------------------------------------------------------ titles
TITLES = {}
for line in open(os.path.join(REPO, "docs", "stress-and-security-test-protocol.md"), encoding="utf-8"):
    m = re.match(r"\|\s*((?:N|H|D|R|RN|CK|T|A)\d+)\s*\|\s*([^|]+?)\s*\|", line)
    if m:
        TITLES[m.group(1)] = re.sub(r"[*`]", "", m.group(2))[:70]

# ------------------------------------------------------------------ Pi results.txt (explicit validity rules)
PI_RULES = [
    # (env, folder, ids that count, ids that ran but are void -> reason)
    ("dirty", "production-pi/results/20261112-142259", {"H1", "H3", "H12"}, {}),
    ("dirty", "production-pi/results/20261112-145159", {"N1"}, {}),
    ("dirty", "production-pi/results/20261112-150512", {"N2", "N3", "N4", "N5", "N6", "N7"}, {}),
    ("dirty", "production-pi/results/20261112-153510", {"H8", "H9"},
     {"H6": "memory limit was never applied (memory cgroup off); PASS lines are meaningless"}),
    ("dirty", "production-pi/results/20261112-163355", {"N8", "N9", "N10", "N11"}, {}),
    ("dirty", "production-pi/results/20261112-141627", {"D9", "D10"}, {}),   # real read-only config checks from a dry run
    ("pilot", "test-pi/results/20261112-153040", {"H1", "H3", "H8", "H9", "H12"},
     {"H4": "superseded by the rerun (cloudflared false failure; cgroup was off)",
      "H6": "memory limit was never applied (memory cgroup off)"}),
    ("pilot", "test-pi/results/20261112-161440", {"H4", "H6"}, {}),
    ("pilot", "test-pi/results/overnight-20261112-162945/net-N1-N7", {"N1", "N2", "N3", "N4", "N5", "N6", "N7"}, {}),
    ("pilot", "test-pi/results/overnight-20261112-162945/net-N8-N9-N11", {"N8", "N9", "N11"}, {}),
    ("pilot", "test-pi/results/overnight-20261112-162945/hw-H5-H10-H13", {"H5", "H10"}, {}),
]
NOTES = {
    ("dirty", "N9"): "cloudflared needs ~15 s to rebuild its tunnel after a total blackout",
    ("pilot", "N1"): "failed requests were HTTP 429: probe ran at 0.2 s gap (harness bug), not a stack failure",
    ("pilot", "N2"): "failed requests were HTTP 429 (probe gap bug)",
    ("pilot", "N3"): "failed requests were HTTP 429 (probe gap bug)",
    ("pilot", "N6"): "failed requests were HTTP 429 (probe gap bug)",
    ("pilot", "N8"): "failed requests were HTTP 429 (probe gap bug)",
    ("pilot", "N11"): "failed requests were HTTP 429 (probe gap bug)",
    ("pilot", "H4"): "swap churn 322 pages/s vs limit 100 (zram); latency held",
    ("dirty", "H8"): "p95 235 ms, 15 ms under the limit; 256 MB file instead of 1 GB",
    ("dirty", "H9"): "256 MB file instead of 1 GB",
    ("dirty", "D9"): "no RuntimeWatchdogSec, no dtparam=watchdog=on (baseline before setup_pi.sh)",
    ("dirty", "D10"): "no log rotation on containers / journald not capped (baseline before setup_pi.sh)",
}
ALWAYS_NOTE = {("dirty", "H8"), ("dirty", "H9")}      # size caveat applies to every row of these
for env, folder, ids, voids in PI_RULES:
    p = os.path.join(EVID, folder, "results.txt")
    for line in open(p, encoding="utf-8", errors="replace"):
        m = re.match(r"(PASS|FAIL|SKIP)\s+(\S+)\s*(.*)", line.rstrip())
        if not m:
            continue
        stt, tok, rest = m.group(1).lower(), m.group(2), m.group(3)
        base = re.match(r"[A-Z]+\d+", tok)
        if not base:
            continue
        base = base.group()
        mm = re.match(r"(\w+)=(.*)", rest)
        if mm:
            test, detail = f"{tok} {mm.group(1)}", mm.group(2)
        else:
            k = rest.find(" (")
            test, detail = (f"{tok} {rest[:k]}", rest[k + 1:]) if k > 0 else (f"{tok} {rest}", "")
        if base in voids:
            add(base, test, env, "void", f"{stt.upper()} in the log: {detail}"[:90], rel(p), voids[base])
        elif base in ids:
            note = NOTES.get((env, base), "")
            if stt == "pass" and (env, base) not in ALWAYS_NOTE:
                note = ""
            add(base, test, env, "skip" if stt == "skip" else stt, detail[:90], rel(p), note)

# ------------------------------------------------------------------ laptop in-process race suite
def junit(path):
    out = []
    for tc in ET.parse(path).getroot().iter("testcase"):
        stt, msg = "pass", ""
        for ch in tc:
            if ch.tag in ("failure", "error"):
                stt, msg = "fail", (ch.get("message") or "")[:100]
            elif ch.tag == "skipped":
                msg = (ch.get("message") or "")[:100]
                stt = "xfail" if "xfail" in (ch.get("type", "") + msg).lower() else "skip"
        out.append((tc.get("name", ""), stt, msg))
    return out


p = os.path.join(EVID, "laptop", "races.xml")
for name, stt, msg in junit(p):
    m = ID_RE.match(name)
    if m:
        add(m.group(1).upper(), name, "lap", stt, msg, rel(p))

# ------------------------------------------------------------------ security suite (CK, T, A) against the public URL
SEC = os.path.join(EVID, "production-sec")
RER = os.path.join(EVID, "production-sec-rerun")
sec_ids = {"test_hsts_max_age_one_year": "T2"}


def sec_id(name):
    base = name.split("[")[0]
    if base in sec_ids:
        return sec_ids[base]
    m = ID_RE.match(base)
    return m.group(1).upper() if m else None


try:
    col = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=os.path.join(STRESS, "sec"),
                         env={**os.environ, "BASE_URL": "https://x"}, capture_output=True, text=True, timeout=300).stdout
    collected = [l.split("::", 1)[1].strip() for l in col.splitlines() if "::" in l]
    if collected:
        open(os.path.join(SEC, "collected.txt"), "w", encoding="utf-8").write("\n".join(collected) + "\n")
except Exception:
    collected = []
if not collected:
    collected = open(os.path.join(SEC, "collected.txt"), encoding="utf-8").read().split("\n")
collected = [c for c in collected if c]

first_fail, first_msg, cur = set(), {}, None
for line in open(os.path.join(SEC, "sec.log"), encoding="utf-8", errors="replace"):
    m = re.match(r"^_+ (test_.*?) _+$", line.rstrip())
    if m:
        cur = m.group(1); first_fail.add(cur)
    elif cur and line.startswith("E  ") and cur not in first_msg and "AssertionError" in line:
        first_msg[cur] = line.strip()
rerun = {n: (s, msg) for n, s, msg in junit(os.path.join(RER, "sec-rerun.xml"))}
SEC_NOTES = {
    "test_t1_legacy_tls_refused": "Cloudflare edge accepts TLS 1.0/1.1 (set minimum TLS 1.2)",
    "test_ck2_plaintext_http_redirects_without_cookie": "plain http returns 200 (Cloudflare 'Always Use HTTPS' off)",
    "test_t3_http_redirects_and_serves_nothing": "plain http returns 200 (Cloudflare 'Always Use HTTPS' off)",
    "test_ck1_cookie_attributes": "refresh cookie has Path=/ (sent to every route)",
    "test_ck11_no_store_on_set_cookie_responses": "login response lacks Cache-Control: no-store",
    "test_ck7_rotation_reuse_revokes_family": "family not revoked after reuse; may be inside the 8 s grace window (to check)",
    "test_t6_diagnostics_not_public": "trailing-slash /metrics/ answers 307 (probably benign, to confirm)",
    "test_a6_no_sensitive_paths": "false positive: SPA index.html returned with 200",
    "test_a5_traversal_in_path_params": "client library refuses to send a NUL byte (harness error)",
    "test_a7_jwt_forgeries_rejected": "client library refuses an empty 'Bearer ' header (harness error)",
    "test_a1_anonymous_refused_on_every_secured_route": "route absent (404) or validated before auth (422) on production",
    "test_a1_public_route_inventory": "POST /payments/webhook/{provider} is unauthenticated by design (HMAC signature)",
    "test_a1_role_matrix": "502s during the N9/N10 outage; needs a clean rerun",
    "test_hsts_max_age_one_year": "HSTS max-age 300, accepted only because APP_ENV=demo",
}
SEC_SKIP_FIRST = {"test_a12_gitleaks_clean": "gitleaks not installed", "test_a12_container_env_has_no_default_secrets":
                  "needs SEC_DOCKER=1 on the Pi", "test_a13_audit_logs_append_only_as_app_account":
                  "needs MARIADB_APP_PASSWORD on the Pi"}
src_re, src_1 = rel(os.path.join(RER, "sec-rerun.xml")), rel(os.path.join(SEC, "sec.log"))
for name in collected:
    i = sec_id(name)
    if not i:
        continue
    base = name.split("[")[0]
    note = SEC_NOTES.get(base, "")
    if name in rerun:
        stt, msg = rerun[name]
        add(i, name, "dirty", stt, msg[:90], src_re, note if stt in ("fail", "xfail") else "")
    elif base == "test_a1_role_matrix":
        add(i, name, "dirty", "void", "502 responses while the tunnel was down (N9/N10)", src_1, note)
    elif name in first_fail:
        msg = first_msg.get(name, "")
        code = re.search(r"-> (\d{3})", msg)
        if base == "test_a1_anonymous_refused_on_every_secured_route" and code:
            note = ("route not in the deployed build (production image is older than the repo)" if code.group(1) == "404"
                    else "public emergency endpoint validates input before auth (by design)")
        add(i, name, "dirty", "fail", f"HTTP {code.group(1)}" if code else "", src_1, note)
    elif base in SEC_SKIP_FIRST:
        add(i, name, "dirty", "skip", SEC_SKIP_FIRST[base], src_1)
    else:
        add(i, name, "dirty", "pass", "", src_1)

# ------------------------------------------------------------------ halted runs and not-run reasons
add("H7", "H7 memory-growth soak (24 h)", "dirty", "void", "halted by the owner after about 30 min (217 samples); no verdict",
    "production-pi/results/20261112-163950")
add("H11", "H11 SD/eMMC writes per day", "dirty", "void", "baseline taken, second reading never done (run halted); no verdict",
    "production-pi/results/20261112-162341")
NOTRUN_WHY = dict(rep.PARTIAL)
NOTRUN_WHY.update({"N12": "manual: phone in airplane mode + NFC tag",
                   "H2": "queued on the test Pi (30 min)", "D5": "needs POWER_CYCLE_CMD (smart plug)",
                   "D8": "needs a restic repo + backup sandbox", "D11": "availability soak, not scheduled",
                   "H11": "baseline only; verdict needs the second reading",
                   "D4": "queued last on the test Pi (reboot + cron hook)"})
GROUP_WHY = {"R": "live race suite needs the mock gateway + admin login on the target; decision pending",
             "RN": "needs Toxiproxy on the target Pi; pending go for the test Pi after the queue",
             "D": "destructive; test Pi only", "H": "destructive or long soak; test Pi only",
             "A": "needs the host (Pi) or extra credentials", "T": "needs host access", "CK": "", "N": ""}

# ------------------------------------------------------------------ Clean Prod Pi campaign plan (what runs, what does not)
def _rng(prefix, a, b):
    return [f"{prefix}{k}" for k in range(a, b + 1)]


# step -> (scenarios covered, estimated time, note)   order = campaign order (see qa/stress/pi/campaign.sh)
CAMPAIGN = [
    ("h11-first", ["H11"], "5 min", "first reading of writes per day"),
    ("sec", [f"CK{k}" for k in (1, 2, 3, 4, 6, 7, 8, 9, 10, 11)] + _rng("T", 1, 6) + ["A1", "A3", "A4", "A5", "A6", "A7", "A9", "A10", "A11", "A12", "A13"], "1.5-3 h",
     "security suite + host scripts (sniff, exposure scan, lynis); A5 upload-abuse part not run"),
    ("race-live", ["R1", "R2", "R4", "R8", "R9", "R10", "R11"], "15 min", "live race suite against the public URL"),
    ("rn-live", ["RN1", "RN2", "RN3", "RN6", "RN7", "RN9", "RN10"], "40-60 min", "Toxiproxy in front of Caddy"),
    ("net-N1-N7", _rng("N", 1, 7), "35 min", "shaping inside the cloudflared container"),
    ("hw-safe", ["H1", "H3", "H4", "H6", "H8", "H9", "H12"], "1.2 h", "full 1 GB fio, origin path"),
    ("hw-H2", ["H2"], "30 min", "thermal soak"),
    ("hw-H7", ["H7"], "8 h", "memory growth, 8 h soak"),
    ("dur-D11", ["D11"], "6 h", "availability soak"),
    ("net-disruptive", ["N8", "N9", "N10", "N11"], "10 min", "destructive: slowloris, blackout, tunnel stop, DNS block"),
    ("hw-risky", ["H5", "H10", "H13"], "20 min", "destructive: OOM, disk full, worst case"),
    ("dur-destructive", ["D1", "D2", "D3", "D6", "D12"], "20 min", "destructive: kills, docker restart, down/up, clock skew"),
    ("dur-D7-D9-D10", ["D7", "D9", "D10"], "10 min", "D9 is the config check only; kernel panic not run"),
    ("h11-second", ["H11"], "5 min", "second reading, 24 h or more after the first"),
    ("dur-D4", ["D4"], "5 min", "cold reboot, last; cron hook verifies"),
]
EXCLUDED_CLEAN = {
    "D11": "skipped by the owner: stopped after 10 of 6 h; the 10-minute partial reading is not a verdict",
    "CK5": "manual: HSTS stripping needs a LAN rig with mitmproxy",
    "N12": "manual: phone in airplane mode + NFC tag",
    "D5": "needs a smart plug (POWER_CYCLE_CMD)",
    "D8": "needs a restic repo + backup sandbox",
    "RN4": "UI race: needs a browser (Playwright)", "RN5": "needs a 15 min token expiry",
    "RN8": "true half-open sockets need hardware",
    "T7": "needs the Pi's public address (ORIGIN_IP)",
    "A2": "needs a foreign patient id / second login (SEC_FOREIGN_PATIENT_ID)",
    "A8": "needs the SSRF endpoint list (SEC_SSRF)",
    "A14": "needs NTAG 424 DNA hardware; tag crypto is covered in-process on the laptop",
}
for _i in ("R3", "R5", "R6", "R7", "R12", "R13", "R14", "R15"):
    EXCLUDED_CLEAN[_i] = "no live version; covered in-process on the laptop only"


def campaign_progress():
    """step -> 'done' | 'running' | 'queued', from the pulled campaign queue.log (if present)."""
    out = {}
    q = os.path.join(EVID, "clean-pi", "campaign", "queue.log")
    if os.path.exists(q):
        for line in open(q, encoding="utf-8", errors="replace"):
            m = re.match(r"\S+\s+(BEGIN|END)\s+(\S+)", line)
            if m:
                out[m.group(2)] = "running" if m.group(1) == "BEGIN" else "done"
    return out


PROG = campaign_progress()
SRC_Q = "clean-pi/campaign/queue.log"
for step, ids, eta, note in CAMPAIGN:
    for i in ids:
        if i == "D4" and os.path.exists(os.path.join(EVID, "clean-pi", "campaign", "D4-verify", "results.txt")):
            continue                      # the post-reboot check has run
        if i == "D11":
            continue                      # skipped by the owner: listed under EXCLUDED_CLEAN
        stt = PROG.get(step, "queued")
        if stt == "done":
            continue                      # finished steps are filled from their results once the evidence is pulled
        add(i, f"{i} in step {step}", "clean", "running" if stt == "running" else "queued",
            f"{note}; est. {eta}", SRC_Q)
for i, why in EXCLUDED_CLEAN.items():
    add(i, f"{i} (will not run on the Pi)", "clean", "excluded", why, "clean-pi/campaign/not-run.txt")
_done = [st for st, v in PROG.items() if v == "done" and st not in ("h11-first", "speed")]

# finished campaign steps, read from the pulled evidence (clean Pi only; never mixed with dirty)
CAMP = os.path.join(EVID, "clean-pi", "campaign")
def _clean_results(step, ids):
    p = os.path.join(CAMP, step, "results.txt")
    if (step not in PROG and not os.path.isdir(os.path.dirname(p))) or not os.path.exists(p):
        return
    for line in open(p, encoding="utf-8", errors="replace"):
        m = re.match(r"(PASS|FAIL|SKIP)\s+(\S+)\s*(.*)", line.rstrip())
        b = m and re.match(r"[A-Z]+\d+", m.group(2))
        if m and step == "D4-verify" and m.group(2) == "BOOT":      # the post-reboot check labels its lines BOOT, they are D4
            add("D4", f"D4 {m.group(3)}"[:70], "clean", m.group(1).lower(), "", rel(p))
        elif b and b.group() in ids:
            add(b.group(), f"{m.group(2)} {m.group(3)}"[:70], "clean", m.group(1).lower(), "", rel(p))
RERUN = os.path.join(CAMP, "sec-rerun-login", "rerun.xml")   # clinician/admin demo logins need MFA on the Pi build
RERUN_NAMES = {tc.get("name", "") for tc in ET.parse(RERUN).getroot().iter("testcase")} if os.path.exists(RERUN) else set()
def _clean_junit(path, pick):
    if not os.path.exists(path):
        return
    for tc in ET.parse(path).getroot().iter("testcase"):
        i = pick(tc.get("name", ""))
        if not i or (path != RERUN and tc.get("name", "") in RERUN_NAMES):
            continue                      # a test that was rerun counts once, from the rerun
        stt, msg = "pass", ""
        for ch in tc:
            if ch.tag == "error":
                stt, msg = "void", "setup error, test never ran: " + (ch.get("message") or "")[:70]
            elif ch.tag == "failure":
                stt, msg = "fail", (ch.get("message") or "")[:90]
            elif ch.tag == "skipped":
                msg = (ch.get("message") or "")[:90]
                stt = "xfail" if "xfail" in (ch.get("type", "") + msg).lower() else "skip"
        if stt == "skip" and msg.startswith("login did not yield a token") and os.path.exists(RERUN):
            continue                      # superseded by the rerun below
        add(i, tc.get("name", ""), "clean", stt, msg, rel(path), "rerun as admin, answering the TOTP step" if path == RERUN else "")
_clean_results("net-N1-N7", set(_rng("N", 1, 7)))
_clean_results("hw-safe", {"H1", "H3", "H4", "H6", "H8", "H9", "H12"})
_clean_results("hw-H2", {"H2"})
_clean_results("hw-H7", {"H7"})
_clean_results("net-disruptive", {"N8", "N9", "N10", "N11"})
_clean_results("hw-risky", {"H5", "H10", "H13"})
_clean_results("dur-destructive", {"D1", "D2", "D3", "D6", "D12"})
_clean_results("dur-D7-D9-D10", {"D7", "D9", "D10"})
_clean_results("h11-second", {"H11"})
_clean_results("D4-verify", {"D4"})
for _r in REC:
    if _r["env"] == "clean" and _r["id"] == "H7":
        _r["note"] = "8 h soak (shortened from 24 h); backend RSS stepped up ~60 MiB near 02:15 UTC then stayed flat; cause not identified"
for _st, _f in (("race-live", "race-live/races-live.xml"), ("rn-live", "rn-live/rn-live.xml")):
    if os.path.exists(os.path.join(CAMP, _st + "-rerun", os.path.basename(_f))):
        _f = f"{_st}-rerun/{os.path.basename(_f)}"      # the rerun replaces the void first attempt
        _clean_junit(os.path.join(CAMP, _f), lambda n: (ID_RE.match(n) or [None, None])[1] and ID_RE.match(n).group(1).upper())
    elif _st in PROG:
        _clean_junit(os.path.join(CAMP, _f), lambda n: (ID_RE.match(n) or [None, None])[1] and ID_RE.match(n).group(1).upper())
if "sec" in PROG:
    for _f in ("sec/app.xml", "sec/cookies.xml"):
        _clean_junit(os.path.join(CAMP, _f), lambda n: sec_id(n))
    _clean_junit(RERUN, lambda n: sec_id(n))
    _p = os.path.join(CAMP, "sec.log")
    for line in open(_p, encoding="utf-8", errors="replace"):
        k = re.match(r"(FAIL|NOTE)\s+(host NIC|docker bridge).*\((CK[34])[^)]*\):\s*(.*)", line.rstrip())
        if k:                             # sniff_cookies.sh: CK3 hit on the host NIC = fail; CK4 hit on the bridge = documented residual
            add(k.group(3), f"{k.group(3)} {k.group(2)}: {k.group(4)}"[:70], "clean", "fail" if k.group(1) == "FAIL" else "xfail",
                "hit in the capture", rel(_p), "" if k.group(1) == "FAIL" else "Caddy->backend hop is plaintext by design (residual)")
        m = re.match(r"(PASS|FAIL)\s+((?:CK|T|A)\d+)\s*(.*)", line.rstrip())
        if m:
            add(m.group(2), f"{m.group(2)} {m.group(3)}"[:70], "clean", m.group(1).lower(), "host script", rel(_p))

    _h = os.path.join(CAMP, "sec", "host.log")      # the A10 lines are only in host.log, not at line start in sec.log
    for line in open(_h, encoding="utf-8", errors="replace") if os.path.exists(_h) else ():
        m = re.match(r"(PASS|FAIL)\s+(A10)\s*(.*)", line.rstrip())
        if m:
            add("A10", f"A10 {m.group(3)}"[:70], "clean", m.group(1).lower(), "host script", rel(_h))

# ------------------------------------------------------------------ reference measurements (no pass/fail threshold)
# Speed, ping and latency numbers straight from the raw results.txt INFO lines. Reference only.
PROBE_RE = re.compile(r"INFO\s+(\S+)\s+probe n=(\d+) fail=(\d+) 5xx=(\d+) ok%=([\d.]+) med=([\d.]+)ms p95=([\d.]+)ms p99=([\d.]+)ms max=([\d.]+)ms")
MEAS, NET = [], []
# folders whose speed / ping baseline is reported (env, folder, label)
NET_SRC = [("dirty", "production-pi/results/20261112-140432", "via Cloudflare tunnel (public URL)"),
           ("dirty", "production-pi/results/20261112-140837", "origin run, direct to Caddy (43/103 were HTTP 429)"),
           ("pilot", "test-pi/results/20261112-153040", "pilot on .7, LAN, old build"),
           ("clean", "clean-pi/campaign/speed", "Clean Pi via Cloudflare tunnel (public URL)")]
for env, folder, lab in NET_SRC:
    pth = os.path.join(EVID, folder, "results.txt")
    if not os.path.exists(pth):
        continue
    for line in open(pth, encoding="utf-8", errors="replace"):
        m = re.match(r"INFO\s+(base|origin)_(down|up)_mbps\s+([\d.]+)", line)
        if m:
            NET.append({"env": env, "label": lab, "metric": f"speed {m.group(2)}load Mbit/s", "value": m.group(3), "src": rel(pth)})
        m = re.match(r"INFO\s+(?:base|origin)_ping_([\d.]+)_avg_ms\s+([\d.]+)\s+\(min=([\d.]+) max=([\d.]+) ([^)]*)\)", line)
        if m:
            NET.append({"env": env, "label": lab, "metric": f"ping {m.group(1)} avg ms",
                        "value": f"{m.group(2)} (min {m.group(3)}, max {m.group(4)}, {m.group(5)})", "src": rel(pth)})
        m = PROBE_RE.match(line.strip())
        if m and m.group(1) in ("base_tunnel", "origin_tunnel"):
            NET.append({"env": env, "label": lab, "metric": f"{m.group(1).split('_')[0]} request latency ms (n={m.group(2)}, failed {m.group(3)})",
                        "value": f"median {m.group(6)}, p95 {m.group(7)}, p99 {m.group(8)}, max {m.group(9)}", "src": rel(pth)})
# per-test latency probes from every counted run
for env, folder, ids, voids in PI_RULES:
    pth = os.path.join(EVID, folder, "results.txt")
    for line in open(pth, encoding="utf-8", errors="replace"):
        m = PROBE_RE.match(line.strip())
        if not m:
            continue
        base = re.match(r"[A-Z]+\d+", m.group(1))
        if not base or base.group() not in ids and base.group() not in voids:
            continue
        MEAS.append({"env": env, "id": base.group(), "test": m.group(1), "n": int(m.group(2)), "fail": int(m.group(3)),
                     "ok": m.group(5), "med": float(m.group(6)), "p95": float(m.group(7)), "p99": float(m.group(8)),
                     "max": float(m.group(9)), "src": rel(pth), "void": base.group() in voids})
json.dump({"network_reference": NET, "latency_probes": MEAS}, open(os.path.join(REPORT, "measurements.json"), "w"), indent=1)

# ------------------------------------------------------------------ views (one SVG pair per Pi)
VIEWS = {
    "clean": {"title": "Clean Prod Pi (192.168.1.7): latest build 72039b8", "envs": ["clean", "lap"],
              "sub": "System under test: fresh install, CLARION only, memory cgroup on, 343 API paths. Campaign started 2026-11-12 18:05 UTC "
                     "(about 36 h, in the order listed in the detail file): purple = running / queued, brown = will not run on the Pi (reason in the "
                     "detail file). 'In-process' = the race suite run on this laptop against the same HEAD code. The pilot on this Pi (old build) is not counted.",
              "cols": [("clean", "Pi live"), ("lap", "in-process")], "why": "not in the campaign", "meas": ["clean"]},
    "dirty": {"title": "Dirty Prod Pi (192.168.1.10): old build from 2026-10-24", "envs": ["dirty"],
              "sub": "Long-running live demo (82% disk used, other workloads, memory cgroup off), 328 API paths. Reference only: offline since "
                     "2026-11-12; destructive tests were not run on it.",
              "cols": [("dirty", "Pi live")], "why": "not run on the live node (destructive, long soak, or needs host access)", "meas": ["dirty"]},
}
IDS = rep.all_ids()
cov = rep.static_status()
PRI = {"fail": 7, "xfail": 6, "pass": 5, "skip": 4, "void": 3, "running": 2, "queued": 1, "excluded": 0}


def agg(i, env):
    sts = [r["status"] for r in REC if r["id"] == i and r["env"] == env]
    return max(sts, key=lambda x: PRI[x]) if sts else "notrun"


SCEN = {v: {i: {e: agg(i, e) for e in VIEWS[v]["envs"]} for i in IDS} for v in VIEWS}
NOTRUN = {v: [] for v in VIEWS}
for v, V in VIEWS.items():
    for i in IDS:
        if not any(r["id"] == i and r["env"] in V["envs"] for r in REC):
            why = NOTRUN_WHY.get(i) or GROUP_WHY.get(re.match(r"[A-Z]+", i).group(), "") or V["why"]
            NOTRUN[v].append({"id": i, "group": re.match(r"[A-Z]+", i).group(), "test": i, "env": "-", "status": "notrun",
                              "detail": why, "note": "", "src": ""})
tally = {v: {e: Counter(SCEN[v][i][e] for i in IDS) for e in VIEWS[v]["envs"]} for v in VIEWS}
checks = {e: Counter(r["status"] for r in REC if r["env"] == e) for e in ENV}
json.dump({"records": REC, "scenarios": SCEN, "scenario_tally": {v: {e: dict(c) for e, c in d.items()} for v, d in tally.items()},
           "check_tally": {e: dict(c) for e, c in checks.items()}}, open(os.path.join(REPORT, "matrix.json"), "w"), indent=1)
with open(os.path.join(REPORT, "matrix.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["id", "group", "test", "env", "status", "detail", "note", "src"])
    w.writeheader(); w.writerows(REC)

SUBLAB = {"clean": "Pi live", "dirty": "Pi live", "lap": "In-process (laptop)", "pilot": "Pilot (old build)"}


# ------------------------------------------------------------------ overview svg (one Pi)
def overview(v):
    V = VIEWS[v]
    cw, ch, gap, x0 = 58, 52, 4, 160
    body, y = "", 62
    import textwrap
    for k, ln in enumerate(textwrap.wrap(V["sub"], 135)[:5]):
        body += t(16, 46 + 15 * k, ln, 11, GREY)
        y += 15 if k else 0
    y += 26
    ncol = len(V["cols"])
    for g in ORDER:
        body += t(x0 - 10, y + 30, GROUPS[g], 12, FG, "end", True)
        for k in range(1, COUNTS[g] + 1):
            i, x = f"{g}{k}", x0 + (k - 1) * (cw + gap)
            parts = " | ".join(f"{lab}: {LABEL[SCEN[v][i][e]]}" for e, lab in V["cols"])
            body += (f'<g><title>{esc(i)} {esc(TITLES.get(i, ""))} | {esc(parts)}</title>'
                     f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" fill="#161b22" stroke="{rep.C[cov[i]]}" stroke-width="2"/>'
                     + t(x + 5, y + 14, i, 11, FG, "start", True))
            sw = (cw - 10 - (ncol - 1) * 3) / ncol
            for n, (e, lab) in enumerate(V["cols"]):
                st_ = SCEN[v][i][e]
                body += (f'<rect x="{x + 5 + n * (sw + 3):.1f}" y="{y + 22}" width="{sw:.1f}" height="22" rx="2" fill="{COL[st_]}"'
                         + (f' stroke="{LINE}"' if st_ == "notrun" else "") + "/>")
            body += "</g>"
        y += ch + 10
    body += t(16, y + 22, "Scenarios (94 in the spec)", 13, FG, "start", True)
    hx = 16 + 190
    for n, st_ in enumerate(ST):
        body += (f'<rect x="{hx + n * 104}" y="{y + 34}" width="12" height="12" rx="2" fill="{COL[st_]}" stroke="{LINE}"/>'
                 + t(hx + n * 104 + 18, y + 45, LABEL[st_], 10, GREY))
    for r, (e, lab) in enumerate(V["cols"]):
        yy = y + 70 + r * 24
        body += t(16, yy, lab if ncol > 1 else "Pi live", 12, FG, "start", True)
        for n, st_ in enumerate(ST):
            c = tally[v][e].get(st_, 0)
            body += t(hx + n * 104 + 18, yy, c, 13, FG if c else GREY, "start", bool(c))
    y += 70 + ncol * 24 + 16
    body += t(16, y + 4, "Individual tests / checks that ran (the full list is in the detail file)", 13, FG, "start", True)
    for r, (e, lab) in enumerate(V["cols"]):
        yy = y + 30 + r * 24
        body += t(16, yy, lab if ncol > 1 else "Pi live", 12, FG, "start", True)
        for n, st_ in enumerate(ST[:5]):
            c = checks[e].get(st_, 0)
            body += t(hx + n * 104 + 18, yy, c, 13, FG if c else GREY, "start", bool(c))
    y += 30 + ncol * 24 + 8
    # reference network line
    menv = V["meas"][0]
    nets = [n for n in NET if n["env"] == menv and "tunnel" not in n["label"].lower() and "origin" not in n["label"].lower()] \
        or [n for n in NET if n["env"] == menv]
    first = {}
    for n in nets:
        first.setdefault(n["metric"], n)
    if menv == "dirty":
        g = lambda k: (first.get(k) or {}).get("value", "n/a").split(" (")[0]
        txt = (f"Reference network, via the tunnel (3 runs): download {g('speed download Mbit/s')} Mbit/s, upload {g('speed upload Mbit/s')} Mbit/s, "
               f"ping 1.1.1.1 {g('ping 1.1.1.1 avg ms')} ms, ping 8.8.8.8 {g('ping 8.8.8.8 avg ms')} ms")
        tun = [n for n in NET if n["env"] == "dirty" and n["metric"].startswith("base request")]
        if tun:
            txt += "   |   tunnel request: " + tun[0]["value"].replace("median", "median").replace(",", " ms,") + " ms"
    else:
        cn = {n["metric"]: n for n in NET if n["env"] == "clean"}
        g = lambda k: (cn.get(k) or {}).get("value", "n/a").split(" (")[0]
        txt = (f"Reference network, via the tunnel (3 runs): download {g('speed download Mbit/s')} Mbit/s, upload {g('speed upload Mbit/s')} Mbit/s, "
               f"ping 1.1.1.1 {g('ping 1.1.1.1 avg ms')} ms, ping 8.8.8.8 {g('ping 8.8.8.8 avg ms')} ms")
        tun = [n for n in NET if n["env"] == "clean" and n["metric"].startswith("base request")]
        if tun:
            txt += "   |   tunnel request: " + tun[0]["value"].replace(",", " ms,") + " ms"
    body += t(16, y + 10, txt[:260], 11, "#58a6ff")
    y += 22
    if v == "clean":
        pc = checks["pilot"]
        body += t(16, y + 10, f"Pilot on this Pi before the rebuild (old build, LAN path), NOT counted above: {pc.get('pass', 0)} passed, "
                              f"{pc.get('fail', 0)} failed, {pc.get('void', 0)} void. Listed at the end of the detail file.", 11, "#d29922")
        y += 22
    body += t(16, y + 14, "Box outline = test built: green automated, amber partial / manual / needs hardware, red not built. "
                          "Grey square with outline = not run. Amber square = ran but void (invalid, see detail).", 10, GREY)
    return svg(x0 + 15 * (cw + gap) + 20, y + 34, body, V["title"] + ": status by scenario")


# ------------------------------------------------------------------ detail svg (one Pi)
def detail(v):
    V = VIEWS[v]
    W, rh = 1240, 17
    xs = {"id": 16, "test": 74, "env": 560, "st": 690, "det": 790}
    body, y = "", 60
    import textwrap
    for k, ln in enumerate(textwrap.wrap(V["sub"], 170)[:4]):
        body += t(16, 46 + 14 * k, ln, 11, GREY)
        y += 14 if k else 0
    lx = 16
    for st_ in ST:
        body += (f'<rect x="{lx}" y="{y - 10}" width="11" height="11" rx="2" fill="{COL[st_]}" stroke="{LINE}"/>'
                 + t(lx + 16, y, LABEL[st_], 10, GREY))
        lx += 134
    y += 22

    def chip(x, yy, st_):
        return (f'<rect x="{x}" y="{yy - 11}" width="86" height="14" rx="3" fill="{COL[st_]}"' + (f' stroke="{LINE}"' if st_ == "notrun" else "") + "/>"
                + t(x + 43, yy, st_ if st_ != "notrun" else "not run", 10, "#fff" if st_ != "notrun" else GREY, "middle", True))

    def section(rows_all, title_extra=""):
        nonlocal y, body
        for g in ORDER:
            rows = [r for r in rows_all if r["group"] == g]
            if not rows:
                continue
            big = [r for r in rows if r["test"].startswith("test_a1_anonymous_refused")]
            rows = [r for r in rows if r not in big]
            rows.sort(key=lambda r: (int(re.search(r"\d+", r["id"]).group()), r["env"], r["test"]))
            gc = Counter(r["status"] for r in rows_all if r["group"] == g)
            body += (f'<rect x="8" y="{y}" width="{W - 16}" height="24" rx="4" fill="#161b22"/>'
                     + t(16, y + 16, f"{g}  {GROUPS[g]}{title_extra}", 13, FG, "start", True)
                     + t(W - 20, y + 16, "   ".join(f"{LABEL[x].split(' (')[0]} {gc[x]}" for x in ST if gc[x]), 10, GREY, "end"))
            y += 34
            if big:
                n = len(big)
                body += t(16, y, f"A1  anonymous request refused on every secured route: {n} cases, "
                                 f"{sum(r['status'] == 'pass' for r in big)} passed, {sum(r['status'] == 'fail' for r in big)} failed", 11, FG)
                y += 8
                per = 70
                for k, r in enumerate(big):
                    gx, gy = 16 + (k % per) * 15, y + (k // per) * 14
                    body += (f'<g><title>{esc(r["test"])} {esc(r["status"])}</title><rect x="{gx}" y="{gy}" width="12" height="11" rx="2" '
                             f'fill="{COL[r["status"]]}"/></g>')
                y += ((n - 1) // per + 1) * 14 + 10
                rows = [r for r in big if r["status"] != "pass"] + rows
            for r in rows:
                nm = r["test"] if len(r["test"]) < 76 else r["test"][:73] + "..."
                d = (r["note"] or r["detail"] or TITLES.get(r["id"], ""))
                d = d if len(d) < 80 else d[:77] + "..."
                body += (f'<g><title>{esc(r["test"])} | {esc(r["src"])}</title>'
                         + t(xs["id"], y, r["id"], 11, GREY, "start", True) + t(xs["test"], y, nm, 11, FG)
                         + t(xs["env"], y, SUBLAB.get(r["env"], "-") if r["env"] != "-" else "-", 10, GREY) + chip(xs["st"], y, r["status"])
                         + t(xs["det"], y, d, 10, GREY) + "</g>")
                y += rh
            y += 14

    def measurements(envs, heading):
        """Reference table: speed / ping / latency. No pass/fail."""
        nonlocal y, body
        net = [n for n in NET if n["env"] in envs]
        pr = [m for m in MEAS if m["env"] in envs]
        body += (f'<rect x="8" y="{y}" width="{W - 16}" height="24" rx="4" fill="#0b2545"/>'
                 + t(16, y + 16, heading, 13, "#58a6ff", "start", True)
                 + t(W - 20, y + 16, "reference only, no pass/fail threshold; client round trip (curl), not server time", 10, GREY, "end"))
        y += 34
        if not net and not pr:
            body += t(16, y, "No measurements yet on this Pi.", 11, GREY)
            y += rh + 10
            return
        if net:
            body += t(16, y, "Connection baseline (speed, ping, request latency)", 11, FG, "start", True)
            y += rh
            for n in net:
                body += (f'<g><title>{esc(n["src"])}</title>' + t(16, y, n["label"][:48], 10, GREY) + t(360, y, n["metric"], 11, FG)
                         + t(640, y, n["value"][:90], 11, "#58a6ff") + "</g>")
                y += rh
            y += 10
        if pr:
            body += t(16, y, "Latency under each test (one HTTPS request per 1.1 s; ms)", 11, FG, "start", True)
            y += rh
            cols = [("test", 16), ("n", 330), ("failed", 390), ("ok %", 460), ("median", 540), ("p95", 630), ("p99", 720), ("max", 810)]
            for c, x in cols:
                body += t(x, y, c, 10, GREY, "start", True)
            y += rh
            for m in sorted(pr, key=lambda m: (m["env"], int(re.search(r"\d+", m["id"]).group()), m["test"])):
                col = "#d29922" if m["void"] else FG
                body += (f'<g><title>{esc(m["src"])}</title>' + t(16, y, m["test"] + (" (void run)" if m["void"] else "") + (f"   [{SUBLAB[m['env']]}]" if len(envs) > 1 else ""), 11, col)
                         + t(330, y, m["n"], 11, col) + t(390, y, m["fail"], 11, "#da3633" if m["fail"] else col)
                         + t(460, y, m["ok"], 11, col) + t(540, y, f"{m['med']:g}", 11, col) + t(630, y, f"{m['p95']:g}", 11, col)
                         + t(720, y, f"{m['p99']:g}", 11, col) + t(810, y, f"{m['max']:g}", 11, col) + "</g>")
                y += rh
        y += 14

    section([r for r in REC if r["env"] in V["envs"]] + NOTRUN[v])
    measurements(V["meas"], "Reference measurements: network speed, ping and latency")
    if v == "clean":
        pil = [r for r in REC if r["env"] == "pilot"]
        body += (f'<rect x="{8}" y="{y}" width="{W - 16}" height="30" rx="4" fill="#3b2f0a"/>'
                 + t(16, y + 20, "PILOT on this Pi before the rebuild: old build, LAN path, memory cgroup toggled. NOT counted in the Clean results above.",
                     13, "#d29922", "start", True))
        y += 42
        section(pil, "  (pilot)")
        measurements(["pilot"], "Pilot reference measurements (old build, LAN)")
    return svg(W, y + 20, body, V["title"] + ": every test and its result")


for v in VIEWS:
    open(os.path.join(STRESS, f"coverage-{v}.svg"), "w", encoding="utf-8").write(overview(v))
    open(os.path.join(STRESS, f"coverage-{v}-detail.svg"), "w", encoding="utf-8").write(detail(v))
for old in ("coverage.svg", "coverage-detail.svg"):
    q = os.path.join(STRESS, old)
    if os.path.exists(q):
        os.remove(q)


# ------------------------------------------------------------------ STATUS.md
def trow(label, c, keys):
    return f"| {label} | " + " | ".join(str(c.get(k, 0)) for k in keys) + " |"


S = ["# Stress and security tests: status\n",
     "Generated by `qa/result/final/2026-11-13/tools/build_matrix.py` from the raw evidence in `../evidence/` (source paths in the tables are relative to it). One SVG pair per Pi in `qa/stress/` (copies in this folder): "
     "`coverage-clean.svg` / `coverage-clean-detail.svg` and `coverage-dirty.svg` / `coverage-dirty-detail.svg`. "
     "Data: `matrix.json`, `matrix.csv`, `measurements.json` (speed, ping, latency). Narrative and tables: `qa/stress/result.md`.\n",
     "**Rule:** results from the two Pis, or from different builds, are never mixed. Clean Prod Pi (192.168.1.7) is the system under test; "
     "Dirty Prod Pi (192.168.1.10) is a labelled reference on the old build.\n"]
K = ["pass", "fail", "xfail", "skip", "void", "notrun"]
H = "| | passed | failed | known gap | skipped | void | not run |\n|---|---|---|---|---|---|---|"
for v, V in VIEWS.items():
    S.append(f"## {V['title']}\n")
    S.append("Scenarios (94 in the spec)\n\n" + H)
    for e, lab in V["cols"]:
        S.append(trow(lab, tally[v][e], K))
    S.append("\nIndividual tests and checks that ran\n\n" + "| | passed | failed | known gap | skipped | void |\n|---|---|---|---|---|---|")
    for e, lab in V["cols"]:
        S.append(trow(lab, checks[e], K[:5]))
    S.append("")
S.append("## Reference network measurements (no threshold; client round trip)\n")
S.append("| Pi | Path | Metric | Value |\n|---|---|---|---|")
for n in NET:
    S.append(f"| {ENV[n['env']]} | {n['label']} | {n['metric']} | {n['value']} |")
S.append("\nPer-test latency lines (n, failed, median, p95, p99, max) are in `measurements.json` and in the detail SVGs.")
S.append("\n## Clean Prod Pi: what is done\n")
_cs = Counter(r["status"] for r in REC if r["env"] == "clean")
S.append(f"- Campaign plan on the Pi: {len(set(r['id'] for r in REC if r['env'] == 'clean' and r['status'] in ('queued', 'running')))} scenarios queued or running, "
         f"{_cs.get('excluded', 0)} will not run (reasons in `clean-pi/campaign/not-run.txt` and the detail SVG). Finished steps so far: "
         f"{', '.join(sorted(st for st, v in PROG.items() if v == 'done')) or 'none'}; running: {', '.join(sorted(st for st, v in PROG.items() if v == 'running')) or 'none'}.")
S.append("- Latest build (`72039b8`, 343 API paths) deployed, verified from the public URL (logins, formerly missing routes now 401, edge headers, TLS 1.3).\n"
         "- Toolchain installed, memory cgroup on, Cloudflare tunnel with verified origin TLS.\n"
         "- In-process race suite (R1 to R15, A14) on HEAD code: 30 passed, 4 skipped, 1 known gap.\n"
         "- Campaign order: speed baseline, security suite, R/RN live, N1-N7, H1-H4/H6/H8/H9/H12/H2, H7 (24 h), D11 (6 h), then destructive N8-N11, H5/H10/H13, D1/D2/D3/D6/D12, D7/D9/D10, H11 second reading, D4 reboot last.")
pc = checks["pilot"]
S.append(f"\n## Pilot on the Clean Pi (old build, not counted): {pc.get('pass', 0)} passed, {pc.get('fail', 0)} failed, {pc.get('void', 0)} void\n")
S.append("Worth rerunning on the new build: H5 (the OOM killer chose a gunicorn process), H10 (healthz failed while the disk was full); "
         "nothing in the network results: the N1/N2/N3/N6/N8/N11 failures were all HTTP 429 from a probe-gap bug in overnight.sh (fixed), "
         "so they say nothing about the stack. N9 recovery 8.1 s (cause not checked).")
S.append("\n## Dirty Prod Pi: findings on the old build\n")
S.append("- N9: 15.1 s tunnel recovery after a 60 s blackout (limit 5 s).\n- D9/D10: no watchdog setting, no container log rotation, journald uncapped.\n"
         "- Cloudflare edge: TLS 1.0/1.1 accepted; plain http not redirected.\n- Cookies: refresh cookie Path=/; login response lacks no-store.\n"
         "- 19 routes that exist in the repo answer 404 (the deployed image is older than the repo).\n- CK7 reuse test to confirm against the 8 s grace.\n"
         "- Void: H6 (memory limit never applied, cgroup off), A1 role matrix (502s during an outage), H7 and H11 (halted).")
S.append("\n## Open decisions\n")
S.append("1. H7 length on the Clean Pi: 6 h or 24 h?\n2. Start the full campaign on the Clean Pi.\n"
         "3. Fix list from the findings (Cloudflare TLS and HTTPS settings, cookie path, no-store, vendoring MinIO instead of quay.io).")
open(os.path.join(REPORT, "STATUS.md"), "w", encoding="utf-8").write("\n".join(S) + "\n")

print("records:", len(REC), " network reference rows:", len(NET), " latency probes:", len(MEAS))
for v in VIEWS:
    for e, lab in VIEWS[v]["cols"]:
        print(f"{v:6} {lab:12} scenarios {dict(tally[v][e])}   checks {dict(checks[e])}")
print("pilot checks", dict(checks["pilot"]))
