from app.core.database import AsyncSessionLocal
from app.identity.permissions import MEMBERS_INVITE, ORGANIZATION_SETTINGS_UPDATE, USER_MANAGE
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Déclare la permission de gestion des utilisateurs au catalogue (T-021), pour que
    l'administration des rôles puisse l'attribuer à un rôle personnalisé."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, USER_MANAGE, "identity", "Créer des utilisateurs, réémettre une invitation, suspendre et réactiver un membre.")
        await get_or_create_permission(db, MEMBERS_INVITE, "identity", "Inviter une personne à rejoindre l'organisation et consulter les invitations en attente.")
        await get_or_create_permission(db, ORGANIZATION_SETTINGS_UPDATE, "identity", "Modifier les réglages de l'organisation courante (nom).")
        await db.commit()
