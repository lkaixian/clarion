"""Verify the audit_logs tamper-evident hash chain (roadmap P2.9).

Walks every row in `seq` order, recomputes each `row_hash`, and checks
linkage + gap-freeness + the chain-tip state row + every daily seal. Exits
0 if the chain is intact, 1 on the first break (with detail), 2 on a usage
/ environment error.

Wire it into cron (nightly) and CI (P2.11). Read-only -- safe to run
against production. The nightly production run should pass `--worm` so a
tail-truncation that also rewrote the in-DB seal rows is caught against the
off-box WORM copy.

Usage:
  python -m db.verify_audit_chain
  python -m db.verify_audit_chain --worm        # also cross-check the WORM seals
  python -m db.verify_audit_chain --json
  DATABASE_URL=mysql+pymysql://clarion_report:PW@host/clarion python -m db.verify_audit_chain
"""
import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the full report as JSON")
    ap.add_argument("--no-seals", action="store_true", help="skip the daily-seal cross-check")
    ap.add_argument("--worm", action="store_true",
                    help="also re-read each seal from the WORM bucket (implies seal checking)")
    args = ap.parse_args()
    if args.worm and args.no_seals:
        ap.error("--worm cannot be combined with --no-seals (the WORM check needs the seals)")

    # Imported here, not at module scope: `app.audit` raises on a missing
    # SECRET_KEY, and we want that to surface as the exit-2 "environment
    # error" below, not an exit-1 that a cron job can't tell from "broken".
    from app.audit import verify_chain
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        report = verify_chain(db, check_seals=not args.no_seals, check_worm=args.worm)
    finally:
        db.close()

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"rows        : {report.total_rows}")
        print(f"last seq    : {report.last_seq}")
        print(f"last hash   : {report.last_hash}")
        print(f"tip matches : {report.state_matches_tip}")
        print(f"sealed days : {report.sealed_days}")
        if report.seal_mismatches:
            print(f"seal breaks : {', '.join(report.seal_mismatches)}")
        if report.worm_checked:
            print(f"worm check  : {'OK' if not report.worm_mismatches else 'MISMATCH: ' + ', '.join(report.worm_mismatches)}")
        if report.ok:
            print("RESULT      : OK -- chain intact")
        elif report.first_break_seq is not None:
            print(f"RESULT      : BROKEN at seq {report.first_break_seq}")
            print(f"              {report.first_break_reason}")
        elif report.first_break_reason:
            print(f"RESULT      : BROKEN -- {report.first_break_reason}")
        elif report.worm_mismatches:
            print("RESULT      : BROKEN -- WORM seal(s) missing or mismatched: "
                  + ", ".join(report.worm_mismatches))
        elif report.seal_mismatches:
            print("RESULT      : BROKEN -- in-DB seal(s) mismatched: "
                  + ", ".join(report.seal_mismatches))
        else:
            print("RESULT      : BROKEN")

    return 0 if report.ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
