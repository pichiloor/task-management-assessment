from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    password_hash: str
    is_active: bool
