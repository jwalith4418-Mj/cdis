import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..observability import counters, logger
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, dummy_verify, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _email_tag(email: str) -> str:
    # Correlatable in logs for abuse detection, but not the raw address (no PII in logs).
    return hashlib.sha256(email.lower().encode()).hexdigest()[:12]


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    exists = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = User(email=body.email, name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"token": create_token(user.id), "name": user.name, "email": user.email}


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    # Always spend one PBKDF2 verification so response time can't reveal whether
    # the email exists. Identical error for both cases — no enumeration.
    if user is None:
        dummy_verify(body.password)
        ok = False
    else:
        ok = verify_password(body.password, user.password_hash)
    if not ok:
        counters.bump("auth_failed")
        logger.warning("auth failed email_tag=%s", _email_tag(body.email))
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return {"token": create_token(user.id), "name": user.name, "email": user.email}
