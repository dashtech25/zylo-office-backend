import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.audit.permissions import AUDIT_LOG_VIEW
from app.core.errors import AppError
from app.rbac.models import Permission, UserPermissionGrant

# Import différé (pas au niveau module) : `app.rbac.service` importe
# `record_audit_event` de ce même fichier pour journaliser les actions
# rbac (attribution de rôle, grant...) — un import au niveau module créerait
# un cycle d'import (audit.service -> rbac.service -> audit.service).


async def record_audit_event(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    changes: dict | None = None,
    scope_resource_type: str | None = None,
    scope_resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Point d'appel unique pour toute action sensible (§18) — n'effectue
    volontairement PAS son propre `commit()` : l'appelant l'inclut dans la
    même transaction que l'action métier qu'il journalise, pour garantir
    qu'un audit n'est jamais enregistré si l'action elle-même a échoué (et
    inversement)."""
    entry = AuditLog(
        organizationId=organization_id,
        actorUserId=actor_user_id,
        action=action,
        entityType=entity_type,
        entityId=entity_id,
        scopeResourceType=scope_resource_type,
        scopeResourceId=scope_resource_id,
        summary=summary,
        changes=changes,
        ipAddress=ip_address,
        userAgent=user_agent,
    )
    db.add(entry)
    await db.flush()
    return entry


async def _audit_visibility(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> tuple[bool, set[tuple[str, uuid.UUID]]]:
    """Retourne (voit_tout, ensemble_de_portees_visibles) — §17 du document
    d'architecture : réutilise exactement le moteur de résolution des
    permissions, jamais un filtrage ad hoc séparé. Les portées candidates
    viennent aussi bien d'un grant individuel scopé QUE d'un rôle dont
    l'attribution (`UserRole`) est elle-même scopée (ex. un gérant qui reçoit
    `audit.log.view` via son rôle station, pas via un grant direct)."""
    from app.rbac.service import _role_permission_grants, user_has_permission  # import différé, voir en-tête du fichier

    if await user_has_permission(db, user_id, organization_id, AUDIT_LOG_VIEW):
        return True, set()

    candidate_scopes: set[tuple[str, uuid.UUID]] = set()

    role_grants = await _role_permission_grants(db, user_id, organization_id)
    for code, r_type, r_id in role_grants:
        if code == AUDIT_LOG_VIEW and r_type is not None and r_id is not None:
            candidate_scopes.add((r_type, r_id))

    stmt = (
        select(UserPermissionGrant)
        .join(Permission, Permission.id == UserPermissionGrant.permissionId)
        .where(
            UserPermissionGrant.userId == user_id,
            UserPermissionGrant.organizationId == organization_id,
            Permission.code == AUDIT_LOG_VIEW,
            UserPermissionGrant.effect == "allow",
            UserPermissionGrant.resourceType.is_not(None),
        )
    )
    candidate_grants = list((await db.execute(stmt)).scalars().all())
    for grant in candidate_grants:
        candidate_scopes.add((grant.resourceType, grant.resourceId))

    visible_scopes: set[tuple[str, uuid.UUID]] = set()
    for r_type, r_id in candidate_scopes:
        if await user_has_permission(db, user_id, organization_id, AUDIT_LOG_VIEW, r_type, r_id):
            visible_scopes.add((r_type, r_id))

    return False, visible_scopes


async def list_audit_logs(
    db: AsyncSession,
    organization_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    action_prefix: str | None,
    limit: int,
    offset: int,
    scope_resource_type: str | None = None,
    scope_resource_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> tuple[list[AuditLog], int]:
    """`scope_resource_type`/`scope_resource_id` (Centre administratif et
    opérationnel de la station, domaine « Historique ») — filtre additif sur
    la même colonne dénormalisée déjà utilisée pour la visibilité
    (`AuditLog.scopeResourceType/scopeResourceId`), jamais un contournement :
    s'applique EN PLUS de la restriction de portée ci-dessous, jamais à sa
    place (un gérant ne peut pas demander l'historique d'une station qu'il
    ne voit pas). `actor_user_id` (module Personnel, « Activité récente »
    d'une fiche membre) — même principe, filtre additif sur une colonne déjà
    existante (`AuditLog.actorUserId`), jamais un contournement de la
    restriction de portée ci-dessous."""
    sees_all, visible_scopes = await _audit_visibility(db, organization_id, requesting_user_id)
    if not sees_all and not visible_scopes:
        raise AppError(code="permission_denied", message=f"Permission manquante : {AUDIT_LOG_VIEW}.", status_code=403)

    stmt = select(AuditLog).where(AuditLog.organizationId == organization_id)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.like(f"{action_prefix}%"))
    if scope_resource_type is not None:
        stmt = stmt.where(AuditLog.scopeResourceType == scope_resource_type)
    if scope_resource_id is not None:
        stmt = stmt.where(AuditLog.scopeResourceId == scope_resource_id)
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actorUserId == actor_user_id)
    if not sees_all:
        # Un gérant de station ne voit que les évènements scopés à ses
        # stations autorisées — jamais les évènements sans portée (org
        # entière) qui restent réservés à qui a audit.log.view non scopé.
        conditions = [
            (AuditLog.scopeResourceType == rtype) & (AuditLog.scopeResourceId == rid) for rtype, rid in visible_scopes
        ]
        combined = conditions[0]
        for c in conditions[1:]:
            combined = combined | c
        stmt = stmt.where(combined)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(AuditLog.createdAt.desc()).limit(limit).offset(offset))
    return list(result.scalars().all()), total or 0
