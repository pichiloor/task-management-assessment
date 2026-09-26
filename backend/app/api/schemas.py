from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema, model_validator

from app.domain.export import Export, ExportStatus
from app.domain.task import DESCRIPTION_MAX_LENGTH, TITLE_MAX_LENGTH, TaskStatus


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: int
    email: str
    name: str


class UserPublic(BaseModel):
    id: int
    name: str


class ErrorResponse(BaseModel):
    detail: str
    code: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_MAX_LENGTH)
    description: str = Field(default="", max_length=DESCRIPTION_MAX_LENGTH)
    assignee_id: int | None = None
    due_date: date | None = None


class TaskUpdate(BaseModel):
    """Only the fields present in the body are changed. `assignee_id` and
    `due_date` accept null to clear them; the other fields do not."""

    model_config = ConfigDict(extra="forbid")

    # Typed as optional so "omitted" is representable, but documented without
    # null: the validator below rejects an explicit null for these three.
    title: Annotated[
        str | None,
        WithJsonSchema(
            {"type": "string", "minLength": 1, "maxLength": TITLE_MAX_LENGTH}
        ),
    ] = Field(default=None, min_length=1, max_length=TITLE_MAX_LENGTH)
    description: Annotated[
        str | None,
        WithJsonSchema({"type": "string", "maxLength": DESCRIPTION_MAX_LENGTH}),
    ] = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: Annotated[
        TaskStatus | None,
        WithJsonSchema({"type": "string", "enum": [s.value for s in TaskStatus]}),
    ] = None
    assignee_id: int | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def _reject_null_for_required_fields(self) -> Self:
        for name in ("title", "description", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    status: TaskStatus
    creator_id: int
    assignee_id: int | None
    due_date: date | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int
    pages: int


class ExportCreate(BaseModel):
    """Same filters as the task listing, without paging. All optional."""

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus | None = None
    due_date: date | None = None
    due_from: date | None = None
    due_to: date | None = None


class ExportFilters(BaseModel):
    status: TaskStatus | None
    due_from: date | None
    due_to: date | None


class ExportOut(BaseModel):
    id: int
    status: ExportStatus
    filters: ExportFilters
    row_count: int | None
    error_code: str | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None
    download_url: str | None

    @classmethod
    def from_export(cls, export: Export) -> "ExportOut":
        completed = export.status is ExportStatus.COMPLETED
        return cls(
            id=export.id or 0,
            status=export.status,
            filters=ExportFilters(
                status=export.task_status,
                due_from=export.due_from,
                due_to=export.due_to,
            ),
            row_count=export.row_count,
            error_code=export.error_code,
            created_at=export.created_at,
            finished_at=export.finished_at,
            expires_at=export.expires_at,
            download_url=f"/api/v1/exports/{export.id}/download" if completed else None,
        )


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]
