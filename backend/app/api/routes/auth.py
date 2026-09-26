from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies import AuthServiceDep
from app.api.schemas import ErrorResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Bad credentials"}},
    summary="Log in with email (as username) and password",
)
def issue_token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], auth: AuthServiceDep
) -> TokenResponse:
    return TokenResponse(access_token=auth.login(form.username, form.password))
