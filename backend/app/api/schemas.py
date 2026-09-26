from pydantic import BaseModel


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
