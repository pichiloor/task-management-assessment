"""CSV exports.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requester_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("task_status", sa.String(length=20), nullable=True),
        sa.Column("due_from", sa.Date(), nullable=True),
        sa.Column("due_to", sa.Date(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name=op.f("ck_exports_status_valid"),
        ),
        sa.CheckConstraint(
            "task_status IS NULL OR "
            "task_status IN ('pending', 'in_progress', 'completed')",
            name=op.f("ck_exports_task_status_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (finished_at IS NULL)",
            name=op.f("ck_exports_finished_at_matches_status"),
        ),
        sa.CheckConstraint(
            "((status = 'completed') = (row_count IS NOT NULL)) AND "
            "((status = 'completed') = (expires_at IS NOT NULL))",
            name=op.f("ck_exports_result_matches_status"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_exports_error_matches_status"),
        ),
        sa.CheckConstraint(
            "row_count >= 0", name=op.f("ck_exports_row_count_not_negative")
        ),
        sa.CheckConstraint(
            "due_from IS NULL OR due_to IS NULL OR due_from <= due_to",
            name=op.f("ck_exports_due_range_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name="fk_exports_requester_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_exports"),
    )
    op.create_index("ix_exports_requester_id", "exports", ["requester_id"])


def downgrade() -> None:
    op.drop_table("exports")
