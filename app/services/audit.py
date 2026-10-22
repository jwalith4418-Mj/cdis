"""Decision Audit + Replay (Blueprint §7.2).

Every decision stored with its inputs, twin snapshot, evidence, engine version,
confidence, fallback flag, and latency. Replay recomputes the decision from the
stored snapshot with the deterministic rule engine and reports whether the
result reproduces byte-for-byte, plus whether the live Twin has since changed.
"""
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Decision
from .decision import compute_alignment, coverage_from_skills, rule_engine_text
from .parser import extract_jd_requirements


def list_decisions(db: Session, user_id: int) -> list[dict]:
    rows = db.execute(
        select(Decision).where(Decision.user_id == user_id).order_by(Decision.id.desc())
    ).scalars().all()
    return [{
        "id": d.id, "kind": d.kind, "confidence": d.confidence,
        "engine_version": d.engine_version, "fallback_used": d.fallback_used,
        "latency_ms": d.latency_ms, "created_at": d.created_at.isoformat(),
        "target": d.output.get("target"),
        "alignment_score": d.output.get("alignment_score"),
    } for d in rows]


def get_decision(db: Session, user_id: int, decision_id: int) -> Decision:
    d = db.get(Decision, decision_id)
    if d is None or d.user_id != user_id:
        raise HTTPException(status_code=404, detail="Decision not found.")
    return d


def _recompute_alignment(snapshot: dict, jd_text: str) -> dict:
    """Reuses the exact scoring core from the Decision Engine — so a reproducible
    replay is guaranteed by construction, not by a parallel implementation."""
    requirements = extract_jd_requirements(jd_text)
    coverage = coverage_from_skills(snapshot.get("skills", []))
    core = compute_alignment(requirements, coverage)
    factors = [{"skill": f["skill"], "estimated_gain": f["estimated_gain"]}
               for f in core["limiting_factors"][:5]]
    return {"alignment_score": core["alignment_score"], "limiting_factors": factors}


def replay(db: Session, user_id: int, decision_id: int, current_twin_hash: str) -> dict:
    d = get_decision(db, user_id, decision_id)
    if d.kind != "gap_analysis":
        raise HTTPException(status_code=400, detail="Only gap-analysis decisions replay.")
    recomputed = _recompute_alignment(d.twin_snapshot, d.inputs["jd_text"])
    original_factors = [{"skill": f["skill"], "estimated_gain": f["estimated_gain"]}
                        for f in d.output.get("limiting_factors", [])]
    reproducible = (
        recomputed["alignment_score"] == d.output.get("alignment_score")
        and recomputed["limiting_factors"] == original_factors
    )
    return {
        "decision_id": d.id,
        "reproducible": reproducible,
        "twin_changed_since": current_twin_hash != d.twin_hash,
        "reasoning_path": {
            "inputs": {"target": d.inputs.get("target_label"),
                       "jd_excerpt": re.sub(r"\s+", " ", d.inputs["jd_text"])[:280]},
            "twin_hash_at_decision": d.twin_hash,
            "evidence_used": d.evidence,
            "engine_version": d.engine_version,
            "fallback_used": d.fallback_used,
            "rule": rule_engine_text(
                d.output.get("alignment_score", 0),
                d.output.get("limiting_factors", []),
                d.output.get("target", ""),
            ),
        },
        "original_output": d.output,
        "recomputed": recomputed,
    }
