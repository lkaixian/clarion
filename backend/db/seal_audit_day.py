"""Write the daily WORM seal for the audit hash chain (roadmap P2.9).

Records one `audit_seals` row per UTC day: the [from_seq, to_seq] range,
the row count, and to_seq's row_hash -- a short digest that pins the whole
day's audit history and (best-effort) is mirrored to the object-store WORM
bucket. Idempotent: re-sealing a day whose digest changed raises (tamper).

Run once a day from cron, shortly after midnight UTC, e.g.:
  5 0 * * *  cd /app/backend && python -m db.seal_audit_day >> /var/log/clarion/audit-seal.log 2>&1

Usage:
  python -m db.seal_audit_day                # seal yesterday (UTC)
  python -m db.seal_audit_day --date 2026-09-01
  python -m db.seal_audit_day --backfill     # seal every unsealed past day
  python -m db.seal_audit_day --no-mirror    # DB row only, skip object storage
"""
import argparse
import sys
from datetime import date, datetime, timedelta, timezone


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="UTC day to seal (YYYY-MM-DD); default: yesterday")
    ap.add_argument("--backfill", action="store_true", help="seal every unsealed past UTC day")
    ap.add_argument("--no-mirror", action="store_true", help="skip the object-store WORM mirror")
    args = ap.parse_args()
    if args.date and args.backfill:
        ap.error("--date and --backfill are mutually exclusive")
    mirror = not args.no_mirror

    # Imported here so a missing SECRET_KEY surfaces as the exit-2 error below.
    from app.audit import seal_day
    from app.database import SessionLocal
    from app import models

    def seal_one(db, d: date) -> str:
        """seal one day; returns 'sealed' | 'empty' | 'exists' for the summary."""
        existed = (
            db.query(models.AuditSeal).filter(models.AuditSeal.seal_date == d.isoformat()).first()
            is not None
        )
        seal = seal_day(db, d, mirror_to_object_store=mirror)
        if seal is None:
            print(f"{d.isoformat()}: no audit rows -- nothing to seal")
            return "empty"
        print(
            f"{d.isoformat()}: seq {seal.from_seq}..{seal.to_seq} "
            f"({seal.row_count} rows) hash={seal.chain_hash[:16]}... "
            f"{'mirrored=' + seal.object_key if seal.object_key else 'not mirrored'}"
        )
        return "exists" if existed else "sealed"

    counts = {"sealed": 0, "empty": 0, "exists": 0}
    db = SessionLocal()
    try:
        if args.backfill:
            first = db.query(models.AuditLog).order_by(models.AuditLog.seq.asc()).first()
            if first is None:
                print("no audit rows at all")
                return 0
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            sealed = {s.seal_date for s in db.query(models.AuditSeal).all()}
            d = _row_day(first.timestamp)
            while d <= yesterday:
                if d.isoformat() not in sealed:
                    counts[seal_one(db, d)] += 1
                d += timedelta(days=1)
            print(f"-- backfill done: {counts['sealed']} sealed, "
                  f"{counts['exists']} already-sealed, {counts['empty']} empty days")
        elif args.date:
            seal_one(db, date.fromisoformat(args.date))
        else:
            seal_one(db, (datetime.now(timezone.utc) - timedelta(days=1)).date())
    finally:
        db.close()
    return 0


def _row_day(value) -> date:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace(" ", "T"))
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.date()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
