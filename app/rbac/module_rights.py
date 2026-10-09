"""Résolution des droits PAR MODULE (T-018) : point d'entrée unique.

Intention : un droit de module = (utilisateur, organisation, module, permission)
accordé par le moteur central `user_has_permission` (deny prioritaire, refus
par défaut), restreint en plus à trois conditions :
1. la permission appartient au module ou au socle partagé (liste fermée) ;
2. le module est actif pour l'organisation (un module inactif bloque même si
   la permission est accordée, comme `require_module_active`) ;
3. le moteur central confirme l'accès.
Aucune autre logique d'autorisation n'existe par module : tout passe par ici.
"""

import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.service import is_module_active
from app.rbac.models import Permission, Role, UserRole
from app.rbac.module_policy import permission_belongs_to_module
from app.rbac.service import get_current_organization_id, user_has_permission
from app.shared.permissions import SHARED_PERMISSION_CODES

# Bloc de la liste des droits réservé au socle partagé (pas un module du catalogue).
SHARED_BLOCK = "shared"


async def user_has_module_permission(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, module_code: str, permission_code: str
) -> bool:
    """Vrai seulement si les trois conditions de l'en-tête sont remplies.
    Une permission inconnue, hors module ou module inactif donne False (refus
    par défaut) sans jamais lever d'erreur, pour qu'un appelant ne puisse pas
    sonder l'existence d'un code par le message d'erreur."""
    if not await is_module_active(db, organization_id, module_code):
        return False
    permission_module_code = (
        await db.execute(select(Permission.moduleCode).where(Permission.code == permission_code))
    ).scalar_one_or_none()
    if permission_module_code is None:
        return False
    if not permission_belongs_to_module(permission_code, permission_module_code, module_code):
        return False
    return await user_has_permission(db, user_id, organization_id, permission_code)


def require_module_permission(module_code: str, permission_code: str):
    """Dépendance FastAPI : même contrat que `require_permission`, mais exige
    en plus que la permission appartienne au module et que le module soit actif."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not await user_has_module_permission(db, current_user.id, organization_id, module_code, permission_code):
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {permission_code} (module {module_code}).",
                status_code=403,
            )

    return dependency


async def effective_rights_by_module(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[dict]:
    """Droits effectifs d'un utilisateur, un bloc par module du catalogue.
    Un module inactif (ou jamais activé) liste ses rôles mais aucune permission :
    la liste reflète ce que le serveur autorisera réellement."""
    modules = (await db.execute(select(Module).order_by(Module.code))).scalars().all()
    statuses = {
        om.moduleCode: om.status
        for om in (
            await db.execute(select(OrganizationModule).where(OrganizationModule.organizationId == organization_id))
        ).scalars().all()
    }
    assignments = (
        await db.execute(
            select(UserRole.id, Role.id, Role.code, Role.name, Role.moduleCode)
            .join(Role, Role.id == UserRole.roleId)
            .where(
                UserRole.userId == user_id,
                UserRole.organizationId == organization_id,
                Role.moduleCode.is_not(None),
            )
            .order_by(Role.code)
        )
    ).all()
    candidates = (
        await db.execute(
            select(Permission.code, Permission.moduleCode).where(
                Permission.code.in_(list(SHARED_PERMISSION_CODES))
                | Permission.moduleCode.in_([m.code for m in modules])
            )
        )
    ).all()

    result: list[dict] = []
    for module in modules:
        active = statuses.get(module.code) in ("active", "trial")
        permission_codes: list[str] = []
        if active:
            for code, permission_module_code in candidates:
                if code not in SHARED_PERMISSION_CODES and permission_belongs_to_module(code, permission_module_code, module.code) and await user_has_permission(
                    db, user_id, organization_id, code
                ):
                    permission_codes.append(code)
        result.append(
            {
                "moduleCode": module.code,
                "active": active,
                "roles": [
                    {"assignmentId": a_id, "roleId": r_id, "code": r_code, "name": r_name}
                    for a_id, r_id, r_code, r_name, r_module in assignments
                    if r_module == module.code
                ],
                "permissionCodes": sorted(permission_codes),
            }
        )

    # Le socle partagé est listé à part : une permission partagée est valable dans
    # tout module actif (règle d'application), mais la lister sous chaque module
    # ferait croire qu'elle y a été accordée par un rôle de ce module.
    shared_codes = []
    for code, _permission_module_code in candidates:
        if code in SHARED_PERMISSION_CODES and await user_has_permission(db, user_id, organization_id, code):
            shared_codes.append(code)
    result.append(
        {"moduleCode": SHARED_BLOCK, "active": True, "roles": [], "permissionCodes": sorted(set(shared_codes))}
    )
    return result
