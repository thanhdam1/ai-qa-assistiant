class AppError(Exception):
    def __init__(
        self, code: str, message: str, status_code: int = 400, details: dict | None = None
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, resource: str):
        super().__init__("not_found", f"{resource} not found", 404)


class StaleVersionError(AppError):
    def __init__(self):
        super().__init__("stale_version", "The source story or review is stale", 409)


class CyclicDependencyError(AppError):
    def __init__(self, message: str = "Cannot create circular dependency between stories"):
        super().__init__("cyclic_dependency_detected", message, 409)


class ReviewNotApprovedError(AppError):
    def __init__(self):
        super().__init__("review_not_approved", "A current approved review is required", 409)


class AIProviderError(AppError):
    def __init__(
        self,
        message: str,
        retryable: bool = False,
        provider_code: str | None = None,
        validation_details: dict | None = None,
    ):
        details = {"retryable": retryable}
        if provider_code:
            details["provider_code"] = provider_code
        if validation_details is not None:
            details["validation"] = validation_details
        super().__init__("ai_provider_error", message, 503, details)
