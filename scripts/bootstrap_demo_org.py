"""Provisionne une organisation de démo Zylo Liquid : user owner, module
activé, toutes les permissions zylo_liquid accordées au rôle owner.
Idempotent (réutilise l'existant si déjà présent)."""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from app.modules_registry.models import OrganizationModule
from app.modules.zylo_liquid import permissions as p

SLUG = "demo-reseau-live"
EMAIL = "demo@zylo-liquid.local"
PASSWORD = "DemoLive2026!"

ALL_PERMS = [v for k, v in vars(p).items() if k.isupper()]


async def main():
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalar_one_or_none()
        if user is None:
            user = User(email=EMAIL, hashedPassword=hash_password(PASSWORD), fullName="Démo Live", status="active")
            db.add(user)
            await db.flush()
            print(f"Utilisateur créé : {EMAIL} / {PASSWORD}")
        else:
            print(f"Utilisateur existant réutilisé : {EMAIL}")

        org = (await db.execute(select(Organization).where(Organization.slug == SLUG))).scalar_one_or_none()
        if org is None:
            org = Organization(name="Réseau Démo Live", slug=SLUG)
            db.add(org)
            await db.flush()
            db.add(OrganizationUser(organizationId=org.id, userId=user.id))
            owner_role = Role(organizationId=org.id, code="owner", name="Propriétaire")
            db.add(owner_role)
            await db.flush()
            db.add(UserRole(userId=user.id, organizationId=org.id, roleId=owner_role.id))
            print(f"Organisation créée : {org.id}")
        else:
            owner_role = (await db.execute(
                select(Role).where(Role.organizationId == org.id, Role.code == "owner")
            )).scalar_one_or_none()
            if owner_role is None:
                owner_role = Role(organizationId=org.id, code="owner", name="Propriétaire")
                db.add(owner_role)
                await db.flush()
            existing_ur = (await db.execute(
                select(UserRole).where(UserRole.userId == user.id, UserRole.organizationId == org.id)
            )).scalar_one_or_none()
            if existing_ur is None:
                db.add(UserRole(userId=user.id, organizationId=org.id, roleId=owner_role.id))
            existing_ou = (await db.execute(
                select(OrganizationUser).where(OrganizationUser.organizationId == org.id, OrganizationUser.userId == user.id)
            )).scalar_one_or_none()
            if existing_ou is None:
                db.add(OrganizationUser(organizationId=org.id, userId=user.id))
            print(f"Organisation existante réutilisée : {org.id}")

        # Module zylo_liquid actif
        om = (await db.execute(
            select(OrganizationModule).where(OrganizationModule.organizationId == org.id, OrganizationModule.moduleCode == "zylo_liquid")
        )).scalar_one_or_none()
        if om is None:
            db.add(OrganizationModule(organizationId=org.id, moduleCode="zylo_liquid", status="active"))
        else:
            om.status = "active"

        # Toutes les permissions zylo_liquid accordées au rôle owner
        existing_rp = (await db.execute(select(RolePermission).where(RolePermission.roleId == owner_role.id))).scalars().all()
        existing_perm_ids = {rp.permissionId for rp in existing_rp}
        for code in ALL_PERMS:
            perm = await get_or_create_permission(db, code, "zylo_liquid", f"Permission {code}")
            if perm.id not in existing_perm_ids:
                db.add(RolePermission(roleId=owner_role.id, permissionId=perm.id))

        await db.commit()
        print(f"organizationId={org.id}")
        print(f"userId={user.id}")


if __name__ == "__main__":
    asyncio.run(main())
