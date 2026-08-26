"""扩展 API 的独立鉴权能力。"""

from module.extension_api.auth.service import (
    ALL_AUTH_SCOPES,
    AuthenticationRequiredError,
    AuthPrincipal,
    AuthService,
    AuthServiceError,
    BootstrapTokenError,
    PasswordResetTokenError,
    PermissionDeniedError,
    RateLimitExceededError,
    SetupAlreadyCompletedError,
    SetupRequiredError,
    ValidationError,
)

__all__ = [
    "ALL_AUTH_SCOPES",
    "AuthPrincipal",
    "AuthService",
    "AuthServiceError",
    "AuthenticationRequiredError",
    "BootstrapTokenError",
    "PasswordResetTokenError",
    "PermissionDeniedError",
    "RateLimitExceededError",
    "SetupAlreadyCompletedError",
    "SetupRequiredError",
    "ValidationError",
]
