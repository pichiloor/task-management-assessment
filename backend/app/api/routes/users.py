from fastapi import APIRouter

from app.api.dependencies import CurrentUser, TaskServiceDep
from app.api.schemas import ErrorResponse, UserProfile, UserPublic

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={401: {"model": ErrorResponse, "description": "Not authenticated"}},
)


@router.get("/me", response_model=UserProfile, summary="Current user")
def read_me(user: CurrentUser) -> UserProfile:
    return UserProfile(id=user.id, email=user.email, name=user.name)


@router.get(
    "", response_model=list[UserPublic], summary="Users a task can be assigned to"
)
def list_assignable_users(_: CurrentUser, service: TaskServiceDep) -> list[UserPublic]:
    return [UserPublic(id=u.id, name=u.name) for u in service.assignable_users()]
