from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

# Taille de pool explicite (2026-09-11) — la valeur par défaut de SQLAlchemy
# (pool_size=5, max_overflow=10, soit 15 connexions max) sature dès qu'une
# seule page station charge ses ~15-20 appels en parallèle (vue d'ensemble +
# centre admin), causant des files d'attente de plusieurs dizaines de
# secondes observées en usage réel (plainte de lenteur déjà remontée, non
# investiguée jusqu'ici). L'endpoint Neon utilisé est déjà le pooler
# (pgbouncer, suffixe "-pooler"), largement dimensionné pour ce nombre de
# connexions applicatives.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=20,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles SQLAlchemy du socle et des modules futurs."""


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
