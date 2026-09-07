"""Small shared directory lookups.

Extracted (code-review follow-up 2026-09-07) from four byte-identical
"resolve a set of user ids to display names in one query" loops that had
been copy-pasted across admin.py and pharmacy.py list endpoints.
"""
from typing import Iterable

from sqlalchemy.orm import Session

from . import models


def resolve_user_names(db: Session, user_ids: Iterable[str]) -> dict[str, str]:
    """`{user_id: full_name}` for the given ids, in a single query. Ids with
    no matching user are simply absent from the result -- callers use
    `.get(id)` and treat a miss as "unknown", same as the loops this
    replaced."""
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    return {
        uid: full_name
        for uid, full_name in (
            db.query(models.User.id, models.User.full_name)
            .filter(models.User.id.in_(ids))
            .all()
        )
    }
