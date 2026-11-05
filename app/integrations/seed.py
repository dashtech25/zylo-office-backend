"""Déclaration en base des permissions `integrations.read` (BE-164) et `integrations.manage` (BE-165).

Idempotent : crée chaque permission seulement si elle est absente, comme les autres `seed.py`.
"""

from app.core.database import AsyncSessionLocal
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée `integrations.read` et `integrations.manage` si elles sont absentes."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, INTEGRATIONS_READ, "integrations", "Consulter le journal des tentatives d'intégration (métadonnées)."
        )
        await get_or_create_permission(
            db, INTEGRATIONS_MANAGE, "integrations", "Reprendre manuellement une lettre morte d'intégration."
        )
        await db.commit()
