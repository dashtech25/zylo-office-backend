import uuid
from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import OrganizationUser, User
from app.rbac.models import Permission, Role, RolePermission, UserPermissionGrant, UserRole


async def get_current_organization_id(
    x_organization_id: uuid.UUID = Header(..., alias="X-Organization-Id"),
) -> uuid.UUID:
    """L'organisation courante est portée par le header X-Organization-Id — un
    utilisateur pouvant appartenir à plusieurs organisations, elle ne peut pas
    être déduite du seul token JWT."""
    return x_organization_id


def _scope_covers(
    grant_resource_type: str | None,
    grant_resource_id: uuid.UUID | None,
    requested_resource_type: str | None,
    requested_resource_id: uuid.UUID | None,
) -> bool:
    """Un grant à portée NULL (toute l'organisation) couvre toujours la
    ressource demandée. Un grant scopé à une ressource précise ne couvre que
    cette ressource exacte — jamais une autre, jamais une vérification
    "org entière" (« rôle et permissions... .md » §5.4 : la portée du deny
    doit être égale ou plus large que celle demandée, jamais l'inverse)."""
    if grant_resource_type is None:
        return True
    if requested_resource_type is None:
        return False
    return grant_resource_type == requested_resource_type and grant_resource_id == requested_resource_id


async def _role_permission_grants(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID
) -> list[tuple[str, str | None, uuid.UUID | None]]:
    """Toutes les permissions issues des rôles actifs de l'utilisateur, avec
    la portée de LEUR ATTRIBUTION (`UserRole.resourceType/resourceId`) — pas
    une portée propre au rôle (le contenu d'un `Role` reste inchangé, seule
    l'attribution à cet utilisateur peut être restreinte à une ressource
    précise, ex. un gérant limité à sa station). Null = organisation entière
    (comportement historique, rétro-compatible)."""
    stmt = (
        select(Permission.code, UserRole.resourceType, UserRole.resourceId)
        .join(RolePermission, RolePermission.permissionId == Permission.id)
        .join(Role, Role.id == RolePermission.roleId)
        .join(UserRole, UserRole.roleId == Role.id)
        .where(
            UserRole.userId == user_id,
            UserRole.organizationId == organization_id,
            Role.organizationId == organization_id,
        )
    )
    result = await db.execute(stmt)
    return list(result.all())


async def _applicable_grants(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, permission_code: str
) -> list[UserPermissionGrant]:
    """Tous les grants (allow ET deny) actuellement valides pour cet
    utilisateur sur ce code de permission — expiration/révocation filtrées en
    base, le filtrage de portée (scope) reste à faire par l'appelant via
    `_scope_covers` (dépend de la ressource demandée, inconnue ici)."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(UserPermissionGrant)
        .join(Permission, Permission.id == UserPermissionGrant.permissionId)
        .where(
            UserPermissionGrant.userId == user_id,
            UserPermissionGrant.organizationId == organization_id,
            Permission.code == permission_code,
            UserPermissionGrant.revokedAt.is_(None),
            UserPermissionGrant.validFrom <= now,
            (UserPermissionGrant.validUntil.is_(None)) | (UserPermissionGrant.validUntil > now),
        )
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def user_has_permission(
    db: AsyncSession,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    permission_code: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> bool:
    """Algorithme de résolution — « rôle et permissions global global et
    spécifique par module Zylo Office.md » §5.4 :

    1. Candidats allow = permissions des rôles actifs dont la portée
       d'ATTRIBUTION (`UserRole.resourceType/resourceId`, org entière par
       défaut) couvre la ressource demandée, UNION grants individuels
       effect=allow dont la portée couvre la ressource demandée.
    2. Candidats deny = grants individuels effect=deny dont la portée couvre
       la ressource demandée.
    3. Un deny applicable annule TOUJOURS tout allow, quelle que soit son
       origine (rôle ou grant direct) — c'est l'écart assumé par rapport au
       modèle "union pure" d'Odoo/Dolibarr (aucun refus explicite chez eux),
       exigé par `formation/role_permission.md` §0.2.
    4. Sinon, autorisé si au moins un allow s'applique.
    5. Sinon, refusé (absence de grant = refus, jamais un accès supposé)."""
    role_grants = await _role_permission_grants(db, user_id, organization_id)
    has_role_allow = any(
        code == permission_code and _scope_covers(role_resource_type, role_resource_id, resource_type, resource_id)
        for code, role_resource_type, role_resource_id in role_grants
    )

    grants = await _applicable_grants(db, user_id, organization_id, permission_code)
    has_grant_allow = any(
        g.effect == "allow" and _scope_covers(g.resourceType, g.resourceId, resource_type, resource_id) for g in grants
    )
    has_deny = any(
        g.effect == "deny" and _scope_covers(g.resourceType, g.resourceId, resource_type, resource_id) for g in grants
    )

    if has_deny:
        return False
    return has_role_allow or has_grant_allow


def require_permission(permission_code: str):
    """Dépendance FastAPI générique — un module déclare simplement
    `Depends(require_permission("crm.contact.read"))` sur sa route, sans jamais
    dupliquer la logique d'autorisation (grande_phases.md §8)."""

    async def dependency(
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        allowed = await user_has_permission(db, current_user.id, organization_id, permission_code)
        if not allowed:
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {permission_code}.",
                status_code=403,
            )

    return dependency


def require_permission_scoped(permission_code: str, resource_type: str, path_param: str):
    """Variante de `require_permission` qui rattache la vérification à une
    ressource précise (ex. la station du chemin d'URL) plutôt qu'à
    l'organisation entière — §5.3/§17 du document d'architecture RBAC. Un
    grant individuel `deny` scopé à CETTE ressource peut alors bloquer
    l'accès même si le rôle de l'utilisateur l'autorise par ailleurs (portée
    org entière) ; un grant `allow` scopé peut à l'inverse débloquer un
    utilisateur qui n'a pas le rôle correspondant. Rétro-compatible : un
    utilisateur qui n'a que des permissions de rôle (jamais scopées) continue
    de passer normalement, `_scope_covers` traitant "org entière" comme
    couvrant toute ressource demandée."""

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        raw_id = request.path_params.get(path_param)
        resource_id = uuid.UUID(str(raw_id)) if raw_id is not None else None
        allowed = await user_has_permission(
            db, current_user.id, organization_id, permission_code, resource_type, resource_id
        )
        if not allowed:
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {permission_code}.",
                status_code=403,
            )

    return dependency


def require_permission_scoped_via(permission_code: str, resolve_scope):
    """Généralisation de `require_permission_scoped` pour le cas où la
    ressource à protéger n'est pas directement nommée dans le chemin d'URL —
    ex. `/tanks/{tank_id}` doit être scopé à la STATION de la cuve (portée
    utile en pratique, cf. `role_permission.md` §2.3 : "le chef d'équipe
    reçoit Cuve Diesel"), pas à la cuve elle-même. `resolve_scope` est un
    callable `async def(db, organization_id, path_params) -> tuple[str
    | None, uuid.UUID | None]` — retourner `(None, None)` équivaut à une
    vérification org entière (comportement de `require_permission`)."""

    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        resource_type, resource_id = await resolve_scope(db, organization_id, request.path_params)
        allowed = await user_has_permission(
            db, current_user.id, organization_id, permission_code, resource_type, resource_id
        )
        if not allowed:
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {permission_code}.",
                status_code=403,
            )

    return dependency


async def get_or_create_permission(db: AsyncSession, code: str, module_code: str, description: str) -> Permission:
    result = await db.execute(select(Permission).where(Permission.code == code))
    permission = result.scalar_one_or_none()
    if permission:
        return permission
    permission = Permission(code=code, moduleCode=module_code, description=description)
    db.add(permission)
    await db.flush()
    return permission


# ---------------------------------------------------------------------------
# Rôles
# ---------------------------------------------------------------------------


async def list_roles(db: AsyncSession, organization_id: uuid.UUID) -> list[Role]:
    result = await db.execute(select(Role).where(Role.organizationId == organization_id).order_by(Role.name))
    return list(result.scalars().all())


async def get_role(db: AsyncSession, organization_id: uuid.UUID, role_id: uuid.UUID) -> Role:
    role = await db.get(Role, role_id)
    if role is None or role.organizationId != organization_id:
        raise AppError(code="role_not_found", message="Rôle introuvable.", status_code=404)
    return role


async def get_role_permission_codes(db: AsyncSession, role_id: uuid.UUID) -> list[str]:
    stmt = select(Permission.code).join(RolePermission, RolePermission.permissionId == Permission.id).where(
        RolePermission.roleId == role_id
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_role(
    db: AsyncSession, organization_id: uuid.UUID, creator_user_id: uuid.UUID, code: str, name: str, permission_codes: list[str]
) -> Role:
    """Création d'un rôle personnalisé (`role.create.custom` de
    `role_permission.md` §1.1) — toujours bornée par la non-élévation de
    privilège du créateur (§5.5 du document d'architecture) : il ne peut
    inclure dans le rôle que des permissions qu'il possède lui-même."""
    existing = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == code))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="role_code_already_used", message="Ce code de rôle existe déjà pour cette organisation.", status_code=409)

    await _assert_no_privilege_escalation(db, organization_id, creator_user_id, permission_codes)

    role = Role(organizationId=organization_id, code=code, name=name)
    db.add(role)
    await db.flush()

    for perm_code in permission_codes:
        permission = await _get_permission_or_404(db, perm_code)
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))

    await record_audit_event(
        db,
        organization_id,
        creator_user_id,
        action="rbac.role.create",
        entity_type="Role",
        entity_id=role.id,
        summary=f"Création du rôle {role.name} ({len(permission_codes)} permission(s))",
    )
    await db.commit()
    await db.refresh(role)
    return role


async def update_role_permissions(
    db: AsyncSession, organization_id: uuid.UUID, editor_user_id: uuid.UUID, role_id: uuid.UUID, permission_codes: list[str]
) -> Role:
    role = await get_role(db, organization_id, role_id)
    if role.code == "owner":
        raise AppError(code="owner_role_immutable", message="Le rôle Propriétaire ne peut pas être modifié.", status_code=409)

    await _assert_no_privilege_escalation(db, organization_id, editor_user_id, permission_codes)

    existing = await db.execute(select(RolePermission).where(RolePermission.roleId == role_id))
    for row in existing.scalars().all():
        await db.delete(row)
    await db.flush()

    for perm_code in permission_codes:
        permission = await _get_permission_or_404(db, perm_code)
        db.add(RolePermission(roleId=role.id, permissionId=permission.id))

    await record_audit_event(
        db,
        organization_id,
        editor_user_id,
        action="rbac.role.update",
        entity_type="Role",
        entity_id=role.id,
        summary=f"Modification des permissions du rôle {role.name} ({len(permission_codes)} permission(s))",
        changes={"permissionCodes": permission_codes},
    )
    await db.commit()
    await db.refresh(role)
    return role


async def _get_permission_or_404(db: AsyncSession, code: str) -> Permission:
    result = await db.execute(select(Permission).where(Permission.code == code))
    permission = result.scalar_one_or_none()
    if permission is None:
        raise AppError(code="permission_not_found", message=f"Permission inconnue : {code}.", status_code=404)
    return permission


async def _assert_no_privilege_escalation(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    permission_codes: list[str],
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> None:
    """Règle §0.1 de `role_permission.md` : un utilisateur ne peut jamais
    accorder/inclure dans un rôle une permission qu'il ne possède pas
    lui-même, À LA PORTÉE QU'IL S'APPRÊTE À ACCORDER — contrôlé ici côté
    serveur, jamais seulement côté interface. Un propriétaire (portée org
    entière) peut accorder une portée plus étroite (une station) sans
    difficulté ; l'inverse serait une élévation de privilège."""
    for code in permission_codes:
        if not await user_has_permission(db, actor_user_id, organization_id, code, resource_type, resource_id):
            raise AppError(
                code="privilege_escalation_denied",
                message=f"Vous ne pouvez pas accorder une permission que vous ne possédez pas vous-même sur cette portée : {code}.",
                status_code=403,
            )


# ---------------------------------------------------------------------------
# Attribution de rôle
# ---------------------------------------------------------------------------


async def assign_role(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_id: uuid.UUID,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
) -> UserRole:
    """`resource_type`/`resource_id` (ex. `("station", <uuid>)`) restreint
    l'exercice des permissions de ce rôle à CETTE ressource pour cet
    utilisateur — le contenu du rôle (`RolePermission`) ne change pas, seule
    cette attribution est bornée (résout le point bloquant identifié dans
    `processus-double-sources-verite/02-modele-double-source.md` §6 : un
    gérant peut désormais être rattaché à sa seule station via le mécanisme
    RBAC déjà existant, sans nouvelle table)."""
    role = await get_role(db, organization_id, role_id)
    role_codes = await get_role_permission_codes(db, role.id)
    await _assert_no_privilege_escalation(db, organization_id, granter_user_id, role_codes, resource_type, resource_id)

    existing = await db.execute(
        select(UserRole).where(
            UserRole.userId == target_user_id,
            UserRole.organizationId == organization_id,
            UserRole.roleId == role_id,
            UserRole.resourceType == resource_type,
            UserRole.resourceId == resource_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="role_already_assigned", message="Ce rôle est déjà attribué à cet utilisateur sur cette portée.", status_code=409)

    user_role = UserRole(
        userId=target_user_id, organizationId=organization_id, roleId=role_id, resourceType=resource_type, resourceId=resource_id
    )
    db.add(user_role)
    target_user = await db.get(User, target_user_id)
    scope_label = f" (portée : {resource_type} {resource_id})" if resource_type else ""
    await record_audit_event(
        db,
        organization_id,
        granter_user_id,
        action="rbac.role.assign",
        entity_type="UserRole",
        entity_id=role.id,
        summary=f"Attribution du rôle {role.name} à {target_user.fullName if target_user else target_user_id}{scope_label}",
        scope_resource_type=resource_type,
        scope_resource_id=resource_id,
    )
    await db.commit()
    await db.refresh(user_role)
    return user_role


async def unassign_role(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, assignment_id: uuid.UUID
) -> None:
    """Cible l'attribution précise (`UserRole.id`), pas seulement le rôle —
    un même rôle peut être attribué deux fois au même utilisateur avec des
    portées différentes (ex. gérant sur deux stations distinctes), retirer
    "le" rôle par son seul code serait ambigu."""
    user_role = await db.get(UserRole, assignment_id)
    if user_role is None or user_role.organizationId != organization_id:
        raise AppError(code="role_not_assigned", message="Cette attribution de rôle est introuvable.", status_code=404)
    role_id = user_role.roleId
    target_user_id = user_role.userId
    role = await db.get(Role, role_id)
    target_user = await db.get(User, target_user_id)
    await db.delete(user_role)
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="rbac.role.unassign",
        entity_type="UserRole",
        entity_id=role_id,
        summary=f"Retrait du rôle {role.name if role else role_id} à {target_user.fullName if target_user else target_user_id}",
    )
    await db.commit()


async def list_user_role_assignments(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[dict]:
    """Une ligne par ATTRIBUTION (pas par rôle) — un même rôle peut apparaître
    plusieurs fois avec des portées différentes (ex. gérant sur 2 stations)."""
    stmt = (
        select(UserRole, Role)
        .join(Role, Role.id == UserRole.roleId)
        .where(UserRole.userId == user_id, UserRole.organizationId == organization_id)
        .order_by(Role.name)
    )
    result = await db.execute(stmt)
    return [
        {
            "assignmentId": user_role.id,
            "id": role.id,
            "organizationId": role.organizationId,
            "code": role.code,
            "name": role.name,
            "resourceType": user_role.resourceType,
            "resourceId": user_role.resourceId,
        }
        for user_role, role in result.all()
    ]


# ---------------------------------------------------------------------------
# Grants individuels (allow/deny), délégation, révocation en cascade
# ---------------------------------------------------------------------------


async def create_grant(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    permission_code: str,
    effect: str,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    valid_until: datetime | None = None,
    audit_note: str | None = None,
    delegated_from_grant_id: uuid.UUID | None = None,
) -> UserPermissionGrant:
    """Grant/deny individuel — §5.3/5.5/5.6 du document d'architecture. Un
    `effect="allow"` (direct ou délégué) est toujours borné par la
    non-élévation de privilège du granter ; un `effect="deny"` ne l'est pas
    (refuser un droit à quelqu'un ne peut jamais constituer une élévation de
    privilège)."""
    if effect not in ("allow", "deny"):
        raise AppError(code="invalid_grant_effect", message="effect doit être 'allow' ou 'deny'.", status_code=400)

    permission = await _get_permission_or_404(db, permission_code)

    origin = "direct"
    if delegated_from_grant_id is not None:
        origin_grant = await db.get(UserPermissionGrant, delegated_from_grant_id)
        if origin_grant is None or origin_grant.userId != granter_user_id or origin_grant.revokedAt is not None:
            raise AppError(
                code="invalid_delegation_source",
                message="Le grant d'origine de la délégation est introuvable, révoqué, ou ne vous appartient pas.",
                status_code=403,
            )
        origin = "delegation"

    if effect == "allow":
        if not await user_has_permission(db, granter_user_id, organization_id, permission_code, resource_type, resource_id):
            raise AppError(
                code="privilege_escalation_denied",
                message=f"Vous ne pouvez pas accorder une permission que vous ne possédez pas vous-même sur cette portée : {permission_code}.",
                status_code=403,
            )

    grant = UserPermissionGrant(
        organizationId=organization_id,
        userId=target_user_id,
        permissionId=permission.id,
        effect=effect,
        resourceType=resource_type,
        resourceId=resource_id,
        origin=origin,
        delegatedFromGrantId=delegated_from_grant_id,
        grantedByUserId=granter_user_id,
        validFrom=datetime.now(timezone.utc),
        validUntil=valid_until,
        auditNote=audit_note,
    )
    db.add(grant)
    await db.flush()

    target_user = await db.get(User, target_user_id)
    verb = "Refus" if effect == "deny" else "Octroi"
    scope_label = f" (portée : {resource_type}={resource_id})" if resource_type else ""
    await record_audit_event(
        db,
        organization_id,
        granter_user_id,
        action="rbac.grant.create",
        entity_type="UserPermissionGrant",
        entity_id=grant.id,
        summary=f"{verb} de {permission_code} à {target_user.fullName if target_user else target_user_id}{scope_label}",
        scope_resource_type=resource_type,
        scope_resource_id=resource_id,
    )
    await db.commit()
    await db.refresh(grant)
    return grant


async def revoke_grant(db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, grant_id: uuid.UUID) -> None:
    """Révocation avec cascade immédiate — §5.6 : si ce grant a servi de
    source à des délégations, elles sont révoquées avec lui, récursivement."""
    grant = await db.get(UserPermissionGrant, grant_id)
    if grant is None or grant.organizationId != organization_id:
        raise AppError(code="grant_not_found", message="Grant introuvable.", status_code=404)

    now = datetime.now(timezone.utc)
    to_revoke = [grant]
    frontier = [grant.id]
    while frontier:
        result = await db.execute(
            select(UserPermissionGrant).where(
                UserPermissionGrant.delegatedFromGrantId.in_(frontier), UserPermissionGrant.revokedAt.is_(None)
            )
        )
        children = list(result.scalars().all())
        to_revoke.extend(children)
        frontier = [c.id for c in children]

    for g in to_revoke:
        g.revokedAt = now

    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="rbac.grant.revoke",
        entity_type="UserPermissionGrant",
        entity_id=grant.id,
        summary=f"Révocation d'un grant ({len(to_revoke)} grant(s) affecté(s) avec la cascade de délégation)",
    )
    await db.commit()


async def list_user_grants(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[UserPermissionGrant]:
    result = await db.execute(
        select(UserPermissionGrant)
        .where(UserPermissionGrant.organizationId == organization_id, UserPermissionGrant.userId == user_id)
        .order_by(UserPermissionGrant.createdAt.desc())
    )
    return list(result.scalars().all())


async def list_organization_members_with_roles(db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
    """Pour la page globale Utilisateurs (§14.1) — un utilisateur + ses rôles
    dans CETTE organisation (un même User peut avoir des rôles différents
    selon l'organisation, cf. UserRole scopé)."""
    stmt = select(User).join(OrganizationUser, OrganizationUser.userId == User.id).where(
        OrganizationUser.organizationId == organization_id
    ).order_by(User.fullName)
    users = list((await db.execute(stmt)).scalars().all())

    members: list[dict] = []
    for user in users:
        roles = await list_user_role_assignments(db, organization_id, user.id)
        members.append(
            {
                "userId": user.id,
                "email": user.email,
                "fullName": user.fullName,
                "status": user.status,
                "roles": roles,
            }
        )
    return members


async def list_visible_resource_ids(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, permission_code: str, resource_type: str
) -> tuple[bool, set[uuid.UUID]]:
    """Pour filtrer une LISTE (pas un accès à une ressource précise) : que
    doit voir cet utilisateur pour ce code de permission sur ce type de
    ressource ? Retourne (voit_tout, ensemble_d_ids_visibles) — réutilise
    exactement le même moteur de résolution que `user_has_permission`,
    jamais un filtrage ad hoc séparé (même principe que `_audit_visibility`,
    généralisé ici pour tout module). Un gérant dont le rôle n'est attribué
    que sur SA station (`UserRole.resourceType="station"`) ne verra ainsi
    que cette station dans une liste, sans qu'aucune requête ne l'exclue
    explicitement — c'est la résolution normale qui le détermine."""
    if await user_has_permission(db, user_id, organization_id, permission_code):
        return True, set()

    candidate_ids: set[uuid.UUID] = set()
    role_grants = await _role_permission_grants(db, user_id, organization_id)
    for code, r_type, r_id in role_grants:
        if code == permission_code and r_type == resource_type and r_id is not None:
            candidate_ids.add(r_id)
    grants = await _applicable_grants(db, user_id, organization_id, permission_code)
    for g in grants:
        if g.effect == "allow" and g.resourceType == resource_type and g.resourceId is not None:
            candidate_ids.add(g.resourceId)

    visible: set[uuid.UUID] = set()
    for rid in candidate_ids:
        if await user_has_permission(db, user_id, organization_id, permission_code, resource_type, rid):
            visible.add(rid)
    return False, visible


async def list_effective_permission_codes(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    """Permissions effectives de l'utilisateur, **dans n'importe quelle
    portée** (organisation entière OU une ressource précise, ex. un gérant
    limité à sa station) — utilisé par le frontend (`GET
    /rbac/organizations/{id}/me/permissions`) pour conditionner l'affichage
    (menu, actions) ; ne remplace jamais la vérification serveur sur chaque
    endpoint, qui reste seule responsable d'appliquer la portée exacte (§20
    du document d'architecture : jamais une sécurité uniquement côté
    interface).

    Corrigé — utilisait auparavant `user_has_permission` sans portée
    (équivalent à une exigence "organisation entière"), ce qui faisait
    disparaître silencieusement du menu toute fonctionnalité d'un
    utilisateur scopé à une seule station (gérant, pompiste...), alors
    qu'il y a bel et bien accès sur sa station — découvert en testant un
    scénario de démo réel avec des rôles scopés (mission
    « vente-maintenant-reglementation »). Les grants individuels `deny` ne
    sont pas pris en compte ici (liste purement indicative pour l'affichage,
    jamais une décision d'autorisation) — un deny reste appliqué par
    `user_has_permission` sur chaque endpoint réel."""
    role_grants = await _role_permission_grants(db, user_id, organization_id)
    codes = {code for code, _resource_type, _resource_id in role_grants}
    grant_codes = list((await db.execute(
        select(Permission.code)
        .join(UserPermissionGrant, UserPermissionGrant.permissionId == Permission.id)
        .where(
            UserPermissionGrant.userId == user_id,
            UserPermissionGrant.organizationId == organization_id,
            UserPermissionGrant.effect == "allow",
            UserPermissionGrant.revokedAt.is_(None),
        )
    )).scalars().all())
    codes.update(grant_codes)
    return sorted(codes)
