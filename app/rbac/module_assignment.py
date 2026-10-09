"""Rôles de module : création, affectation et retrait (T-018).

Intention : un utilisateur reçoit, par organisation, AU PLUS UN rôle par module
(un rôle « propre » au module). Un même utilisateur peut avoir des rôles
différents selon le module, et selon l'organisation. Toutes les vérifications
d'autorisation sont côté serveur ; le front ne fait que refléter le résultat.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.modules_registry.models import Module
from app.modules_registry.service import is_module_active
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.module_policy import assert_permissions_match_module, is_valid_permission_code
from app.rbac.service import (
    _assert_no_privilege_escalation,
    _get_permission_or_404,
    get_role,
    get_role_permission_codes,
)


async def create_module_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    module_code: str,
    code: str,
    name: str,
    permission_codes: list[str],
) -> Role:
    """Crée un rôle rattaché à un module. Les contrôles ont lieu AVANT toute
    écriture : une erreur ne laisse aucune ligne en attente dans la session."""
    for perm_code in permission_codes:
        if not is_valid_permission_code(perm_code):
            raise AppError(code="permission_code_invalid", message=f"Format de permission invalide : {perm_code}.", status_code=422)

    if (await db.execute(select(Module).where(Module.code == module_code))).scalar_one_or_none() is None:
        raise AppError(code="module_not_found", message=f"Module inconnu : {module_code}.", status_code=404)

    existing = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == code))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="role_code_already_used", message="Ce code de rôle existe déjà pour cette organisation.", status_code=409)

    await assert_permissions_match_module(db, module_code, permission_codes)
    await _assert_no_privilege_escalation(db, organization_id, actor_user_id, permission_codes)

    role = Role(organizationId=organization_id, code=code, name=name, moduleCode=module_code)
    db.add(role)
    await db.flush()
    for perm_code in permission_codes:
        permission = await _get_permission_or_404(db, perm_code)
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))

    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="rbac.moduleRole.create",
        entity_type="Role",
        entity_id=role.id,
        summary=f"Création du rôle de module {role.name} ({module_code}, {len(permission_codes)} permission(s))",
    )
    await db.commit()
    await db.refresh(role)
    return role


async def assign_module_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> UserRole:
    """Affecte un rôle de module à un membre de l'organisation.
    Refus si : rôle hors organisation (404), rôle transverse, cible non membre,
    module inactif, second rôle pour le même module, permission d'un autre
    module, ou permission que le granter ne possède pas (non-élévation)."""
    role = await get_role(db, organization_id, role_id)
    if role.moduleCode is None:
        raise AppError(
            code="role_not_module_role",
            message="Ce rôle n'est pas rattaché à un module : utiliser l'attribution de rôle standard.",
            status_code=422,
        )

    membership = await db.execute(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == target_user_id
        )
    )
    if membership.scalar_one_or_none() is None:
        raise AppError(code="user_not_member", message="Cet utilisateur n'est pas membre de l'organisation.", status_code=404)

    if not await is_module_active(db, organization_id, role.moduleCode):
        raise AppError(code="module_not_active", message=f"Le module {role.moduleCode} n'est pas actif pour cette organisation.", status_code=409)

    already = await db.execute(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.roleId)
        .where(
            UserRole.userId == target_user_id,
            UserRole.organizationId == organization_id,
            Role.moduleCode == role.moduleCode,
        )
    )
    if already.first() is not None:
        raise AppError(
            code="module_role_already_assigned",
            message=f"Cet utilisateur a déjà un rôle sur le module {role.moduleCode}. Retirez-le avant d'en affecter un autre.",
            status_code=409,
        )

    role_codes = await get_role_permission_codes(db, role.id)
    await assert_permissions_match_module(db, role.moduleCode, role_codes)
    await _assert_no_privilege_escalation(db, organization_id, granter_user_id, role_codes)

    user_role = UserRole(userId=target_user_id, organizationId=organization_id, roleId=role.id, resourceType=None, resourceId=None)
    db.add(user_role)
    await db.flush()
    target_user = await db.get(User, target_user_id)
    await record_audit_event(
        db,
        organization_id,
        granter_user_id,
        action="rbac.moduleRole.assign",
        entity_type="UserRole",
        entity_id=user_role.id,
        summary=f"Affectation du rôle {role.name} ({role.moduleCode}) à {target_user.fullName if target_user else target_user_id}",
    )
    await db.commit()
    await db.refresh(user_role)
    return user_role


async def unassign_module_role(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, assignment_id: uuid.UUID) -> None:
    """Retire une affectation de rôle de module. Une attribution de rôle
    transverse n'est jamais retirée ici (404) : elle passe par l'API standard."""
    user_role = await db.get(UserRole, assignment_id)
    role = await db.get(Role, user_role.roleId) if user_role is not None else None
    if user_role is None or user_role.organizationId != organization_id or role is None or role.moduleCode is None:
        raise AppError(code="module_role_assignment_not_found", message="Cette affectation de rôle de module est introuvable.", status_code=404)
    target_user = await db.get(User, user_role.userId)
    await db.delete(user_role)
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="rbac.moduleRole.unassign",
        entity_type="UserRole",
        entity_id=assignment_id,
        summary=f"Retrait du rôle {role.name} ({role.moduleCode}) à {target_user.fullName if target_user else user_role.userId}",
    )
    await db.commit()
