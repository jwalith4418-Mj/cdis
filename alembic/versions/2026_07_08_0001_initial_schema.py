"""Initial schema — baseline of all existing models.

Revision ID: 0001
Revises: (none)
Create Date: 2026-07-08

This migration creates all tables that the ORM models define. For existing
databases that already have these tables (created by Base.metadata.create_all),
stamp with:  alembic stamp 0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── twin_events ───────────────────────────────────────────────────
    op.create_table(
        "twin_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_twin_events_user_id", "twin_events", ["user_id"])
    op.create_index("ix_twin_events_user_id_id", "twin_events", ["user_id", "id"])

    # ── decisions ─────────────────────────────────────────────────────
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("twin_hash", sa.String(64), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("twin_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("engine_version", sa.String(60), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("latency_ms", sa.Float(), server_default=sa.text("0.0")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_decisions_user_id", "decisions", ["user_id"])

    # ── resume_versions ───────────────────────────────────────────────
    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_version", sa.Integer(), nullable=True),
        sa.Column("target_label", sa.String(200), server_default="master"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_resume_versions_user_id", "resume_versions", ["user_id"])
    op.create_unique_constraint("uq_user_version", "resume_versions", ["user_id", "version"])

    # ── applications ──────────────────────────────────────────────────
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_role", sa.String(200), nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="applied"),
        sa.Column("consented", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_applications_user_id", "applications", ["user_id"])


def downgrade() -> None:
    op.drop_table("applications")
    op.drop_table("resume_versions")
    op.drop_table("decisions")
    op.drop_table("twin_events")
    op.drop_table("users")
