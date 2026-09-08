import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("zylo_office.errors")


class AppError(Exception):
    """Exception métier de base — tous les modules doivent lever AppError (ou une
    sous-classe) plutôt qu'une exception Python brute, pour garantir un format
    de réponse d'erreur unique côté API."""

    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST, details: list | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)


def _jsonable_validation_errors(errors: list[dict]) -> list[dict]:
    """`RequestValidationError.errors()` peut contenir l'exception Python
    d'origine dans `ctx.error` (ex. un `ValueError` levé par un
    `field_validator` métier) — jamais sérialisable telle quelle par
    `json.dumps`, ce qui faisait planter cette réponse en 500 au lieu du 422
    attendu (bug pré-existant, découvert via `_reject_reserved_red`)."""
    safe_errors = []
    for error in errors:
        error = dict(error)
        ctx = error.get("ctx")
        if isinstance(ctx, dict) and isinstance(ctx.get("error"), BaseException):
            ctx = {**ctx, "error": str(ctx["error"])}
            error["ctx"] = ctx
        safe_errors.append(error)
    return safe_errors


def _error_response(status_code: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", extra={"code": exc.code, "path": request.url.path})
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Les données envoyées sont invalides.",
            details=_jsonable_validation_errors(exc.errors()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"path": request.url.path})
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Une erreur interne est survenue.",
        )
