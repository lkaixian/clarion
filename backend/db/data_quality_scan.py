"""Run the batch data-quality scan (roadmap P2.12, the tender).

Walks every enabled rule in `app/data_quality.py`, UPSERTs the findings into
`data_quality_alerts`, and auto-resolves alerts whose finding stopped
firing. Read-heavy, write-light -- safe against production.

Wire into cron (e.g. hourly or nightly). Admins review the results at
`GET /admin/data-quality`.

Usage:
  python -m db.data_quality_scan
  python -m db.data_quality_scan --json
  python -m db.data_quality_scan --list-rules
  DATA_QUALITY_DISABLED_RULES=duplicate_patients,anomaly_dates python -m db.data_quality_scan
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the ScanResult as JSON")
    ap.add_argument("--list-rules", action="store_true", help="print the rule registry and exit")
    args = ap.parse_args()

    from app import data_quality
    from app.database import SessionLocal

    if args.list_rules:
        for r in data_quality.RULES:
            print(f"{r.key:34s} -> {', '.join(r.emits)}")
        return 0

    db = SessionLocal()
    try:
        result = data_quality.run_scan(db)
    finally:
        db.close()

    if args.json:
        print(json.dumps(result.as_dict(), indent=2))
    else:
        print(f"ran {result.rules_run} rules"
              + (f" (skipped {', '.join(result.rules_skipped)})" if result.rules_skipped else ""))
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
