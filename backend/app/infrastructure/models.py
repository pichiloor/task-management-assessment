"""SQLAlchemy tables. These are persistence details: the rest of the app works
with the domain dataclasses, and repositories translate between the two."""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.domain.export import ExportStatus
from app.domain.task import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH, TaskStatus

# Deterministic constraint names keep Alembic migrations reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_STATUSES = ", ".join(f"'{s.value}'" for s in TaskStatus)
_EXPORT_STATUSES = ", ".join(f"'{s.value}'" for s in ExportStatus)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lowercased (enforced above), so a plain unique index is enough.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TaskRow(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUSES})", name="status_valid"),
        CheckConstraint(
            "(status = 'completed') = (completed_at IS NOT NULL)",
            name="completed_at_matches_status",
        ),
        Index("ix_tasks_status_due_date", "status", "due_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    description: Mapped[str] = mapped_column(
        String(DESCRIPTION_MAX_LENGTH), server_default=""
    )
    status: Mapped[str] = mapped_column(String(20))
    creator_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExportRow(Base):
    __tablename__ = "exports"
    __table_args__ = (
        CheckConstraint(f"status IN ({_EXPORT_STATUSES})", name="status_valid"),
        CheckConstraint(
            f"task_status IS NULL OR task_status IN ({_STATUSES})",
            name="task_status_valid",
        ),
        CheckConstraint(
            "(status = 'pending') = (finished_at IS NULL)",
            name="finished_at_matches_status",
        ),
        CheckConstraint(
            "((status = 'completed') = (row_count IS NOT NULL)) AND "
            "((status = 'completed') = (expires_at IS NOT NULL))",
            name="result_matches_status",
        ),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="error_matches_status",
        ),
        CheckConstraint("row_count >= 0", name="row_count_not_negative"),
        CheckConstraint(
            "due_from IS NULL OR due_to IS NULL OR due_from <= due_to",
            name="due_range_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20))
    # The task filters, applied when the worker runs.
    task_status: Mapped[str | None] = mapped_column(String(20))
    due_from: Mapped[date | None] = mapped_column(Date)
    due_to: Mapped[date | None] = mapped_column(Date)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
