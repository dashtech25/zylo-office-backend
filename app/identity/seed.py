from app.core.database import AsyncSessionLocal
from app.identity.permissions import USER_MANAGE
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Déclare la permission de gestion des utilisateurs au catalogue (T-021), pour que
    l'administration des rôles puisse l'attribuer à un rôle personnalisé."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, USER_MANAGE, "identity", "Créer des utilisateurs, réémettre une invitation, suspendre et réactiver un membre.")
        await db.commit()
