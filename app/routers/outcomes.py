"""Consented outcome tracking: the application funnel that makes the North Star
measurable and seeds the evidence->outcome corpus. User-owned and consented."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Application, User
from ..schemas import ApplicationIn, ApplicationStatusIn
from ..security import get_current_user

router = APIRouter(prefix="/api/outcomes", tags=["outcomes"])


def _row(a: Application) -> dict:
    return {"id": a.id, "target_role": a.target_role, "decision_id": a.decision_id,
            "status": a.status, "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat()}


@router.post("", status_code=201)
def create(body: ApplicationIn, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    a = Application(user_id=user.id, target_role=body.target_role,
                    decision_id=body.decision_id, status=body.status)
    db.add(a)
    db.commit()
    db.refresh(a)
    return _row(a)


@router.patch("/{app_id}")
def update(app_id: int, body: ApplicationStatusIn, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    a = db.get(Application, app_id)
    if a is None or a.user_id != user.id:
        raise HTTPException(status_code=404, detail="Application not found.")
    a.status = body.status
    db.commit()
    db.refresh(a)
    return _row(a)


@router.get("")
def list_outcomes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Application).where(Application.user_id == user.id)
                      .order_by(Application.id.desc())).scalars().all()
    advanced = sum(1 for a in rows if a.status in ("interview", "offer"))
    return {"applications": [_row(a) for a in rows],
            "north_star": {"total": len(rows), "advanced_beyond_applied": advanced}}
