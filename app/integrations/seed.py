"""Déclaration en base de la permission `integrations.read` (BE-164).

Idempotent : crée la permission seulement si elle est absente, comme les autres `seed.py`.
"""

from app.core.database import AsyncSessionLocal
from app.integrations.permissions import INTEGRATIONS_READ
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée `integrations.read` si elle est absente."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, INTEGRATIONS_READ, "integrations", "Consulter le journal des tentatives d'intégration (métadonnées)."
        )
        await db.commit()
