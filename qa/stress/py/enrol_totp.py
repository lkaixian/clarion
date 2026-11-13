#!/usr/bin/env python3
"""enrol_totp.py BASE_URL EMAIL PASSWORD - one-time TOTP enrolment of a QA account that the server forces into MFA.
Prints two lines: SECRET=<base32> and RECOVERY=<codes>. Keep them in a root-only file on the Pi (never in the repo).
Run once; running it on an already enrolled account fails (the login then asks for a code instead of enrolment)."""
import sys

import httpx

from conftest import totp_now

base, email, pw = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
with httpx.Client(base_url=base, verify=False, timeout=30) as c:
    b = c.post("/auth/login", data={"username": email, "password": pw}).json()
    if not (b.get("mfa_required") and b.get("mfa_enrol")):
        sys.exit(f"nothing to enrol: login answered {sorted(b)}")
    secret = c.post("/auth/mfa/enrol/start", json={"mfa_token": b["mfa_token"]}).json()["secret"]
    r = c.post("/auth/mfa/enrol/confirm", json={"mfa_token": b["mfa_token"], "code": totp_now(secret)})
    r.raise_for_status()
    print("SECRET=" + secret)
    print("RECOVERY=" + ",".join(r.json().get("recovery_codes", [])))
