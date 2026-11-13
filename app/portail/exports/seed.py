"""Déclaration en base de la permission d'export du portail (BE-117).

Appelé par app/cli.py au démarrage des seeds. Idempotent : `get_or_create_permission`
ne crée la ligne qu'une fois.
"""

from app.core.database import AsyncSessionLocal
from app.portail.exports.permissions import DATA_EXPORT
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, DATA_EXPORT, "data", "Demander, lire et télécharger un export de données de l'organisation (BE-117)."
        )
        await db.commit()
