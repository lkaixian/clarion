"""Offline emergency-export appliance CLI (P5.3).

Two roles, run on different machines:

  Central (nightly cron, produces the file the Branch edge appliance carries):
    python -m db.emergency_export_appliance build --facility "University Branch" \\
        --recipient age1... --out /appliance/emergency-campus-branch.json.age

  Appliance itself (during an actual WAN cut, looks up one patient by NRIC):
    python -m db.emergency_export_appliance query --in emergency-campus-branch.json.age \\
        --identity /secure/appliance-key.txt --nric 900101-01-1234

`--recipient` may repeat (age supports multiple recipients). Recipients and
the identity file follow the same custody rule as
`backend/backup/README.md`: the identity (private key) lives only on the
appliance, never on the central host that runs `build`.

`build` writes a central `audit_logs` row per run (action=
emergency_export_build). `query` cannot -- the whole point of the
appliance is looking a patient up while the central DB is unreachable -- so
it instead appends one line to a LOCAL, append-only log next to the export
file (`<export>.access.log` by default, `--log` to override): timestamp +
sha256(NRIC), never the NRIC itself. Security review 2026-09-15 (P5.3):
reconcile this into central `audit_logs` once connectivity returns
(a follow-up script, not built here -- same "documented wiring gap, not a
built pipeline" precedent as `backend/backup/README.md`'s own
`status.jsonl` feeding into P5.1 alerting).
"""
import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path


def _build(args) -> int:
    from app.database import SessionLocal
    from app.emergency_export import build_emergency_export, encrypt_export

    db = SessionLocal()
    try:
        payload = build_emergency_export(db, args.facility)
    finally:
        db.close()
    blob = encrypt_export(payload, args.recipient)
    out = Path(args.out)
    out.write_bytes(blob)
    print(f"{args.facility}: {len(payload)} patients -> {out} ({len(blob)} bytes, age-encrypted)")
    return 0


def _query(args) -> int:
    from app.emergency_export import decrypt_export
    from app.nric import normalize_nric

    blob = Path(args.in_).read_bytes()
    patients = decrypt_export(blob, args.identity)
    target = normalize_nric(args.nric)
    hits = [p for p in patients if p.get("national_id") == target]

    log_path = Path(args.log) if args.log else Path(args.in_).with_suffix(Path(args.in_).suffix + ".access.log")
    nric_hash = hashlib.sha256(target.encode("utf-8")).hexdigest()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} nric_sha256={nric_hash} hits={len(hits)}\n")

    if not hits:
        print(f"no match for {args.nric} in this export ({len(patients)} patients on file)")
        return 1
    for p in hits:
        print(f"-- {p['full_name']} (age {p.get('age')}) --")
        for key in ("blood_type", "allergies", "medications", "conditions"):
            if key in p:
                print(f"  {key}: {p[key]}")
        omitted = p.get("omitted_non_critical") or {}
        if omitted:
            print(f"  (non-critical items on file but omitted here: {omitted})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="export + encrypt one facility's critical-for-emergency subset")
    b.add_argument("--facility", required=True)
    b.add_argument("--recipient", action="append", required=True, help="age public key; repeatable")
    b.add_argument("--out", required=True)
    b.set_defaults(func=_build)

    q = sub.add_parser("query", help="decrypt an export and look up one patient by NRIC (run ON the appliance)")
    q.add_argument("--in", dest="in_", required=True)
    q.add_argument("--identity", required=True, help="age private-key file")
    q.add_argument("--nric", required=True)
    q.add_argument("--log", default=None, help="local access-log path (default: <in>.access.log)")
    q.set_defaults(func=_query)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - CLI top-level
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
