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

# Self-service password-reset (POST /auth/forgot-password) lockout policy.
RESET_MAX_ATTEMPTS = 5
RESET_LOCKOUT_MINUTES = 20

# POST /auth/login lockout policy. Mirrors the forgot-password thresholds
# above (same "reasonable human typo tolerance vs. brute-force resistance"
# tradeoff) — 5 wrong passwords in a row is well past plausible fat-fingering
# (esp. for a temp password patients type once) but still cheap for a
# legitimate user to recover from after a 20 minute cooldown.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 20

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
