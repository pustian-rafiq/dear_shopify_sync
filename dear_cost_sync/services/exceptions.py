"""Typed exceptions for the cost-sync application."""

from __future__ import annotations


class CostSyncError(Exception):
    error_code = "COST_SYNC_ERROR"


class ConfigurationError(CostSyncError):
    error_code = "CONFIG_ERROR"


class LockError(CostSyncError):
    error_code = "LOCK_ERROR"


class ApiError(CostSyncError):
    error_code = "API_ERROR"

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(ApiError):
    error_code = "AUTH_ERROR"


class RateLimitError(ApiError):
    error_code = "RATE_LIMIT"

    def __init__(
        self,
        message: str,
        status_code: int | None = 429,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code)
        self.retry_after = retry_after


class TransientApiError(ApiError):
    error_code = "TRANSIENT_API_ERROR"


class DearApiError(ApiError):
    error_code = "DEAR_API_ERROR"


class ShopifyGraphQLError(ApiError):
    error_code = "SHOPIFY_GRAPHQL_ERROR"


class ShopifyUserError(CostSyncError):
    error_code = "SHOPIFY_USER_ERROR"


class ValidationError(CostSyncError):
    error_code = "VALIDATION_ERROR"
