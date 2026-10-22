from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..schemas import EvidenceIn, GithubIn, ManualFactIn, ResumeTextIn
from ..security import get_current_user
from ..services import evidence as evidence_svc
from ..services import github as gh_svc
from ..services import twin as twin_svc
from ..services.parser import ExtractedFact, parse_resume

router = APIRouter(prefix="/api/twin", tags=["twin"])


def _ingest(db: Session, user: User, text: str) -> dict:
    result = parse_resume(text)
    events = twin_svc.add_facts(db, user.id, result.facts)  # atomic: one transaction
    added = [
        {"fact_id": event.id, "entity": fact.entity, "value": fact.value,
         "confidence": fact.confidence,
         "status": twin_svc.status_for_confidence(fact.confidence),
         "detail": fact.detail}
        for event, fact in zip(events, result.facts, strict=True)
    ]
    return {"stages_used": result.stages_used, "warnings": result.warnings,
            "facts": added,
            "hitl_policy": {"accepted": "confidence ≥ 0.80",
                            "pending": "0.60–0.79 — confirm to use",
                            "manual_review": "< 0.60 — verify to use"}}


@router.post("/resume")
def ingest_resume_text(body: ResumeTextIn, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    return _ingest(db, user, body.text)


@router.post("/resume/file")
async def ingest_resume_file(file: UploadFile = File(...),
                             user: User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(f"File too large (max {settings.max_upload_bytes // (1024 * 1024)} MB). "
                    "Paste your resume text instead — the mission continues."),
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="ignore")
    if not any(ch.isalnum() for ch in text):
        raise HTTPException(
            status_code=422,
            detail=("This file has no readable text (a scanned or binary file). "
                    "Paste your resume text instead, or add facts manually — "
                    "the mission continues."),
        )
    return _ingest(db, user, text)


@router.get("")
def get_twin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    return {"name": user.name, "email": user.email, **twin}


@router.post("/facts", status_code=201)
def add_manual_fact(body: ManualFactIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    fact = ExtractedFact(entity=body.entity, value=body.value, confidence=1.0,
                         source_stage="manual", detail="Entered by you.")
    event = twin_svc.add_fact(db, user.id, fact)
    return {"fact_id": event.id, "status": "accepted"}


@router.post("/facts/{fact_id}/confirm")
def confirm_fact(fact_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    twin_svc.resolve_fact(db, user.id, fact_id, "confirmed")
    return {"fact_id": fact_id, "status": "accepted"}


@router.post("/facts/{fact_id}/reject")
def reject_fact(fact_id: int, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    twin_svc.resolve_fact(db, user.id, fact_id, "rejected")
    return {"fact_id": fact_id, "status": "rejected"}


@router.post("/evidence", status_code=201)
def attach_evidence(body: EvidenceIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    known = {f["value"] for f in twin["accepted"].get("skill", [])}
    if body.skill not in known:
        raise HTTPException(status_code=404,
                            detail=f"'{body.skill}' is not an accepted skill in your Twin yet.")
    twin_svc.add_evidence(db, user.id, body.skill, body.type, body.reference)
    return {"skill": body.skill, "type": body.type}


@router.post("/evidence/github", status_code=201)
def import_github(body: GithubIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """Build the scorecard from verified GitHub work: fetch public repos, map them
    to skills, add any new skills as accepted facts, and attach repo evidence."""
    try:
        repos = gh_svc.fetch_repos(body.username)
    except Exception:
        raise HTTPException(status_code=502, detail=(
            "Could not reach GitHub. Try again, or attach evidence manually — "
            "the mission continues.")) from None
    items = gh_svc.repos_to_evidence(repos)
    known = {f["value"] for f in twin_svc.project(db, user.id)["accepted"].get("skill", [])}
    skills_added = 0
    for it in items:
        if it["skill"] not in known:
            twin_svc.add_fact(db, user.id, ExtractedFact(
                entity="skill", value=it["skill"], confidence=1.0,
                source_stage="github", detail="Verified from your GitHub."))
            known.add(it["skill"])
            skills_added += 1
        twin_svc.add_evidence(db, user.id, it["skill"], it["type"], it["reference"])
    return {"repos": len(repos), "skills_added": skills_added,
            "evidence_attached": len(items)}


@router.get("/scorecard")
def get_scorecard(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    return evidence_svc.scorecard(twin)
