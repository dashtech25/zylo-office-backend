"""Enregistrement idempotent de la permission du module opérations (BE-236).

Appelé par `python -m app.cli seed`. Sans cette ligne, `OPERATION_READ` n'existe pas en
base et ne peut être accordée à aucun rôle.
"""

from app.core.database import AsyncSessionLocal
from app.operations.permissions import OPERATION_READ
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée la permission de lecture des opérations si elle est absente."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, OPERATION_READ, "operations", "Lire une opération asynchrone de l'organisation (BE-236).")
        await db.commit()
