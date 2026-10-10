"""Cold storage for the audit hash chain (roadmap P2.9 follow-up).

Packs one completed UTC day of `audit_logs` into a gzip JSONL object plus a
manifest in the WORM `clarion-reports-archive` bucket (7-year COMPLIANCE
retention, same as the daily seals). The manifest pins {from_seq, to_seq,
row_count, first prev_hash, last row_hash, sha256 of the object}, so an
archived day can be re-verified without the DB: `verify_archived_day` re-hashes
every row and re-links the chain.

Deliberately COPY-only: rows stay in `audit_logs` (append-only triggers forbid
DELETE, and `verify_chain` is gap-free from genesis). Freeing DB space is a
DBA partition drop of fully-archived days -- see docs/deployment.md -- done
only after `verify_archived_day` passes for them.
"""
import gzip
import hashlib
import json
from datetime import date
from types import SimpleNamespace
from typing import Optional

from . import models, storage
from .audit import _day_bounds, compute_row_hash
from .audit_hash import canonical_ts

_COLS = ("id", "seq", "patient_id", "actor", "actor_role", "actor_facility",
         "action", "fields_accessed", "detail", "prev_hash", "row_hash")


def _keys(d: date) -> "tuple[str, str]":
    base = f"audit-archive/{d.year}/{d.isoformat()}"
    return base + ".jsonl.gz", base + ".manifest.json"


def archive_day(db, d: date, store=None) -> Optional[dict]:
    """Archive one UTC day. Idempotent; returns the manifest, or None if the
    day has no rows. Raises RuntimeError if an existing manifest disagrees
    with the live rows (tamper) or the written object fails read-back."""
    store = store or storage.get_object_store()
    start, end = _day_bounds(d)
    rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.timestamp >= start, models.AuditLog.timestamp < end)
        .order_by(models.AuditLog.seq.asc())
        .all()
    )
    if not rows:
        return None
    # Refuse to archive unverifiable days: rows must be seq-contiguous and
    # re-hash to their stored row_hash (a day straddling midnight can have a
    # seq gap -- retry once the neighbouring day is complete, WORM is write-once).
    prev = rows[0].prev_hash
    for i, r in enumerate(rows):
        if (i and r.seq != rows[i - 1].seq + 1) or compute_row_hash(r, prev) != r.row_hash:
            raise RuntimeError(f"audit day {d} is not a clean chain segment at seq {r.seq}; not archived")
        prev = r.row_hash
    obj_key, man_key = _keys(d)
    lines = [
        json.dumps({**{c: getattr(r, c) for c in _COLS}, "ts": canonical_ts(r.timestamp)},
                   sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        for r in rows
    ]
    blob = gzip.compress(("\n".join(lines) + "\n").encode("utf-8"), mtime=0)
    manifest = {
        "date": d.isoformat(), "from_seq": rows[0].seq, "to_seq": rows[-1].seq,
        "row_count": len(rows), "first_prev_hash": rows[0].prev_hash,
        "last_row_hash": rows[-1].row_hash, "object_key": obj_key,
        "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob),
    }
    if store.exists(storage.BUCKET_REPORTS, man_key):
        old = json.loads(store.get(storage.BUCKET_REPORTS, man_key))
        if old.get("last_row_hash") != manifest["last_row_hash"] or old.get("row_count") != manifest["row_count"]:
            raise RuntimeError(f"audit archive for {d} exists but live rows differ -- audit_logs tampered")
        return old
    store.put(storage.BUCKET_REPORTS, obj_key, blob, mime="application/gzip")
    store.get_checked(storage.BUCKET_REPORTS, obj_key, manifest["sha256"])  # read-back
    store.put(storage.BUCKET_REPORTS, man_key, json.dumps(manifest, sort_keys=True).encode(),
              mime="application/json")
    return manifest


def verify_archived_day(d: date, store=None) -> "tuple[bool, str]":
    """Re-verify one archived day from object storage alone."""
    store = store or storage.get_object_store()
    obj_key, man_key = _keys(d)
    try:
        man = json.loads(store.get(storage.BUCKET_REPORTS, man_key))
        blob = store.get_checked(storage.BUCKET_REPORTS, obj_key, man["sha256"])
    except Exception as exc:  # missing object / checksum mismatch
        return False, f"cannot read archive: {exc}"
    prev, expected, n = man["first_prev_hash"], man["from_seq"], 0
    for line in gzip.decompress(blob).decode("utf-8").splitlines():
        r = json.loads(line)
        row = SimpleNamespace(**{c: r[c] for c in _COLS}, timestamp=r["ts"])
        if row.seq != expected or row.prev_hash != prev or compute_row_hash(row, prev) != row.row_hash:
            return False, f"chain broken at seq {row.seq}"
        prev, expected, n = row.row_hash, expected + 1, n + 1
    if n != man["row_count"] or prev != man["last_row_hash"]:
        return False, "row count / tip does not match manifest"
    return True, "ok"
