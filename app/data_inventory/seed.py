"""Déclaration en base de la permission d'inventaire des données (BE-242).

Appelé au même titre que les autres `seed.py` du socle : la permission doit
exister en base pour être accordable, sinon `require_permission` refuse, y
compris au propriétaire (CLAUDE.md, « Sécurité, IAM et permissions »).
"""

from app.core.database import AsyncSessionLocal
from app.data_inventory.permissions import DONNEES_INVENTAIRE_LIRE
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée la permission `donnees.inventaire.lire` si elle est absente (idempotent)."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, DONNEES_INVENTAIRE_LIRE, "donnees", "Consulter l'inventaire des données et des classes de rétention."
        )
        await db.commit()
