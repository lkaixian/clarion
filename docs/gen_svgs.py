"""Regenerate docs/tests.svg and docs/features.svg.  Run: python docs/gen_svgs.py
Tests are counted statically (no deps needed); features are the hand-kept FEATURES list below.
Status: g = built, tested, in the demo; y = built+tested but the outside part only against fakes; r = not built.
"""
import re, glob, os, html
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOLD = ' font-weight="bold"'
W, BG, GREY, TXT = 1000, "#0d1117", "#8b949e", "#fff"
COL = {"g": "#2ea043", "y": "#d29922", "r": "#da3633"}
LABEL = {"g": "Built, tested, in the demo", "y": "Built and tested, but the outside part only against fakes", "r": "Not built or not connected"}

def squarify(items, x, y, w, h):
    """items: [(weight, payload)] sorted desc -> [(x,y,w,h,payload)]. Greedy row layout."""
    out, items = [], list(items)
    while items:
        total = sum(i[0] for i in items); side_len = h if w >= h else w; other = w if w >= h else h
        row, best = [], 1e18
        for i in range(1, len(items) + 1):
            r = items[:i]; s = sum(a[0] for a in r); thick = other * s / total
            worst = max(max(thick / (side_len * a[0] / s), (side_len * a[0] / s) / thick) for a in r)
            if worst > best: break
            best, row = worst, r
        s = sum(a[0] for a in row); frac = s / total
        if w >= h:
            rw = w * frac; yy = y
            for a in row:
                ch = h * a[0] / s; out.append((x, yy, rw, ch, a[1])); yy += ch
            x += rw; w -= rw
        else:
            rh = h * frac; xx = x
            for a in row:
                cw = w * a[0] / s; out.append((xx, y, cw, rh, a[1])); xx += cw
            y += rh; h -= rh
        items = items[len(row):]
    return out

def grid(n, x, y, w, h, gap=2):
    """n equal cells packed into a box -> [(x,y,w,h)]."""
    best = None
    for cols in range(1, n + 1):
        rows = -(-n // cols); cw, ch = (w - gap * (cols - 1)) / cols, (h - gap * (rows - 1)) / rows
        if cw < 3 or ch < 3: continue
        score = abs(cw - ch * 1.2)
        if best is None or score < best[0]: best = (score, cols, rows, cw, ch)
    if not best: return []
    _, cols, rows, cw, ch = best
    return [(x + (i % cols) * (cw + gap), y + (i // cols) * (ch + gap), cw, ch) for i in range(n)]

def svg(h, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{h}" viewBox="0 0 {W} {h}"><rect width="100%" height="100%" fill="{BG}"/>{body}</svg>'

def text(x, y, s, size=12, fill=TXT, bold=False):
    return f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-family="sans-serif" font-size="{size}"{BOLD if bold else ""}>{html.escape(s)}</text>'

# ---------- tests.svg ----------
def count_tests():
    pats = [("backend/tests/test_*.py", r"^\s*(?:async\s+)?def test_", "py"),
            ("web/src/**/*.test.js*", r"^\s*(?:it|test)\(", "web"),
            ("mobile_flutter/test/**/*_test.dart", r"^\s*(?:test|testWidgets)\(", "app")]
    out = []
    for g, rx, kind in pats:
        for f in glob.glob(os.path.join(ROOT, g), recursive=True):
            n = len(re.findall(rx, open(f, encoding="utf-8", errors="ignore").read(), re.M))
            if n:
                name = re.sub(r"^test_|\.test$|_test$", "", os.path.splitext(os.path.basename(f))[0])
                out.append((n, f"{name}", os.path.relpath(f, ROOT).replace("\\", "/")))
    return sorted(out, reverse=True)

def tests_svg():
    t = count_tests(); total = sum(n for n, *_ in t); top = 62
    H = 900
    b = text(10, 24, f"{total} automated tests across {len(t)} areas", 16)
    b += text(10, 44, "Each bordered box is one test file; the bigger the box, the more tests it has. Each green square is one automated check.", 12, GREY)
    for x, y, w, h, (n, name, path) in squarify([(n, (n, nm, p)) for n, nm, p in t], 6, top, W - 12, H - top - 6):
        b += f'<g><title>{html.escape(path)}: {n} tests</title><rect x="{x:.1f}" y="{y:.1f}" width="{w-3:.1f}" height="{h-3:.1f}" rx="4" fill="none" stroke="{GREY}" stroke-width="1.5"/>'
        b += text(x + 5, y + 12, f"{name} ({n})", 10.5, bold=True) if w > 60 else ""
        for cx, cy, cw, ch in grid(n, x + 5, y + 17, w - 13, h - 23):
            b += f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="{ch:.1f}" rx="2" fill="{COL["g"]}"/>'
        b += "</g>"
    return svg(H, b)

# ---------- features.svg ----------
FEATURES = {
 "Emergency & NFC": [("Public emergency scan", "g"), ("NFC card + register", "g"), ("Encrypted offline tag (AES-GCM)", "g"), ("Offline read log", "g"), ("Break-glass access", "g"), ("Paramedic responder tier", "g"), ("Scan location map", "g"), ("Tamper-proof tag (NTAG 424)", "r")],
 "Patients & records": [("Patient list + scoping", "g"), ("Full record + cross-facility audit", "g"), ("Documents + previews", "g"), ("PDF/HEIC thumbnails", "g"), ("Family / dependants", "g"), ("Staff + patient profiles", "g"), ("Clinical forms builder", "g")],
 "Clinical": [("SOAP sign-off", "g"), ("Orders (CPOE)", "g"), ("Drug-safety screen (DDI/allergy/ATC)", "g"), ("Drug-name catalogue", "g"), ("Lab results inbox (HL7)", "y"), ("DICOM viewer", "y"), ("Modality worklist", "r")],
 "Local AI": [("Record summary (local LLM)", "g"), ("NRIC OCR", "g"), ("Voice to SOAP", "g"), ("CDS hint", "g"), ("Report narrative", "g"), ("Audit-log explainer", "g")],
 "Billing & payments": [("Billing + charge master", "g"), ("Cashier day close", "g"), ("Refunds (second approver)", "g"), ("Deposits", "g"), ("PDF + email receipts", "g"), ("Patient online payment", "y"), ("Charge master Excel import", "r"), ("Real payment gateway", "r")],
 "Pharmacy & supply": [("Inventory + stock events", "g"), ("Medicine photos", "g"), ("Purchase orders", "g"), ("Suppliers", "g"), ("Stock decrement on dispense", "r")],
 "Front desk": [("Reception + queue", "g"), ("TV calling display", "g"), ("Ticket + label printing", "g"), ("Self-booking (mobile)", "g"), ("Campus eligibility check", "y"), ("Real SMP/SMS/e-klinik", "r")],
 "Security": [("Login + lockout + rate limits", "g"), ("Refresh tokens", "g"), ("LDAP / AD login", "y"), ("Role-based + facility access", "g"), ("Append-only audit log", "g"), ("Access-anomaly alerts", "g"), ("Data-quality alerts", "g"), ("Edge proxy + TLS", "g")],
 "Multi-hospital": [("Federated record locator", "g"), ("Signed visit fetch", "g"), ("Branch edge profile", "y"), ("Offline emergency export", "y"), ("Consent proof for fetch", "r")],
 "Reporting": [("Reporting engine", "g"), ("Predictive forecasts", "g"), ("Population risk bands", "g"), ("Dashboard", "g")],
 "Platform & ops": [("MariaDB + Alembic", "g"), ("Object store (MinIO)", "g"), ("Metrics + logs + alerts", "g"), ("Backups (encrypted)", "y"), ("Load test", "y"), ("Handover manuals", "g")],
 "Apps": [("Web console", "g"), ("Flutter mobile app", "g"), ("NFC bridge", "g"), ("Multi-language strings", "y")],
}

def features_svg():
    allf = [f for v in FEATURES.values() for f in v]; cnt = {k: sum(1 for _, s in allf if s == k) for k in COL}
    b = text(10, 24, f"{len(allf)} features in {len(FEATURES)} areas, and how far each one got", 16)
    b += text(10, 44, "Each bordered box is an area of the app; the bigger the box, the more features it has. Each coloured cell is one feature.", 12, GREY)
    lx = 10
    for k in "gyr":
        s = f"{LABEL[k]}: {cnt[k]}"; b += f'<rect x="{lx}" y="62" width="12" height="12" rx="2" fill="{COL[k]}"/>' + text(lx + 18, 72, s, 12, "#c9d1d9"); lx += 18 + len(s) * 6.4 + 24
    H = 700
    for x, y, w, h, (name, fs) in squarify([(len(v), (k, v)) for k, v in sorted(FEATURES.items(), key=lambda kv: -len(kv[1]))], 7, 90, W - 14, H - 97):
        b += f'<rect x="{x+0:.1f}" y="{y:.1f}" width="{w-4:.1f}" height="{h-4:.1f}" rx="4" fill="none" stroke="{GREY}" stroke-width="1.5"/>' + text(x + 7, y + 14, f"{name} ({len(fs)})", 12, bold=True)
        for (cx, cy, cw, ch), (fn, st) in zip(grid(len(fs), x + 6, y + 22, w - 16, h - 30, 3), fs):
            b += f'<g><title>{html.escape(fn)}: {LABEL[st]}</title><rect x="{cx:.1f}" y="{cy:.1f}" width="{cw:.1f}" height="{ch:.1f}" rx="2" fill="{COL[st]}"/>'
            chars = max(6, int(cw / 5.8)); words, line, lines = fn.split(), "", []
            for wd in words:
                if len(line) + len(wd) + 1 > chars and line: lines.append(line); line = wd
                else: line = (line + " " + wd).strip()
            lines.append(line)
            for i, l in enumerate(lines[: max(1, int((ch - 4) / 12))]): b += text(cx + 4, cy + 13 + i * 12, l, 10.5)
            b += "</g>"
    return svg(H, b)

if __name__ == "__main__":
    for name, fn in (("tests.svg", tests_svg), ("features.svg", features_svg)):
        open(os.path.join(ROOT, "docs", name), "w", encoding="utf-8").write(fn()); print("wrote docs/" + name)
