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
    --reset-mfa               ALSO clear the account's authenticator and
                              recovery codes (lost phone + codes). The next
                              sign-in enrols a new authenticator.
    --mfa-only                clear the authenticator only; leave the password
                              as it is (the user still knows it)
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
from app.schemas import password_rule_failures  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("--password-from-env", metavar="VAR")
    ap.add_argument("--reset-mfa", action="store_true")
    ap.add_argument("--mfa-only", action="store_true")
    args = ap.parse_args()
    mfa_only = args.mfa_only
    clear_mfa = args.reset_mfa or mfa_only
    if mfa_only and (args.reset_mfa or args.password_from_env):
        print("error: --mfa-only leaves the password alone; don't combine it with "
              "--reset-mfa or --password-from-env", file=sys.stderr)
        return 2

    if mfa_only:
        password, generated = "", False
    elif args.password_from_env:
        password = os.environ.get(args.password_from_env, "")
        problems = password_rule_failures(password)
        if problems:
            print(f"error: ${args.password_from_env} needs: " + ", ".join(problems), file=sys.stderr)
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
        if not mfa_only:
            user.hashed_password = auth.hash_password(password)
            user.must_change_password = True
            user.password_changed_at = now
        user.login_locked_until = None
        user.login_failed_count = 0
        user.reset_attempt_count = 0
        if clear_mfa:
            user.mfa_secret_enc = None
            user.mfa_enabled_at = None
            user.mfa_last_step = None
            db.query(models.MfaRecoveryCode).filter_by(user_id=user.id).delete()
        for tok in db.query(models.RefreshToken).filter_by(user_id=user.id, revoked_at=None).all():
            tok.revoked_at = now
        db.commit()
        action = "admin_mfa_reset_cli" if mfa_only else "admin_password_reset_cli"
        log_access(db, None, "system", "system", action,
                   detail=f"user={user_id} role={role} mfa_cleared={clear_mfa}", actor_facility=facility)
    finally:
        db.close()

    if mfa_only:
        print(f"Authenticator and recovery codes cleared for {args.email} (role {role}). "
              "Password unchanged; a new authenticator is enrolled at next sign-in.")
        return 0
    print(f"Password reset for {args.email} (role {role}). Must be changed at next sign-in."
          + (" Authenticator cleared too." if clear_mfa else ""))
    if generated:
        print(f"Temporary password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
