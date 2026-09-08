from app.core.database import AsyncSessionLocal
from app.rbac.permissions import GRANT_MANAGE, ROLE_MANAGE
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, ROLE_MANAGE, "rbac", "Créer des rôles et modifier leurs permissions, attribuer/retirer un rôle.")
        await get_or_create_permission(db, GRANT_MANAGE, "rbac", "Accorder ou refuser une permission individuelle, révoquer un grant.")
        await db.commit()
