"""Contrat d'erreurs de l'API (BE-001, décision D1).

Toute réponse d'erreur de `/api/v1` a la forme :

    {"error": {"code", "message", "field_errors", "details"}, "request_id"}

- `code` : `validation_error` (422), `internal_error` (500), `http_<statut>`
  pour une erreur HTTP Starlette (404, 405, ...), ou le code métier d'une
  `AppError`.
- `field_errors` : chemin pointé sans préfixe `body`/`query`/`path`.
- `details` : vide, sauf pour les erreurs de validation (liste Pydantic sans
  `input` ni `ctx`, qui peuvent contenir des secrets ou des objets Python).
- `request_id` : identique à l'en-tête `X-Request-Id` (et `X-Correlation-Id`),
  posé par `RequestIdMiddleware` (app/core/middleware.py).

Les gestionnaires sont enregistrés par `register_exception_handlers`, appelé
une seule fois dans app/main.py. Ne pas redéfinir cette enveloppe ailleurs.

Table des codes (BE-220) :

| Statut | Code                         | Origine                                        | field_errors / details |
|--------|------------------------------|------------------------------------------------|------------------------|
| 401    | code métier de AppError      | non authentifié (jeton absent ou invalide)     | vide                   |
| 403    | `permission_denied` ou métier | refus de permission au sein de l'organisation  | vide                   |
| 404    | code métier, ou `http_404`   | ressource absente ou hors périmètre (uniforme) | vide                   |
| 405    | `http_405`                   | méthode non permise sur une route connue       | vide                   |
| 409    | code métier de AppError      | conflit de version ou d'état                   | vide                   |
| 422    | `validation_error`           | validation de la requête                       | renseignés             |
| 500    | `internal_error`             | exception non prévue, sans trace dans la réponse | vide                 |

`http_<statut>` reste le code des erreurs HTTP Starlette sans code métier
(route inconnue, méthode non permise) : il est figé par les tests BE-001.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx
from app.core.messages import message_pour

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
    """Construit la réponse d'erreur unique. Le request ID vient de
    `request.state` (posé par RequestIdMiddleware), à défaut de la contextvar
    `request_id_ctx`. Il est reporté dans le corps et dans les en-têtes
    `X-Request-Id` et `X-Correlation-Id`, pour que le client puisse le citer."""
    request_id = (
        getattr(getattr(request, "state", None), "request_id", None)
        or request_id_ctx.get()
    )
    correlation_id = (
        getattr(getattr(request, "state", None), "correlation_id", None)
        or request_id
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers["X-Request-Id"] = request_id
        response_headers["X-Correlation-Id"] = correlation_id
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
    """Enregistre les quatre gestionnaires de l'enveloppe d'erreur sur `app` :
    `AppError`, `RequestValidationError`, `StarletteHTTPException` et `Exception`
    (filet de sécurité 500). Appelée une seule fois, dans app/main.py : un
    second appel doublerait les gestionnaires sans effet visible mais
    trompeur. L'ordre n'a pas d'importance : Starlette choisit le gestionnaire
    le plus spécifique de la classe d'exception levée."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Renvoie une `AppError` avec son code, son statut, ses détails et ses
        en-têtes propres (ex. Retry-After). Journalise en avertissement, sans
        le corps de la requête."""
        logger.warning("app_error", extra={"code": exc.code, "path": request.url.path})
        # Le texte de `AppError` reste le repli : sans clé dans un catalogue
        # (cas de la plupart des codes métier), la réponse ne change pas.
        return _error_response(
            exc.status_code,
            exc.code,
            message_pour(exc.code, exc.message),
            exc.details,
            exc.headers,
            exc.field_errors,
            request,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Erreur de validation de la requête : 422, code `validation_error`,
        `field_errors` par chemin, `details` sans `input` ni `ctx`."""
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            message_pour("validation_error", "Les données envoyées sont invalides."),
            details=_jsonable_validation_errors(exc.errors()),
            field_errors=_validation_field_errors(exc.errors()),
            request=request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Erreur HTTP Starlette (404 route inconnue, 405 méthode non permise,
        erreurs levées par les routes) : code `http_<statut>`. Le message
        Starlette est repris tel quel s'il est textuel ; `details` reste vide
        (contrat BE-001)."""
        message = exc.detail if isinstance(exc.detail, str) else "La requête n’a pas pu être traitée."
        return _error_response(
            exc.status_code,
            f"http_{exc.status_code}",
            message,
            details=[],
            headers=exc.headers,
            request=request,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Erreur non prévue : 500, code `internal_error`, message générique.
        La trace part dans le journal (événement `unhandled_error`, avec le
        request_id), jamais dans la réponse. Ce gestionnaire tourne hors de
        `RequestIdMiddleware`, d'où la lecture du request_id dans `request.state`."""
        logger.exception(
            "unhandled_error",
            extra={"path": request.url.path, "request_id": getattr(request.state, "request_id", None)},
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            message_pour("internal_error", "Une erreur interne est survenue."),
            request=request,
        )
