"""Users and tasks.

Revision ID: 0001
Revises:
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email = lower(email)", name=op.f("ck_users_email_lowercase")
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "description",
            sa.String(length=2000),
            server_default="",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("assignee_id", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed')",
            name=op.f("ck_tasks_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name=op.f("ck_tasks_completed_at_matches_status"),
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["users.id"],
            name="fk_tasks_creator_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_id"],
            ["users.id"],
            name="fk_tasks_assignee_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
    )
    op.create_index("ix_tasks_creator_id", "tasks", ["creator_id"])
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    op.create_index("ix_tasks_status_due_date", "tasks", ["status", "due_date"])


def downgrade() -> None:
    op.drop_table("tasks")
    op.drop_table("users")
