import hashlib
import hmac
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
from .database import get_db

# NOTE FOR TEAM: this secret is fine for a symposium demo. Before any real
# deployment, move it to an environment variable and rotate it.
SECRET_KEY = "medibridge-dev-secret-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8

# POST /auth/login lockout policy (same "reasonable human typo tolerance vs.
# brute-force resistance" tradeoff as the email-OTP reset limits below)
# — 5 wrong passwords in a row is well past plausible fat-fingering
# (esp. for a temp password patients type once) but still cheap for a
# legitimate user to recover from after a 20 minute cooldown.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 20

# Email-OTP password reset (POST /auth/request-password-reset-otp,
# POST /auth/reset-password-with-otp) policy. Two independent limits, same
# "persist on the row, survive restarts" discipline as the lockout columns
# above:
#   - OTP_MAX_VERIFY_ATTEMPTS: wrong-code guesses against one live OTP.
#     Exceeding it invalidates that OTP outright (must request a fresh one)
#     rather than extending a cooldown indefinitely.
#   - OTP_MAX_REQUESTS_PER_WINDOW / OTP_REQUEST_WINDOW_MINUTES: how many
#     *new* OTPs can be requested for one NRIC in a rolling window, so an
#     attacker can't email-bomb a patient's inbox by repeatedly hitting
#     request-password-reset-otp.
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_VERIFY_ATTEMPTS = 5
OTP_MAX_REQUESTS_PER_WINDOW = 3
OTP_REQUEST_WINDOW_MINUTES = 15

# HMAC key for hashing OTP codes at rest -- deliberately NOT bcrypt
# (pwd_context.hash below): bcrypt is tuned to be slow, which is the right
# tradeoff for a long-lived login password but wasted cost for a 6-digit,
# 10-minute-lived, rate-limited code. A keyed HMAC-SHA256 is fast, fixed
# time-cost, and just as unrecoverable without this key. Same
# demo-appropriate secret-management caveat as SECRET_KEY above.
_OTP_HMAC_KEY = b"medibridge-dev-otp-hmac-key-change-me"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Ambiguous-looking characters excluded so a human can reliably read/type a
# temp password off a screen or printed slip: 0/O, 1/l/I.
_TEMP_PASSWORD_ALPHABET = "".join(
    c for c in string.ascii_letters + string.digits if c not in "0O1lI"
)


def generate_temp_password(length: int = 14) -> str:
    """Cryptographically random temporary password (secrets module, not
    random/uuid4). Used both when staff issue a brand-new patient login and
    when staff regenerate/reset an existing one."""
    return "".join(secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length))


def generate_otp_code(length: int = OTP_LENGTH) -> str:
    """Cryptographically random numeric OTP (secrets module, not random).
    Zero-padded so e.g. "004821" is a valid 6-digit code, not "4821"."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def hash_otp_code(code: str) -> str:
    """Keyed HMAC-SHA256 hex digest -- see _OTP_HMAC_KEY comment above for
    why this isn't bcrypt. Only ever the hash is persisted (User.otp_code_hash);
    the plaintext code exists only transiently in memory to email it out."""
    return hmac.new(_OTP_HMAC_KEY, code.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp_code(code), code_hash)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def _resolve_current_user(token: str, db: Session) -> models.User:
    """Shared identity resolution for both get_current_user variants below:
    decode the JWT, look up the user, 401 if either fails. Does NOT check
    must_change_password -- that's layered on top by get_current_user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_user_allow_pending_change(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> models.User:
    """Same as get_current_user, but does NOT block a user whose
    must_change_password flag is still set. Reserved for the small,
    explicit set of endpoints that must stay reachable so such a user can
    actually clear that flag: GET /auth/me and POST /auth/change-password.
    (There is no server-side logout endpoint -- JWTs are stateless here --
    so there's nothing else to exempt.) Every other authenticated route
    should keep using get_current_user / require_roles below."""
    return _resolve_current_user(token, db)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    """Standard auth dependency used by (almost) every protected endpoint,
    directly or via require_roles(). Enforces must_change_password
    server-side: a staff-issued temp password or a fresh self-service reset
    is only ever good for GET /auth/me and POST /auth/change-password until
    the user actually changes it -- previously this flag was purely
    advisory/client-side (mobile happened to gate on it, the web console
    didn't even try), so a captured or shoulder-surfed temp password token
    was fully usable against every other endpoint indefinitely."""
    user = _resolve_current_user(token, db)
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "Password change required",
                "must_change_password": True,
            },
        )
    return user


def require_roles(*roles: str):
    """Dependency factory: require_roles('clinician', 'admin')"""
    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires one of roles: {roles}")
        return user
    return checker
