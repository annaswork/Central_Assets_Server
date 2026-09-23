"""Custom domain exception hierarchy for the application.

Controllers raise domain errors from this module; they never raise HTTPException.
"""

from typing import Any


class AppError(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Resource not found",
        code: str = "NOT_FOUND",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=404, details=details)


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Resource conflict",
        code: str = "CONFLICT",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)


class ValidationError(AppError):
    def __init__(
        self,
        message: str = "Validation failed",
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class UnauthorizedError(AppError):
    def __init__(
        self,
        message: str = "Unauthorized",
        code: str = "UNAUTHORIZED",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=401, details=details)


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "Forbidden",
        code: str = "FORBIDDEN",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=403, details=details)


class RateLimitError(AppError):
    def __init__(
        self,
        message: str = "Too many requests",
        code: str = "RATE_LIMITED",
        retry_after: int = 60,
        details: dict[str, Any] | None = None,
    ) -> None:
        details_dict = details or {}
        details_dict["retry_after"] = retry_after
        super().__init__(message=message, code=code, status_code=429, details=details_dict)
        self.retry_after = retry_after


class InstanceCannotCreateContentError(ConflictError):
    """Raised when an operation attempts to author central content from an instance context."""

    def __init__(
        self,
        message: str = (
            "App instances cannot create content. Content must be authored in the central "
            "library first and then referenced."
        ),
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="INSTANCE_CANNOT_CREATE_CONTENT",
            details=details,
        )
