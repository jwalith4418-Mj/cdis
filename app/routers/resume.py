from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ResumeVersion, User
from ..schemas import ResumeApproveIn, ResumeDraftIn
from ..security import get_current_user
from ..services import resume as resume_svc
from ..services import twin as twin_svc

router = APIRouter(prefix="/api/resume", tags=["resume"])


@router.post("/draft")
def draft(body: ResumeDraftIn, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    content = resume_svc.generate_draft(twin, user.name, user.email,
                                        body.jd_text, body.target_label)
    latest = resume_svc.latest_version(db, user.id)
    return {
        "draft": content,
        "diff": resume_svc.diff_against(latest.content if latest else None, content),
        "base_version": latest.version if latest else None,
        "note": ("This is a draft built only from your accepted, verified facts. "
                 "Nothing is saved until you approve it."),
    }


@router.post("/approve", status_code=201)
def approve(body: ResumeApproveIn, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    version = resume_svc.approve(db, user.id, body.content, body.target_label, body.decision_id)
    return {"version": version.version, "parent_version": version.parent_version,
            "target_label": version.target_label, "created_at": version.created_at.isoformat()}


@router.get("/versions")
def versions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(ResumeVersion).where(ResumeVersion.user_id == user.id)
        .order_by(ResumeVersion.version.desc())
    ).scalars().all()
    return [{"version": v.version, "parent_version": v.parent_version,
             "target_label": v.target_label, "created_at": v.created_at.isoformat(),
             "content": v.content} for v in rows]
