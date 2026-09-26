from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    password_hash: str
    is_active: bool


@dataclass(frozen=True)
class UserSummary:
    """Public view of a user: safe to show to any authenticated caller."""

    id: int
    name: str
