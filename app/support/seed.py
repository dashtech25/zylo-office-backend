"""Déclaration des permissions du module support (BE-262), rejouée au démarrage.

Sans cette déclaration dans la table `permission`, `require_permission()` refuse
toute demande, y compris au propriétaire (règle de CLAUDE.md)."""

from app.core.database import AsyncSessionLocal
from app.rbac.service import get_or_create_permission
from app.support.permissions import SUPPORT_READ, SUPPORT_WRITE_SENSIBLE


async def seed_known_permissions() -> None:
    """Crée `support.read` et `support.write_sensible` si elles n'existent pas."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, SUPPORT_READ, "support", "Lire les données d'une organisation sous accès support (BE-262).")
        await get_or_create_permission(
            db, SUPPORT_WRITE_SENSIBLE, "support", "Écrire sous accès support, en mode écriture uniquement (BE-262)."
        )
        await db.commit()
