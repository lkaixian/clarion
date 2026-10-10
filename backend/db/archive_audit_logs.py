"""Archive completed audit-log days to WORM cold storage (see app/audit_archive.py).

Run from cron after seal_audit_day, e.g.:
  30 0 * * *  cd /app/backend && python -m db.archive_audit_logs

  python -m db.archive_audit_logs                  # every day older than --older-than-days
  python -m db.archive_audit_logs --older-than-days 90 --verify
Copy-only: nothing is deleted from audit_logs.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--older-than-days", type=int, default=90)
    ap.add_argument("--verify", action="store_true", help="re-verify each archived day from storage")
    args = ap.parse_args()

    from app import models
    from app.audit_archive import archive_day, verify_archived_day
    from app.database import SessionLocal

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.older_than_days)
    db = SessionLocal()
    try:
        first = db.query(models.AuditLog.timestamp).order_by(models.AuditLog.timestamp.asc()).first()
        if first is None:
            print("no audit rows")
            return 0
        d = first[0].date()
        done = bad = 0
        while d < cutoff.date():
            if archive_day(db, d) is not None:
                done += 1
                if args.verify and not verify_archived_day(d)[0]:
                    bad += 1
                    print(f"VERIFY FAILED {d}")
            d += timedelta(days=1)
        print(f"archived/confirmed {done} day(s), {bad} verify failure(s)")
        return 1 if bad else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
