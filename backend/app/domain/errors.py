"""Business errors. Each carries a stable machine-readable code for the API."""


class DomainError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ValidationError(DomainError):
    """Input breaks a business rule (maps to 422)."""


class NotFoundError(DomainError):
    """Resource is missing or not visible to the caller (maps to 404)."""


class PermissionDeniedError(DomainError):
    """Caller can see the resource but may not perform the action (maps to 403)."""


class AuthenticationError(DomainError):
    """Missing, invalid or expired credentials (maps to 401)."""
