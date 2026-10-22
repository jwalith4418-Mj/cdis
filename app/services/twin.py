"""Career Twin service (Blueprint §3).

Append-only events → projected current state. Facts carry an HITL status:
  accepted            confidence ≥ 0.8 or explicitly confirmed by the user
  pending             confidence 0.6–0.8 — excluded from reasoning until confirmed
  manual_review       confidence < 0.6 — excluded until manually verified
  rejected            excluded permanently (event retained; nothing is deleted)

Only `accepted` facts feed the Evidence Scorecard, Decision Engine, and Resume
Engine. The twin hash covers accepted facts only, so all caches and decision
records key on exactly the knowledge that was used.

Performance (§8): the projection is cached per user, keyed on the id of the
latest event. Any new event changes the key, so the cache invalidates itself —
no unchanged Twin is ever re-folded.
"""
import hashlib
import json
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import TwinEvent
from .parser import ExtractedFact, match_skills

_CACHE_MAX_USERS = 10_000
_projection_cache: dict[int, tuple[int, dict]] = {}
_cache_lock = Lock()


def status_for_confidence(confidence: float) -> str:
    if confidence >= 0.8:
        return "accepted"
    if confidence >= 0.6:
        return "pending"
    return "manual_review"


def _fact_payload(fact: ExtractedFact) -> dict:
    return {
        "entity": fact.entity,
        "value": fact.value,
        "confidence": round(fact.confidence, 2),
        "status": status_for_confidence(fact.confidence),
        "source_stage": fact.source_stage,
        "detail": fact.detail,
        "evidence": [],
    }


def append_event(db: Session, user_id: int, event_type: str, payload: dict) -> TwinEvent:
    event = TwinEvent(user_id=user_id, event_type=event_type, payload=payload)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def add_fact(db: Session, user_id: int, fact: ExtractedFact) -> TwinEvent:
    return append_event(db, user_id, "fact.added", _fact_payload(fact))


def add_facts(db: Session, user_id: int, facts: list[ExtractedFact]) -> list[TwinEvent]:
    """Persist all facts from one ingest in a single transaction (atomic, one commit)."""
    events = [TwinEvent(user_id=user_id, event_type="fact.added", payload=_fact_payload(f))
              for f in facts]
    db.add_all(events)
    db.commit()
    for e in events:
        db.refresh(e)
    return events


def add_evidence(db: Session, user_id: int, skill: str, ev_type: str, reference: str) -> TwinEvent:
    return append_event(db, user_id, "evidence.added", {
        "skill": skill, "type": ev_type, "reference": reference,
    })


def resolve_fact(db: Session, user_id: int, fact_id: int, action: str) -> TwinEvent:
    fact = db.get(TwinEvent, fact_id)
    if fact is None or fact.user_id != user_id or fact.event_type != "fact.added":
        raise HTTPException(status_code=404, detail="Fact not found.")

    current = _current_status(db, user_id, fact_id)
    if action == "confirmed":
        if current == "accepted":
            raise HTTPException(status_code=409, detail="Fact is already accepted.")
        if current == "rejected":
            raise HTTPException(status_code=409,
                                detail="Rejected facts cannot be re-confirmed. Add it again.")
    elif action == "rejected":
        if current == "rejected":
            raise HTTPException(status_code=409, detail="Fact is already rejected.")
    return append_event(db, user_id, f"fact.{action}", {"fact_id": fact_id})


def _current_status(db: Session, user_id: int, fact_id: int) -> str:
    twin = project(db, user_id)
    for group in twin["facts"].values():
        for f in group:
            if f["id"] == fact_id:
                return f["status"]
    return "unknown"


def _latest_event_id(db: Session, user_id: int) -> int:
    return db.execute(
        select(func.coalesce(func.max(TwinEvent.id), 0)).where(TwinEvent.user_id == user_id)
    ).scalar_one()


def _fold(events: list[TwinEvent]) -> dict:
    facts: dict[int, dict] = {}
    for ev in events:
        if ev.event_type == "fact.added":
            facts[ev.id] = {"id": ev.id, **ev.payload}
        elif ev.event_type in ("fact.confirmed", "fact.rejected"):
            target = facts.get(ev.payload.get("fact_id"))
            if target:
                target["status"] = "accepted" if ev.event_type == "fact.confirmed" else "rejected"
        elif ev.event_type == "evidence.added":
            for f in facts.values():
                if f["entity"] == "skill" and f["value"] == ev.payload["skill"]:
                    f.setdefault("evidence", []).append(
                        {"type": ev.payload["type"], "reference": ev.payload["reference"]}
                    )

    # Certifications naming a lexicon skill count as certificate evidence for it.
    # Uses whole-token matching so a "Digital Marketing" certificate does NOT
    # attach itself to the skill "Git".
    skills = {f["value"]: f for f in facts.values()
              if f["entity"] == "skill" and f["status"] != "rejected"}
    for f in facts.values():
        if f["entity"] == "certification" and f["status"] == "accepted":
            for name in match_skills(f["value"]):
                sk = skills.get(name)
                if sk is None:
                    continue
                refs = {e["reference"] for e in sk.get("evidence", [])}
                if f["value"] not in refs:
                    sk.setdefault("evidence", []).append(
                        {"type": "certificate", "reference": f["value"]}
                    )

    grouped: dict[str, list[dict]] = {
        "skill": [], "project": [], "experience": [], "education": [],
        "certification": [], "impact_claim": [],
    }
    for f in sorted(facts.values(), key=lambda x: x["id"]):
        grouped.setdefault(f["entity"], []).append(f)

    accepted = {k: [f for f in v if f["status"] == "accepted"] for k, v in grouped.items()}
    pending = [f for v in grouped.values() for f in v
               if f["status"] in ("pending", "manual_review")]
    return {"facts": grouped, "accepted": accepted, "pending": pending,
            "twin_hash": twin_hash(accepted)}


def project(db: Session, user_id: int) -> dict:
    """Fold the event log into the current Twin state, cached on the latest event id."""
    version = _latest_event_id(db, user_id)
    with _cache_lock:
        hit = _projection_cache.get(user_id)
        if hit and hit[0] == version:
            return hit[1]  # read-only by contract; callers never mutate the projection

    events = db.execute(
        select(TwinEvent).where(TwinEvent.user_id == user_id).order_by(TwinEvent.id)
    ).scalars().all()
    projection = _fold(events)

    with _cache_lock:
        if len(_projection_cache) > _CACHE_MAX_USERS:
            _projection_cache.clear()
        _projection_cache[user_id] = (version, projection)
    return projection


def twin_hash(accepted: dict) -> str:
    canonical = json.dumps(
        {k: [{kk: f[kk] for kk in ("entity", "value", "evidence") if kk in f} for f in v]
         for k, v in accepted.items()},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
