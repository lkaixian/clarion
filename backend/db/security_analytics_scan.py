"""Run the access-anomaly scan (roadmap P4.5, the tender).

Walks both rules in `app/security_analytics.py`, UPSERTs findings into
`security_alerts`, and auto-resolves alerts whose bucket has fully rotated
out of the lookback window. Read-heavy, write-light -- safe against
production.

Wire into cron (e.g. every 15-30 minutes -- the rules re-derive their whole
lookback window each run, so a missed run just gets caught by the next
one). Admins review the results at `GET /admin/security-alerts`.

Usage:
  python -m db.security_analytics_scan
  python -m db.security_analytics_scan --json
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the ScanResult as JSON")
    args = ap.parse_args()

    from app import security_analytics
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        result = security_analytics.run_scan(db)
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(f"ran {result.rules_run} rules"
              + (f" (failed: {', '.join(k for k, _ in result.rules_failed)})" if result.rules_failed else ""))
        print(f"findings     : {result.findings}")
        print(f"new alerts   : {result.new_alerts}")
        print(f"auto-resolved: {result.auto_resolved}")
        print(f"still open   : {result.still_open}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
