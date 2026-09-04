from typing import Generic, TypeVar

from pydantic import BaseModel

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


class ErrorDetail(BaseModel):
    error: dict
