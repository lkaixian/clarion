"""Reset (or create the way back into) an account's password from the host.

For when nobody can sign in -- e.g. every seeded account was rotated -- or an
admin forgot theirs. Runs INSIDE the backend container against its real DB:

    docker compose -f docker-compose.pi.yml exec backend \\
        python /app/db/reset_admin_password.py admin@clarion.demo

Prints a random password ONCE to your terminal. Do not run it somewhere the
output is logged or shared. The account is forced to change it at next
sign-in, every existing session/refresh token is revoked, and the reset is
written to the audit log.

    --password-from-env VAR   use $VAR instead of generating one (still
                              forced to change at next sign-in)
"""
import argparse
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import auth, models  # noqa: E402
from app.audit import log_access  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.schemas import MIN_PASSWORD_LENGTH  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("--password-from-env", metavar="VAR")
    args = ap.parse_args()

    if args.password_from_env:
        password = os.environ.get(args.password_from_env, "")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"error: ${args.password_from_env} must be at least {MIN_PASSWORD_LENGTH} characters", file=sys.stderr)
            return 2
        generated = False
    else:
        password = secrets.token_urlsafe(18)  # 24 chars
        generated = True

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == args.email).first()
        if user is None:
            print(f"error: no account with email {args.email!r}", file=sys.stderr)
            return 1
        role, user_id, facility = user.role, user.id, user.facility  # read before commit expires the row
        now = datetime.now(timezone.utc)
        user.hashed_password = auth.hash_password(password)
        user.must_change_password = True
        user.password_changed_at = now
        user.login_locked_until = None
        for tok in db.query(models.RefreshToken).filter_by(user_id=user.id, revoked_at=None).all():
            tok.revoked_at = now
        db.commit()
        log_access(db, None, "system", "system", "admin_password_reset_cli",
                   detail=f"user={user_id} role={role}", actor_facility=facility)
    finally:
        db.close()

    print(f"Password reset for {args.email} (role {role}). Must be changed at next sign-in.")
    if generated:
        print(f"Temporary password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
