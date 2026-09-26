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


class ConflictError(DomainError):
    """The resource is not in a state that allows the action (maps to 409)."""


class GoneError(DomainError):
    """The resource existed but is no longer available (maps to 410)."""


class ServiceUnavailableError(DomainError):
    """A service the use case needs is down; retrying later may work (503)."""
