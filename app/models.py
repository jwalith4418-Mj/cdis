"""ORM models.

Design (Blueprint §3): the Career Twin is an append-only event log; the current
state is a projection. Nothing is overwritten — rollback, timeline, and decision
replay come from the same mechanism.
"""
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TwinEvent(Base):
    """Append-only. Never updated except the `status` workflow field on facts,
    which is itself only mutated through confirm/reject events for auditability."""

    __tablename__ = "twin_events"
    # Composite index: projection reads the log per user ordered by id.
    __table_args__ = (Index("ix_twin_events_user_id_id", "user_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # fact.added | fact.confirmed | fact.rejected | evidence.added
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Decision(Base):
    """Decision Audit record (Blueprint §7.2). Stores everything needed for
    deterministic replay: inputs, twin snapshot, evidence, engine version."""

    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # gap_analysis
    twin_hash: Mapped[str] = mapped_column(String(64))
    inputs: Mapped[dict] = mapped_column(JSON)          # e.g. {"jd_text": ...}
    twin_snapshot: Mapped[dict] = mapped_column(JSON)   # accepted facts used
    evidence: Mapped[list] = mapped_column(JSON)        # citations backing the output
    output: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[str] = mapped_column(String(10))  # High | Medium | Low
    engine_version: Mapped[str] = mapped_column(String(60))
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResumeVersion(Base):
    """Immutable, git-like. New versions only via explicit human approval."""

    __tablename__ = "resume_versions"
    # A user's version numbers are dense and unique — enforced, not assumed.
    __table_args__ = (UniqueConstraint("user_id", "version", name="uq_user_version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_label: Mapped[str] = mapped_column(String(200), default="master")
    content: Mapped[str] = mapped_column(Text)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Application(Base):
    """Consented outcome funnel (applied -> interview -> offer/rejected), linked to
    the decision that preceded it -> the evidence->outcome corpus + North Star."""

    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    target_role: Mapped[str] = mapped_column(String(200))
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="applied")
    consented: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
