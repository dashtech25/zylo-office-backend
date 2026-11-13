from app.core.database import AsyncSessionLocal
from app.identity.permissions import (
    MEMBERS_INVITE,
    MEMBERSHIP_MANAGE,
    ORGANIZATION_LEGAL_READ,
    ORGANIZATION_READ,
    ORGANIZATION_SETTINGS_UPDATE,
    ORGANIZATION_UPDATE,
    ORGANIZATION_VERIFICATION_READ,
    ORGANIZATION_VERIFICATION_SUBMIT,
    USER_MANAGE,
)
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Déclare la permission de gestion des utilisateurs au catalogue (T-021), pour que
    l'administration des rôles puisse l'attribuer à un rôle personnalisé."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, USER_MANAGE, "identity", "Créer des utilisateurs, réémettre une invitation, suspendre et réactiver un membre.")
        await get_or_create_permission(db, MEMBERS_INVITE, "identity", "Inviter une personne à rejoindre l'organisation et consulter les invitations en attente.")
        await get_or_create_permission(db, ORGANIZATION_SETTINGS_UPDATE, "identity", "Modifier les réglages de l'organisation courante (nom).")
        await get_or_create_permission(db, ORGANIZATION_READ, "identity", "Lire l'organisation courante (BE-186).")
        await get_or_create_permission(db, ORGANIZATION_UPDATE, "identity", "Modifier l'organisation courante, verrou expectedVersion (BE-186).")
        await get_or_create_permission(db, ORGANIZATION_LEGAL_READ, "identity", "Voir les identifiants légaux confidentiels de l'organisation (BE-186).")
        await get_or_create_permission(db, MEMBERSHIP_MANAGE, "identity", "Inviter, changer l'état et révoquer un membership de l'organisation (BE-189).")
        await get_or_create_permission(db, ORGANIZATION_VERIFICATION_READ, "identity", "Lire le statut de vérification de l'organisation (BE-103).")
        await get_or_create_permission(db, ORGANIZATION_VERIFICATION_SUBMIT, "identity", "Déposer une demande de vérification de l'organisation (BE-103).")
        await db.commit()
