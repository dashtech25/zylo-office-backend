import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent, AuditLog
from app.audit.permissions import AUDIT_LOG_VIEW
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.rbac.models import Permission, UserPermissionGrant

# Import différé (pas au niveau module) : `app.rbac.service` importe
# `record_audit_event` de ce même fichier pour journaliser les actions
# rbac (attribution de rôle, grant...) — un import au niveau module créerait
# un cycle d'import (audit.service -> rbac.service -> audit.service).

RESULTATS_AUDIT = ("success", "refused", "error")
TYPES_ACTEUR_AUDIT = ("humain", "service", "systeme")

# Clés dont la valeur ne doit jamais être stockée dans `changes` (BE-007 CA-4).
# Le motif couvre les variantes courantes (password, newPassword, accessToken,
# refresh_token, client_secret, hashedPassword, mot de passe…). Une clé qui
# correspond est remplacée par REDACTION, sans effacer la clé elle-même : on
# sait qu'une valeur existait, sans jamais la journaliser.
_CLE_SENSIBLE = re.compile(r"password|passwd|secret|token|hash|cookie|api[_-]?key|mot_?de_?passe", re.IGNORECASE)
REDACTION = "[masqué]"


def _retirer_secrets(valeur: Any) -> Any:
    """Parcourt récursivement `changes` et remplace la valeur de toute clé
    sensible par REDACTION.

    Les listes et dictionnaires imbriqués sont traités de la même façon. Le
    parcours ne modifie pas l'objet d'origine : il retourne une copie, pour que
    l'appelant conserve ses données intactes après l'écriture."""
    if isinstance(valeur, dict):
        return {
            cle: (REDACTION if _CLE_SENSIBLE.search(str(cle)) else _retirer_secrets(sous_valeur))
            for cle, sous_valeur in valeur.items()
        }
    if isinstance(valeur, list):
        return [_retirer_secrets(element) for element in valeur]
    return valeur


async def record_audit_event(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    changes: dict | None = None,
    scope_resource_type: str | None = None,
    scope_resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    *,
    result: str = "success",
    actor_type: str = "humain",
    reason: str | None = None,
    approval_id: str | None = None,
    visibility: str | None = None,
    data_classification: str | None = None,
) -> AuditEvent:
    """Écrit exactement une entrée dans la table unique `audit_event` (BE-007).

    Règles de l'écriture :
    - un acteur et une organisation sont obligatoires ; sinon AppError
      `audit_invalid_write` est levée et aucune ligne n'est ajoutée (CA-3) ;
    - le request ID est repris de la contextvar `request_id_ctx`, posée par
      `RequestIdMiddleware`. Hors requête HTTP (tâche de fond, script), un
      identifiant `sans-requete-<uuid>` est généré pour que la colonne reste
      obligatoire (CA-2) ;
    - `changes` est copié et ses valeurs sensibles sont masquées avant
      l'écriture (CA-4) : mot de passe, jeton, secret, condensat, cookie ;
    - `eventId` est un UUID nouveau, distinct de la clé primaire (unicité
      métier, colonne `eventId`) ;
    - `result` vaut `success`, `refused` ou `error` ; `actor_type` vaut
      `humain`, `service` ou `systeme`. Toute autre valeur est refusée.

    N'effectue volontairement PAS son propre `commit()` : l'appelant l'inclut
    dans la même transaction que l'action métier journalisée, pour qu'un audit
    ne soit jamais enregistré si l'action a échoué, et inversement.

    Le paramètre `organization_id` isole l'entrée : elle n'est jamais écrite
    sous une autre organisation que celle qui est passée (CA-5).

    Les paramètres positionnels existants sont inchangés ; `result`,
    `actor_type`, `reason`, `approval_id`, `visibility`, `data_classification`
    sont keyword-only et optionnels."""
    if organization_id is None:
        raise AppError(
            code="audit_invalid_write",
            message="Écriture d'audit refusée : organisation absente.",
            status_code=500,
        )
    if actor_user_id is None:
        raise AppError(
            code="audit_invalid_write",
            message="Écriture d'audit refusée : acteur absent.",
            status_code=500,
        )
    if result not in RESULTATS_AUDIT:
        raise AppError(
            code="audit_invalid_write",
            message=f"Résultat d'audit inconnu : {result!r}.",
            status_code=500,
        )
    if actor_type not in TYPES_ACTEUR_AUDIT:
        raise AppError(
            code="audit_invalid_write",
            message=f"Type d'acteur d'audit inconnu : {actor_type!r}.",
            status_code=500,
        )

    request_id = request_id_ctx.get() or f"sans-requete-{uuid.uuid4()}"
    entry = AuditEvent(
        organizationId=organization_id,
        actorUserId=actor_user_id,
        action=action,
        entityType=entity_type,
        entityId=entity_id,
        scopeResourceType=scope_resource_type,
        scopeResourceId=scope_resource_id,
        summary=summary,
        changes=_retirer_secrets(changes) if changes is not None else None,
        ipAddress=ip_address,
        userAgent=user_agent,
        request_id=request_id,
        result=result,
        eventId=str(uuid.uuid4()),
        actorType=actor_type,
        reason=reason,
        approvalId=approval_id,
        schemaVersion=1,
        visibility=visibility,
        dataClassification=data_classification,
    )
    db.add(entry)
    await db.flush()
    return entry


async def record_sensitive_action(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    justification: str | None,
    changes: dict | None = None,
    scope_resource_type: str | None = None,
    scope_resource_id: uuid.UUID | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    *,
    approval_id: str | None = None,
) -> AuditEvent:
    """Journalise une action sensible (BE-260) : exactement une ligne `audit_event`,
    écrite dans la transaction de l'action (appelant responsable du commit).

    Contrat :
    - `justification` est obligatoire : absente, vide ou blanche, l'action est
      refusée par `AppError` `justification_requise` (HTTP 422) AVANT toute
      écriture, donc sans ligne (CA-2). Le motif est gardé sans transformation
      au-delà de la suppression des espaces de bord ;
    - le motif est stocké dans la colonne `reason` de BE-007 (BE-260 n'ajoute
      aucune colonne, QE-FON-15) ;
    - le résultat est toujours `success` : une action refusée ou en erreur se
      journalise avec `record_audit_event(result=...)`, pas ici ;
    - la validation des autres paramètres (organisation, acteur) reste celle de
      `record_audit_event`, appelée ensuite.

    Piège évité : vérifier la justification avant `record_audit_event` garantit
    qu'aucune entrée partielle ne peut exister pour une action sans motif."""
    motif = (justification or "").strip()
    if not motif:
        raise AppError(
            code="justification_requise",
            message="Action sensible refusée : une justification est obligatoire.",
            status_code=422,
        )
    return await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action,
        entity_type,
        entity_id,
        summary,
        changes=changes,
        scope_resource_type=scope_resource_type,
        scope_resource_id=scope_resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        reason=motif,
        approval_id=approval_id,
    )


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
