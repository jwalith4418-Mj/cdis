"""Resume Engine (Blueprint §2 service 5, §6).

Drafts are generated only from accepted Twin facts (nothing unverified ever
appears in a resume), adapted to the pasted job description by evidence-weighted
ordering. The AI never mutates a resume: a draft + diff is returned, and a new
immutable version exists only after explicit human approval.
"""
import difflib

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import ResumeVersion
from .evidence import score_skill
from .parser import extract_jd_requirements


def generate_draft(twin: dict, user_name: str, user_email: str,
                   jd_text: str, target_label: str) -> str:
    requirements = extract_jd_requirements(jd_text) if jd_text else {}
    skills = twin["accepted"].get("skill", [])
    scored = [(f["value"], score_skill(f.get("evidence", []))) for f in skills]
    scored.sort(key=lambda kv: (-(requirements.get(kv[0], 0)), -kv[1]["score"], kv[0]))

    lines = [f"# {user_name}", f"{user_email}", ""]
    if target_label and target_label != "master":
        lines += [f"**Target:** {target_label}", ""]
    if scored:
        lines += ["## Skills", ""]
        for name, s in scored:
            marker = " ★" if requirements.get(name) else ""
            lines.append(f"- {name} — evidence {s['score']}/100 ({s['band']}){marker}")
        lines.append("")
    for section, title in (("project", "Projects"), ("experience", "Experience"),
                           ("education", "Education"), ("certification", "Certifications")):
        items = twin["accepted"].get(section, [])
        if items:
            lines += [f"## {title}", ""]
            lines += [f"- {f['value']}" for f in items]
            lines.append("")
    if requirements:
        lines += ["---", "_★ emphasized for this job description. Every line above is a "
                  "verified Twin fact — nothing here was generated or assumed._"]
    return "\n".join(lines).strip() + "\n"


def diff_against(previous: str | None, draft: str) -> str:
    if previous is None:
        previous = ""
    return "\n".join(difflib.unified_diff(
        previous.splitlines(), draft.splitlines(),
        fromfile="current-version", tofile="draft", lineterm="",
    ))


def latest_version(db: Session, user_id: int) -> ResumeVersion | None:
    return db.execute(
        select(ResumeVersion).where(ResumeVersion.user_id == user_id)
        .order_by(ResumeVersion.version.desc()).limit(1)
    ).scalar_one_or_none()


def approve(db: Session, user_id: int, content: str, target_label: str,
            decision_id: int | None) -> ResumeVersion:
    """Create the next immutable version. The (user_id, version) uniqueness
    constraint makes concurrent approvals safe: a loser retries against the new
    latest rather than silently duplicating a version number."""
    for _ in range(5):
        latest = latest_version(db, user_id)
        version = ResumeVersion(
            user_id=user_id,
            version=(latest.version + 1) if latest else 1,
            parent_version=latest.version if latest else None,
            target_label=target_label or "master",
            content=content,
            decision_id=decision_id,
        )
        db.add(version)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(version)
        return version
    raise HTTPException(status_code=409,
                        detail="Could not allocate a resume version — retry.")
