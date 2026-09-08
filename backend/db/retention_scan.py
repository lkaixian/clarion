"""Run the retention-schedule scan (roadmap P2.10 / PDPA s.10).

FLAGS records past their category's retention window into
`retention_review_items` for admin review. Never deletes. Run from cron
(weekly is plenty). Admins review at `GET /admin/retention/review` and
disposition each item after the actual archival / partition drop.

Usage:
  python -m db.retention_scan
  python -m db.retention_scan --json
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from app.database import SessionLocal
    from app.retention import run_retention_scan

    db = SessionLocal()
    try:
        res = run_retention_scan(db)
    finally:
        db.close()

    if args.json:
        print(json.dumps(res.as_dict(), indent=2))
    else:
        print(f"scanned      : {res.scanned}")
        print(f"newly flagged: {res.flagged_new}")
        print(f"open reviews : {res.flagged_total}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
