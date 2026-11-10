#!/usr/bin/env python3
"""One command: run the stress/security suites, collect everything, build the report.

    python qa/stress/launch.py                       # every suite that can run with what is set
    python qa/stress/launch.py --suite races,sec     # pick suites
    python qa/stress/launch.py --env stress.env      # KEY=VALUE file (kept out of git, see README)
    python qa/stress/launch.py --pi                  # on the Pi (Linux): also run pi/run_all.sh
    python qa/stress/launch.py --list                # show suites and what each needs

Suites: races (in-process, no setup) | live (qa/stress/py, needs BASE_URL) | sec (qa/stress/sec, needs BASE_URL)
        | pi (pi/run_all.sh, Linux root only).  A suite that cannot run is recorded as skipped with the reason.
Output: qa/stress/results/<timestamp>/  (junit xml, logs, run.json, report.html, *.svg) + qa/stress/coverage.svg
"""
import argparse, datetime, json, os, platform, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
SECRETS = ("PASS", "TOKEN", "SECRET", "KEY")

# name -> (cwd, needs env names, command builder(out) -> list)
SUITES = {
    "races": (os.path.join(REPO, "backend"), [],
              lambda o: [PY, "-m", "pytest", "tests/test_races.py", "tests/test_tag_attacks.py", "-q", "-rxXs", f"--junitxml={o}/races.xml"]),
    "live": (os.path.join(HERE, "py"), ["BASE_URL"],
             lambda o: [PY, "-m", "pytest", "-q", "-rxXs", f"--junitxml={o}/live.xml"]),
    "sec": (os.path.join(HERE, "sec"), ["BASE_URL"],
            lambda o: [PY, "-m", "pytest", "-q", "-rxXs", f"--junitxml={o}/sec.xml"]),
}


def load_env(path):
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def alias_env():
    # the two suites name the same login differently
    for a, b in (("SEC_USER", "ADMIN_EMAIL"), ("SEC_PASS", "ADMIN_PASSWORD")):
        if os.environ.get(b) and not os.environ.get(a):
            os.environ[a] = os.environ[b]
        elif os.environ.get(a) and not os.environ.get(b):
            os.environ[b] = os.environ[a]


def run_suite(name, cmd, cwd, out):
    log = os.path.join(out, f"{name}.log")
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as f:
        try:
            rc = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, timeout=int(os.environ.get("SUITE_TIMEOUT", "5400"))).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    tail = open(log, encoding="utf-8", errors="replace").read().strip().splitlines()[-1:] or [""]
    return {"status": "pass" if rc == 0 else "fail", "rc": rc, "seconds": round(time.time() - t0, 1), "note": tail[0][:160]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", default="", help="comma list: races,live,sec,pi (default: all runnable)")
    ap.add_argument("--env", help="KEY=VALUE file")
    ap.add_argument("--pi", action="store_true", help="include the Pi shell suite (Linux, root)")
    ap.add_argument("--destructive", action="store_true", help="pass --destructive to pi/run_all.sh")
    ap.add_argument("--out", help="results folder (default results/<timestamp>)")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.env:
        load_env(a.env)
    alias_env()
    if a.list:
        for n, (cwd, need, _) in SUITES.items():
            print(f"{n:6} needs: {', '.join(need) or 'nothing'}")
        print("pi     needs: Linux, root, docker (use --pi)")
        return 0

    want = [s for s in a.suite.split(",") if s] or list(SUITES) + (["pi"] if a.pi else [])
    out = a.out or os.path.join(HERE, "results", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out, exist_ok=True)
    suites = {}
    for s in want:
        if s == "pi":
            if platform.system() != "Linux" or not hasattr(os, "geteuid") or os.geteuid() != 0 or not shutil.which("bash"):
                suites[s] = {"status": "skipped", "note": "needs Linux + root (run on the Pi: sudo -E python3 launch.py --suite pi)"}
                continue
            cmd = ["bash", os.path.join(HERE, "pi", "run_all.sh")] + (["--destructive"] if a.destructive else [])
            os.environ["RESULTS_DIR"] = os.path.join(out, "pi")
            print(f"== pi: {' '.join(cmd)}", flush=True)
            suites[s] = run_suite(s, cmd, os.path.join(HERE, "pi"), out)
        elif s in SUITES:
            cwd, need, build = SUITES[s]
            miss = [n for n in need if not os.environ.get(n)]
            if miss:
                suites[s] = {"status": "skipped", "note": f"set {', '.join(miss)}"}
                continue
            print(f"== {s}", flush=True)
            suites[s] = run_suite(s, build(out), cwd, out)
        else:
            suites[s] = {"status": "skipped", "note": "unknown suite"}
        print(f"   {s}: {suites[s]['status']} {suites[s].get('note', '')}", flush=True)

    env_seen = {k: ("set" if os.environ.get(k) else "unset") for k in
                ("BASE_URL", "SEC_USER", "ADMIN_EMAIL", "TOXIPROXY_URL", "DATABASE_URL")}
    json.dump({"when": datetime.datetime.now().isoformat(timespec="seconds"), "host": platform.node(),
               "platform": platform.platform(), "env": env_seen, "suites": suites},
              open(os.path.join(out, "run.json"), "w"), indent=2)
    rc = subprocess.run([PY, os.path.join(HERE, "report.py"), out]).returncode
    bad = [k for k, v in suites.items() if v["status"] == "fail"]
    print(f"\nresults: {out}\nreport:  {os.path.join(out, 'report.html')}\ncoverage: {os.path.join(HERE, 'coverage.svg')}")
    return 1 if (bad or rc) else 0


if __name__ == "__main__":
    sys.exit(main())
