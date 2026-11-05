"""Déclaration en base de la permission d'export de données (BE-243).

Sans cette ligne, `require_permission` refuse, y compris au propriétaire (CLAUDE.md, IAM).
Appelé par app/cli.py au démarrage des seeds.
"""

from app.core.database import AsyncSessionLocal
from app.exports.permissions import DONNEES_EXPORT_CREER
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, DONNEES_EXPORT_CREER, "exports", "Demander un export de données d'un sujet ou du tenant (BE-243)."
        )
        await db.commit()
