from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus | None = None
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


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]
