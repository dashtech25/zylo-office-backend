from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class Page(BaseModel, Generic[T]):
    """Enveloppe de pagination standard — tout endpoint listant une collection
    doit renvoyer ce format, quel que soit le module."""

    data: list[T]
    meta: PageMeta


class PageCurseurMeta(BaseModel):
    """Métadonnées d'une page par curseur (BE-191). `next_cursor` est absent
    (None) sur la dernière page ; sinon il se repasse tel quel en `cursor`."""

    limit: int
    next_cursor: str | None


class PageCurseur(BaseModel, Generic[T]):
    """Enveloppe des listes par curseur (BE-191). Pas de `total` : compter
    coûte une requête de plus et n'est pas garanti stable entre deux pages."""

    data: list[T]
    meta: PageCurseurMeta


class ErrorDetail(BaseModel):
    error: dict


class ApiErrorBody(BaseModel):
    """Corps commun des erreurs HTTP de l'API; succès existants inchangés."""

    code: str
    message: str
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    details: list[dict] = Field(default_factory=list)


class ApiErrorResponse(BaseModel):
    """Enveloppe d'erreur commune; request_id correspond à X-Request-Id."""

    error: ApiErrorBody
    request_id: str
