"""Demo plugin. DELETE THIS FOLDER (and web/src/demo/) for production.

Everything that exists only for the public demo lives here; the core app
imports it optionally (see mfa.py), so with the folder gone there is no
demo code path left to misconfigure. As a second lock it also refuses to
act unless APP_ENV=demo, in case the folder is shipped by mistake.
"""
import os

# Shared public logins that skip 2FA. Keep in sync with web/src/demo/index.jsx.
MFA_EXEMPT = frozenset(f"{r}@clarion.demo" for r in
                       ("patient", "receptionist", "pharmacist", "clinician", "admin"))


def skips_mfa(user) -> bool:
    if os.environ.get("APP_ENV", "").strip().lower() != "demo":
        return False
    return (getattr(user, "email", "") or "").lower() in MFA_EXEMPT
