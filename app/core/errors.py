import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger("zylo_office.errors")


class AppError(Exception):
    """Exception métier de base — tous les modules doivent lever AppError (ou une
    sous-classe) plutôt qu'une exception Python brute, pour garantir un format
    de réponse d'erreur unique côté API."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: list | None = None,
        headers: dict[str, str] | None = None,
        field_errors: dict[str, list[str]] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        self.field_errors = field_errors or {}
        # En-têtes HTTP additionnels (ex. Retry-After pour un 429) ; None = aucun.
        self.headers = headers
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
        # Pydantic input may contain passwords, tokens, or other submitted
        # secrets. Keep the legacy list shape and useful loc/type/msg fields,
        # but never return input values or validator context.
        error.pop("input", None)
        error.pop("ctx", None)
        safe_errors.append(error)
    return safe_errors


def _error_response(
    status_code: int,
    code: str,
    message: str,
    details: list | None = None,
    headers: dict[str, str] | None = None,
    field_errors: dict[str, list[str]] | None = None,
    request: Request | None = None,
) -> JSONResponse:
    request_id = (
        getattr(getattr(request, "state", None), "request_id", None)
        or request_id_ctx.get()
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-Id"] = request_id
        response_headers["X-Correlation-Id"] = request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors or {},
                "details": details or [],
            },
            "request_id": request_id,
        },
        headers=response_headers,
    )


def _validation_field_errors(errors: list[dict]) -> dict[str, list[str]]:
    """Convertit les erreurs Pydantic en chemins simples, sans exposer ctx."""
    result: dict[str, list[str]] = {}
    sources = {"body", "query", "path", "header", "cookie"}
    for error in errors:
        location = list(error.get("loc", ()))
        if location and str(location[0]) in sources:
            location.pop(0)
        path = ".".join(str(part) for part in location) or "_request"
        result.setdefault(path, []).append(str(error.get("msg", "Valeur invalide.")))
    return result


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning("app_error", extra={"code": exc.code, "path": request.url.path})
        return _error_response(
            exc.status_code, exc.code, exc.message, exc.details, exc.headers, exc.field_errors, request
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "Les données envoyées sont invalides.",
            details=_jsonable_validation_errors(exc.errors()),
            field_errors=_validation_field_errors(exc.errors()),
            request=request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "La requête n’a pas pu être traitée."
        details = [] if isinstance(exc.detail, str) else [{"detail": exc.detail}]
        return _error_response(
            exc.status_code,
            f"http_{exc.status_code}",
            message,
            details=details,
            headers=exc.headers,
            request=request,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            extra={"path": request.url.path, "request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Une erreur interne est survenue.",
            request=request,
        )
