from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import GapAnalysisIn
from ..security import get_current_user
from ..services import twin as twin_svc
from ..services.decision import run_gap_analysis

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


@router.post("/gap-analysis")
def gap_analysis(body: GapAnalysisIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    if not twin["accepted"].get("skill"):
        raise HTTPException(
            status_code=422,
            detail=("Your Twin has no accepted skills yet. Ingest a resume or add facts, "
                    "and confirm any pending ones, then run the analysis."),
        )
    return run_gap_analysis(db, user.id, twin, body.jd_text, body.target_label)
