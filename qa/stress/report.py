#!/usr/bin/env python3
"""Collect stress-test results -> graphs + coverage.svg + report.html.  Stdlib only.

    python report.py                      # newest results/<ts>/ under this folder
    python report.py DIR [DIR ...]        # any result folders (e.g. copied back from the Pi)
    python report.py --coverage-only      # just rewrite coverage.svg (no results needed)

Reads, recursively: pytest junit *.xml, Pi results.txt (PASS|FAIL|SKIP|INFO <ID> ...),
*.probe.csv (curl probe), *_stats_history.csv (Locust), collect.csv (Pi host metrics).
Writes into the FIRST dir: summary.json, results.svg, latency.svg, resources.svg, report.html,
and always qa/stress/coverage.svg.
"""
import csv, glob, html, json, os, re, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BG, FG, GREY, GRID = "#0d1117", "#e6edf3", "#8b949e", "#30363d"
C = {"pass": "#2ea043", "fail": "#da3633", "xfail": "#58a6ff", "skip": "#6e7681",
     "auto": "#2ea043", "partial": "#d29922", "missing": "#da3633"}

# id -> (group, title).  Ranges expanded below.  PARTIAL = built but manual / skipped / needs hardware.
GROUPS = {"N": "Network degradation", "H": "Hardware pressure", "D": "Reliability",
          "R": "Races", "RN": "Races on bad networks", "CK": "Cookies", "T": "Transport",
          "A": "App attack surface"}
COUNTS = {"N": 12, "H": 13, "D": 12, "R": 15, "RN": 10, "CK": 11, "T": 7, "A": 14}
PARTIAL = {"N12": "manual mobile test", "H7": "24 h soak, not exercised", "H11": "eMMC life compared by hand",
           "R12": "no endpoint has a version column", "R13": "no patient merge/delete endpoint",
           "R14": "covered by test_mpi_federation", "RN4": "UI race, needs Playwright",
           "RN5": "needs 15 min token expiry", "RN8": "stalled clients, not true half-open",
           "D5": "needs POWER_CYCLE_CMD + reboot hook", "D4": "needs verify_after_boot after reboot", "D8": "needs restic repo + backup sandbox",
           "D11": "multi-day run, Ctrl-C ends early", "A14": "replay needs NTAG 424 DNA (xfail)",
           "T4": "exposure_scan.sh (host only)", "T5": "exposure_scan.sh (host only)",
           "A9": "host_audit.sh (Pi only)", "A10": "host_audit.sh (Pi only)",
           "A11": "host_audit.sh (Pi only)"}
NOT_BUILT = {}

ID_RE = re.compile(r"^(?:test_)?(rn\d+|r\d+|ck\d+|t\d+|a\d+|n\d+|h\d+|d\d+)", re.I)
RANK = {"fail": 3, "xfail": 2, "pass": 1, "skip": 0}


def all_ids():
    return [f"{g}{i}" for g, n in COUNTS.items() for i in range(1, n + 1)]


def group_of(i):
    return re.match(r"[A-Z]+", i).group()


# ---------------------------------------------------------------- parsing
def parse_junit(p, out):
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError:
        return
    for tc in root.iter("testcase"):
        m = ID_RE.match(tc.get("name", ""))
        if not m:
            continue
        i = m.group(1).upper()
        st = "pass"
        for ch in tc:
            if ch.tag in ("failure", "error"):
                st = "fail"
            elif ch.tag == "skipped":
                st = "xfail" if "xfail" in (ch.get("type", "") + ch.get("message", "")).lower() else "skip"
        out.append((i, st, tc.get("name", ""), float(tc.get("time") or 0)))


def parse_results_txt(p, out):
    for line in open(p, encoding="utf-8", errors="replace"):
        m = re.match(r"(PASS|FAIL|SKIP|INFO)\s+([A-Za-z]+\d+)([a-z]?)\s*(.*)", line)
        if m and m.group(1) != "INFO":
            out.append((m.group(2).upper(), m.group(1).lower(), m.group(2) + m.group(3) + " " + m.group(4)[:60], 0))


def read_csv(p):
    try:
        return list(csv.DictReader(open(p, encoding="utf-8", errors="replace")))
    except OSError:
        return []


def collect(dirs):
    res, probes, resources = [], {}, []
    for d in dirs:
        for p in glob.glob(os.path.join(d, "**", "*"), recursive=True):
            b = os.path.basename(p)
            if b.endswith(".xml"):
                parse_junit(p, res)
            elif b == "results.txt":
                parse_results_txt(p, res)
            elif b.endswith(".probe.csv"):
                rows = [(float(r["epoch"]), float(r["total_s"]) * 1000, r["code"]) for r in read_csv(p)
                        if r.get("epoch", "").replace(".", "").isdigit() and r.get("total_s")]
                if rows:
                    probes[b[:-10]] = rows
            elif b.endswith("_stats_history.csv"):
                rows = [(float(r["Timestamp"]), float(r["95%"]), "") for r in read_csv(p)
                        if r.get("Name") == "Aggregated" and r.get("95%", "N/A") != "N/A"]
                if rows:
                    probes[b[:-18] + " (locust p95)"] = rows
            elif b == "collect.csv":
                resources += read_csv(p)
    return res, probes, resources


def verdicts(res):
    best = {}
    for i, st, *_ in res:
        if i not in best or RANK[st] > RANK[best[i]]:
            best[i] = st
    return best


# ---------------------------------------------------------------- svg helpers
def esc(s):
    return html.escape(str(s), quote=True)


def svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="system-ui,Segoe UI,sans-serif"><rect width="{w}" height="{h}" fill="{BG}"/>'
            f'<text x="16" y="26" fill="{FG}" font-size="16" font-weight="bold">{esc(title)}</text>{body}</svg>')


def t(x, y, s, size=12, fill=FG, anchor="start", bold=False):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"'
            f'{" font-weight=\"bold\"" if bold else ""}>{esc(s)}</text>')


def results_svg(res):
    per = {}
    for i, st, *_ in res:
        per.setdefault(group_of(i), {k: 0 for k in RANK})[st] += 1
    if not per:
        return svg(700, 80, t(16, 56, "no results yet", 13, GREY), "Results by group")
    rows, mx = list(per.items()), max(sum(v.values()) for v in per.values())
    body = ""
    for n, (g, v) in enumerate(rows):
        y, x = 50 + n * 34, 190
        body += t(180, y + 16, f"{GROUPS.get(g, g)} ({g})", 12, FG, "end")
        for k in ("pass", "fail", "xfail", "skip"):
            w = 460 * v[k] / mx
            if w:
                body += (f'<rect x="{x}" y="{y}" width="{w:.1f}" height="22" fill="{C[k]}"/>'
                         + (t(x + w / 2, y + 16, v[k], 11, "#fff", "middle") if w > 18 else ""))
                x += w
        body += t(x + 8, y + 16, sum(v.values()), 11, GREY)
    lx = 190
    for k in ("pass", "fail", "xfail", "skip"):
        body += f'<rect x="{lx}" y="{58 + len(rows) * 34}" width="12" height="12" fill="{C[k]}"/>' + t(lx + 18, 69 + len(rows) * 34, k)
        lx += 90
    return svg(720, 100 + len(rows) * 34, body, "Results by group (xfail = known gap, a finding)")


def line_chart(series, title, ylabel, lines=()):
    """series: {name: [(x, y)]}  lines: [(y, label)] threshold guides."""
    W, H, L, R, T, B = 900, 360, 60, 20, 44, 46
    pts = [p for s in series.values() for p in s]
    if not pts:
        return svg(700, 80, t(16, 56, "no data yet", 13, GREY), title)
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts) or 1
    ymax = max(max(p[1] for p in pts), *(y for y, _ in lines if y <= 3 * max(p[1] for p in pts)), 1) * 1.08
    X = lambda x: L + (x - x0) / ((x1 - x0) or 1) * (W - L - R)
    Y = lambda y: H - B - y / ymax * (H - B - T)
    body = ""
    for k in range(5):
        v = ymax * k / 4
        body += f'<line x1="{L}" x2="{W-R}" y1="{Y(v):.0f}" y2="{Y(v):.0f}" stroke="{GRID}"/>' + t(L - 6, Y(v) + 4, f"{v:.0f}", 10, GREY, "end")
    for y, lab in lines:
        if y <= ymax:
            body += (f'<line x1="{L}" x2="{W-R}" y1="{Y(y):.1f}" y2="{Y(y):.1f}" stroke="#da3633" stroke-dasharray="5 4"/>'
                     + t(W - R, Y(y) - 4, lab, 10, "#da3633", "end"))
    pal = ["#58a6ff", "#2ea043", "#d29922", "#bc8cff", "#f778ba", "#79c0ff", "#ffa657", "#56d364"]
    for n, (name, s) in enumerate(list(series.items())[:8]):
        col = pal[n % 8]
        d = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in s[:3000:max(1, len(s) // 3000)])
        body += f'<polyline fill="none" stroke="{col}" stroke-width="1.5" points="{d}"/>'
        body += f'<rect x="{L + n * 105}" y="{H - 22}" width="10" height="10" fill="{col}"/>' + t(L + n * 105 + 14, H - 13, name[:14], 10, GREY)
    body += t(14, T + 4, ylabel, 10, GREY) + t(W - R, H - B + 14, f"{(x1 - x0) / 60:.1f} min", 10, GREY, "end")
    return svg(W, H, body, title)


def latency_svg(probes):
    s = {k: [(a - v[0][0], b) for a, b, _ in v] for k, v in probes.items() for v in [sorted(probes[k])]}
    return line_chart(s, "Client round trip over time", "ms", [(1000, "median limit 1 s"), (10000, "max limit 10 s")])


def resources_svg(rows):
    def col(k):
        out = []
        for r in rows:
            try:
                out.append((float(r["epoch"]), float(r[k])))
            except (KeyError, ValueError):
                pass
        return out
    s = {"temp C": col("temp_c"), "load1": col("load1"), "mem used MB/10": [(a, b / 10) for a, b in col("mem_used_mb")],
         "iowait %": col("iowait_pct")}
    s = {k: [(a - v[0][0], b) for a, b in v] for k, v in s.items() if v}
    return line_chart(s, "Pi resources during the run", "value", [(80, "80 C throttle zone")])


# ---------------------------------------------------------------- coverage
def static_status():
    text = ""
    for p in glob.glob(os.path.join(HERE, "**", "*"), recursive=True):
        if p.endswith((".py", ".sh")) and os.path.basename(p) not in ("report.py", "launch.py"):
            text += open(p, encoding="utf-8", errors="replace").read() + "\n"
    for f in ("test_races.py", "test_tag_attacks.py"):
        p = os.path.join(REPO, "backend", "tests", f)
        if os.path.exists(p):
            text += open(p, encoding="utf-8", errors="replace").read()
    out = {}
    for i in all_ids():
        found = re.search(rf"(?<![A-Za-z0-9]){i}(?![0-9])", text, re.I) is not None
        out[i] = "missing" if (i in NOT_BUILT or not found) else ("partial" if i in PARTIAL else "auto")
    return out


def coverage_svg(verd):
    cov = static_status()
    cw, ch, gap, x0 = 52, 40, 4, 150
    rows = list(COUNTS)
    body, y = "", 54
    for g in rows:
        body += t(x0 - 10, y + 26, f"{GROUPS[g]}", 12, FG, "end", True)
        for k in range(1, COUNTS[g] + 1):
            i, x = f"{g}{k}", x0 + (k - 1) * (cw + gap)
            tip = PARTIAL.get(i) or NOT_BUILT.get(i) or ""
            body += (f'<g><title>{esc(i)} {esc(tip)}</title><rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="4" fill="{C[cov[i]]}"/>'
                     + t(x + cw / 2, y + 25, i, 11, "#fff", "middle", True))
            if i in verd:
                body += f'<circle cx="{x + cw - 8}" cy="{y + 8}" r="5" fill="{C[verd[i]]}" stroke="#fff" stroke-width="1"/>'
            body += "</g>"
        y += ch + 10
    n = len(cov)
    auto = sum(v == "auto" for v in cov.values())
    part = sum(v == "partial" for v in cov.values())
    body += t(16, y + 14, f"{auto} automated, {part} partial/manual, {n - auto - part} not built, of {n} spec scenarios "
                          f"({100 * (auto + part / 2) / n:.0f}% weighted)", 12, FG)
    lx = 16
    for k, lab in (("auto", "automated"), ("partial", "partial / manual / needs hardware"), ("missing", "not built")):
        body += f'<rect x="{lx}" y="{y + 28}" width="12" height="12" fill="{C[k]}"/>' + t(lx + 18, y + 39, lab, 11, GREY)
        lx += 120 if k == "auto" else 250
    body += t(16, y + 62, "dot = last run: ", 11, GREY)
    lx = 100
    for k in ("pass", "fail", "xfail", "skip"):
        body += f'<circle cx="{lx}" cy="{y + 58}" r="5" fill="{C[k]}"/>' + t(lx + 10, y + 62, k, 11, GREY)
        lx += 70
    return svg(x0 + 15 * (cw + gap) + 20, y + 80, body, "Stress and security test coverage (spec scenarios vs built tests)"), cov



def inventory_svg():
    """Static count of what exists: test functions per python file, scenario ids per Pi script."""
    suites = [("races", os.path.join(REPO, "backend", "tests"), ["test_races.py", "test_tag_attacks.py"], "#58a6ff"),
              ("live", os.path.join(HERE, "py"), ["test_*.py"], "#2ea043"),
              ("sec", os.path.join(HERE, "sec"), ["test_*.py"], "#d29922"),
              ("pi", os.path.join(HERE, "pi"), ["*.sh"], "#bc8cff")]
    rows = []
    for name, d, pats, col in suites:
        for pat in pats:
            for p in sorted(glob.glob(os.path.join(d, pat))):
                src = open(p, encoding="utf-8", errors="replace").read()
                if p.endswith(".py"):
                    n = len(re.findall(r"^\s*(?:async )?def test_", src, re.M))
                else:
                    n = len({m.upper() for m in re.findall(r"(?:check|record (?:PASS|FAIL)|skip|info)\s+\"?([NHD]\d+)", src)})
                if n:
                    rows.append((name, os.path.basename(p), n, col))
    mx = max([r[2] for r in rows] or [1])
    body = ""
    for k, (suite, f, n, col) in enumerate(rows):
        y = 44 + k * 26
        w = 440 * n / mx
        body += (t(250, y + 15, f, 12, FG, "end") + f'<rect x="260" y="{y}" width="{w:.1f}" height="20" rx="3" fill="{col}"/>'
                 + t(266 + w, y + 15, n, 12, GREY) + t(900, y + 15, suite, 11, col, "end"))
    tot = {}
    for suite, _, n, _ in rows:
        tot[suite] = tot.get(suite, 0) + n
    h = 44 + len(rows) * 26 + 40
    body += t(16, h - 14, "  |  ".join(f"{k}: {v}" for k, v in tot.items()) + f"  |  total {sum(tot.values())}"
              " (python = test functions, pi = scenario ids; parametrized tests expand at run time)", 11, GREY)
    return svg(920, h, body, "What stress and security tests exist")

# ---------------------------------------------------------------- main
def main(argv):
    cov_only = "--coverage-only" in argv
    dirs = [a for a in argv if not a.startswith("--")]
    if not dirs and not cov_only:
        runs = sorted(glob.glob(os.path.join(HERE, "results", "*", "")))
        dirs = [runs[-1]] if runs else []
    res, probes, resources = collect(dirs) if dirs else ([], {}, [])
    verd = verdicts(res)
    cov_svg, cov = coverage_svg(verd)
    open(os.path.join(HERE, "coverage.svg"), "w", encoding="utf-8").write(cov_svg)
    open(os.path.join(HERE, "tests.svg"), "w", encoding="utf-8").write(inventory_svg())
    print("wrote", os.path.join(HERE, "coverage.svg"), "and tests.svg")
    if cov_only or not dirs:
        return 0
    out = dirs[0]
    parts = {"results.svg": results_svg(res), "latency.svg": latency_svg(probes), "resources.svg": resources_svg(resources)}
    for n, s in parts.items():
        open(os.path.join(out, n), "w", encoding="utf-8").write(s)
    tally = {k: sum(v == k for v in verd.values()) for k in RANK}
    run = {}
    if os.path.exists(os.path.join(out, "run.json")):
        run = json.load(open(os.path.join(out, "run.json")))
    summary = {"scenarios_with_result": len(verd), "tally": tally, "failed": sorted(i for i, v in verd.items() if v == "fail"),
               "known_gaps_xfail": sorted(i for i, v in verd.items() if v == "xfail"), "suites": run.get("suites", {})}
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=2)
    rows = "".join(f"<tr><td>{esc(i)}</td><td style='color:{C[st]}'>{st}</td><td>{esc(n)}</td></tr>"
                   for i, st, n, _ in sorted(res, key=lambda r: (-RANK[r[1]], r[0])) if st in ("fail", "xfail"))
    suites = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v.get('status'))}</td><td>{esc(v.get('note', ''))}</td></tr>"
                     for k, v in run.get("suites", {}).items())
    page = (f"<!doctype html><meta charset=utf-8><title>CLARION stress report</title>"
            f"<body style='background:{BG};color:{FG};font-family:system-ui;max-width:960px;margin:2em auto;padding:0 1em'>"
            f"<h1>CLARION stress report</h1><p>{tally['pass']} pass, {tally['fail']} fail, {tally['xfail']} known gaps, {tally['skip']} skipped"
            f" ({len(verd)} scenarios with a result)</p><h2>Suites</h2><table>{suites}</table>"
            f"{parts['results.svg']}{parts['latency.svg']}{parts['resources.svg']}{cov_svg}"
            f"<h2>Failures and known gaps</h2><table>{rows or '<tr><td>none</td></tr>'}</table></body>")
    open(os.path.join(out, "report.html"), "w", encoding="utf-8").write(page)
    print(f"{tally}\nreport: {os.path.join(out, 'report.html')}")
    return 1 if tally["fail"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
