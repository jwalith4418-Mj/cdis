"""Security primitives: PBKDF2-HMAC password hashing (stdlib, no native builds)
and HS256 JWTs. Passwords are never logged or returned."""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User

_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt}${digest.hex()}"


# A real hash to verify against when an email is unknown, so login spends the
# same PBKDF2 time whether or not the account exists — no timing side channel
# that would let an attacker enumerate registered emails. Built lazily so import
# doesn't pay a PBKDF2 on every cold start.
_DUMMY_HASH: str | None = None


def dummy_verify(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_hex(16))
    verify_password(password, _DUMMY_HASH)


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                        bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(hours=settings.jwt_ttl_hours),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    try:
        payload = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status_code=401, detail="Session expired. Sign in again.") from None
    if user is None:
        raise HTTPException(status_code=401, detail="Account not found.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Authorization gate for privileged endpoints (e.g. the demo kill switch)."""
    if not user.is_admin:
        from .observability import counters, logger
        counters.bump("authz_denied")
        logger.warning("authz denied: non-admin user_id=%s hit an admin endpoint", user.id)
        raise HTTPException(status_code=403, detail="Admin privileges required.")
    return user
