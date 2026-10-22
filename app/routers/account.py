"""Account privacy controls: data portability (export) and erasure (hard delete).

Backs the product's stated invariant — "Twin data is user-owned: full export and
hard delete." Both act only on the caller's own rows; deletion requires a
password re-confirmation so a leaked token alone can't wipe an account.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Decision, ResumeVersion, TwinEvent, User
from ..observability import counters, logger
from ..schemas import DeleteAccountIn
from ..security import get_current_user, verify_password

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/export")
def export_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Everything CDIS holds about the caller, as portable JSON."""
    events = db.execute(
        select(TwinEvent).where(TwinEvent.user_id == user.id).order_by(TwinEvent.id)
    ).scalars().all()
    decisions = db.execute(
        select(Decision).where(Decision.user_id == user.id).order_by(Decision.id)
    ).scalars().all()
    versions = db.execute(
        select(ResumeVersion).where(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.version)
    ).scalars().all()
    return {
        "profile": {"email": user.email, "name": user.name,
                    "created_at": user.created_at.isoformat()},
        "twin_events": [{"id": e.id, "event_type": e.event_type, "payload": e.payload,
                         "created_at": e.created_at.isoformat()} for e in events],
        "decisions": [{"id": d.id, "kind": d.kind, "inputs": d.inputs, "output": d.output,
                       "evidence": d.evidence, "engine_version": d.engine_version,
                       "created_at": d.created_at.isoformat()} for d in decisions],
        "resume_versions": [{"version": v.version, "parent_version": v.parent_version,
                             "target_label": v.target_label, "content": v.content,
                             "created_at": v.created_at.isoformat()} for v in versions],
    }


@router.post("/delete")
def delete_account(body: DeleteAccountIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Irreversible hard delete of the account and all its data. Password-confirmed."""
    if not verify_password(body.password, user.password_hash):
        counters.bump("account_delete_denied")
        raise HTTPException(status_code=403, detail="Password is incorrect.")
    uid = user.id
    # Delete children then the user, in one transaction — no orphaned rows.
    db.execute(delete(TwinEvent).where(TwinEvent.user_id == uid))
    db.execute(delete(Decision).where(Decision.user_id == uid))
    db.execute(delete(ResumeVersion).where(ResumeVersion.user_id == uid))
    db.execute(delete(User).where(User.id == uid))
    db.commit()
    counters.bump("account_deleted")
    logger.info("account deleted user_id=%s", uid)
    return {"deleted": True}
