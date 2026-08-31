from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.shared.schemas import Page, PageMeta


class PaginationParams:
    """Dépendance FastAPI générique — tout endpoint de liste du socle ou d'un
    futur module doit l'utiliser plutôt que de redéfinir limit/offset."""

    def __init__(self, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        self.limit = limit
        self.offset = offset


async def paginate(db: AsyncSession, stmt: Select, params: PaginationParams, schema) -> Page:
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(params.limit).offset(params.offset))
    rows = result.scalars().all()
    return Page(
        data=[schema.model_validate(row) for row in rows],
        meta=PageMeta(total=total or 0, limit=params.limit, offset=params.offset),
    )
