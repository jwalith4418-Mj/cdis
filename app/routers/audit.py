import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import User
from ..observability import counters
from ..schemas import KillSwitchIn
from ..security import get_current_user, require_admin
from ..services import audit as audit_svc
from ..services import twin as twin_svc

router = APIRouter(prefix="/api", tags=["audit", "health"])


def _probe(fn) -> dict:
    start = time.perf_counter()
    try:
        fn()
        return {"status": "healthy", "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001 — health must never raise
        return {"status": "unavailable", "error": type(exc).__name__}


@router.get("/audit")
def list_audit(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return audit_svc.list_decisions(db, user.id)


@router.get("/audit/{decision_id}")
def get_audit(decision_id: int, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    d = audit_svc.get_decision(db, user.id, decision_id)
    return {"id": d.id, "kind": d.kind, "twin_hash": d.twin_hash, "inputs": d.inputs,
            "evidence": d.evidence, "output": d.output, "confidence": d.confidence,
            "engine_version": d.engine_version, "fallback_used": d.fallback_used,
            "latency_ms": d.latency_ms, "created_at": d.created_at.isoformat()}


@router.post("/audit/{decision_id}/replay")
def replay(decision_id: int, user: User = Depends(get_current_user),
           db: Session = Depends(get_db)):
    twin = twin_svc.project(db, user.id)
    return audit_svc.replay(db, user.id, decision_id, twin["twin_hash"])


@router.get("/livez")
def livez():
    """Liveness: the process is up. Deliberately does NOT touch the DB — a transient
    DB blip must not make the container healthcheck fail and trigger a kill/restart
    loop. Readiness (DB reachability) is /api/health, used by the load balancer."""
    return {"status": "alive", "version": settings.version}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    probe = _probe(lambda: db.execute(text("SELECT 1")))
    status = "healthy" if probe["status"] == "healthy" else "unavailable"
    return {"status": status, "version": settings.version, "database": probe}


@router.get("/health/mission")
def mission_health(db: Session = Depends(get_db)):
    from ..services.evidence import score_skill
    from ..services.parser import match_skills

    database = _probe(lambda: db.execute(text("SELECT 1")))
    parser_chain = _probe(lambda: match_skills("python"))
    rule_engine = _probe(lambda: score_skill([{"type": "github_repo"}]))
    llm = ("simulated_down (rule-engine fallback active)" if settings.simulate_llm_down
           else ("configured" if settings.anthropic_api_key
                 else "not_configured (rule-engine primary)"))
    components = {"database": database, "parser_chain": parser_chain,
                  "rule_engine": rule_engine, "llm_adapter": llm}
    unhealthy = [k for k, v in components.items()
                 if isinstance(v, dict) and v["status"] != "healthy"]
    return {
        "mission_status": "degraded" if unhealthy else "healthy",
        "components": components,
        "fallback_counters": counters.snapshot(),
        "doctrine": "Quality may degrade; the mission does not.",
    }


@router.post("/admin/llm-kill-switch")
def kill_switch(body: KillSwitchIn, user: User = Depends(require_admin)):
    """Demo control (Blueprint §12 step 8): flip the LLM off live and show graceful degradation.

    Admin-only. Note: this mutates process-local state; in a multi-instance
    deployment back it with shared state (Redis) so all workers agree.
    """
    settings.simulate_llm_down = body.llm_down
    counters.bump("kill_switch_toggled")
    return {"simulate_llm_down": settings.simulate_llm_down}
