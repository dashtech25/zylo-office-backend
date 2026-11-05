"""Consultation du journal d'audit par recherche et par détail (BE-172).

Rôle : lire la table unique `audit_event` (BE-007) pour les routes
`GET /api/v1/audit/evenements` (recherche) et
`GET /api/v1/audit/evenements/{event_id}` (détail). Aucune table, aucune écriture :
ce module ne fait que lire ce que `record_audit_event` (BE-007) et les écritures
BE-152 / BE-153 ont déjà produit.

Règles de droits (ordre d'évaluation, identique à la liste BE-033) :
1. Permission `audit.log.view` (`AUDIT_LOG_VIEW`) : sans elle et sans portée
   visible, 403 `permission_denied`, rien n'est lu. Un administrateur de
   l'organisation voit tout ; un gérant limité à une portée ne voit que les
   événements de ses portées (même restriction que `list_audit_logs`).
2. Isolation tenant : toute requête filtre sur `organizationId`. Un identifiant
   d'un autre tenant donne 404 (`audit_event_not_found`), jamais 403, pour ne
   pas révéler qu'il existe.
3. Visibilité restreinte : un événement dont `visibility` vaut
   `VISIBILITE_RESTREINTE` exige en plus `PERMISSION_RESTREINTE`.
   - détail : sans elle, 403 `permission_denied` (CA-4) ;
   - recherche : ces événements sont retirés de la page, sans compter ni
     révéler leur présence (un 403 global casserait la lecture du reste).

Filtres de recherche (définition BE-172, recommandation QE-PAR-02) :
- `dateDebut` et `dateFin` obligatoires (bornes incluses sur `createdAt`) ;
  `dateFin` antérieure à `dateDebut` : 422 ;
- `sujetType` obligatoire (`entityType`), `sujetId` optionnel (`entityId`) ;
- `acteurId` (`actorUserId`) et `action` (égalité exacte), optionnels.

Hypothèses signalées (NON DÉFINI dans la source) :
- QE-PAR-16 : valeur de visibilité restreinte `"restreinte"` et permission
  `audit.restricted.view` (`app/audit/permissions.py`) ;
- la définition cite `audit.read` ; le code existant (BE-033, BE-260) porte
  `audit.log.view`. On réutilise celui-ci : aucune permission en double.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.permissions import AUDIT_LOG_VIEW, AUDIT_RESTRICTED_VIEW, VISIBILITE_RESTREINTE
from app.audit.service import _audit_visibility
from app.core.errors import AppError
from app.rbac.service import user_has_permission


async def _peut_voir_restreint(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur détient la permission de visibilité restreinte (QE-PAR-16)."""
    return await user_has_permission(db, user_id, organization_id, AUDIT_RESTRICTED_VIEW)


async def rechercher_evenements(
    db: AsyncSession,
    organization_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    date_debut: datetime,
    date_fin: datetime,
    sujet_type: str,
    sujet_id: uuid.UUID | None,
    acteur_id: uuid.UUID | None,
    action: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AuditEvent], int]:
    """Recherche paginée d'événements d'audit d'une organisation (BE-172 CA-2).

    Ordre des résultats : `createdAt` décroissant. Le total compte les seuls
    événements que l'appelant peut voir (visibilité restreinte exclue sans la
    permission). Lève `AppError` 403 `permission_denied` sans `audit.log.view`
    ni portée visible, et `AppError` 422 si la période est inversée."""
    if date_fin < date_debut:
        raise AppError(code="audit_periode_invalide", message="dateFin doit être postérieure à dateDebut.", status_code=422)

    sees_all, visible_scopes = await _audit_visibility(db, organization_id, requesting_user_id)
    if not sees_all and not visible_scopes:
        raise AppError(code="permission_denied", message=f"Permission manquante : {AUDIT_LOG_VIEW}.", status_code=403)

    stmt = select(AuditEvent).where(
        AuditEvent.organizationId == organization_id,
        AuditEvent.createdAt >= date_debut,
        AuditEvent.createdAt <= date_fin,
        AuditEvent.entityType == sujet_type,
    )
    if sujet_id is not None:
        stmt = stmt.where(AuditEvent.entityId == sujet_id)
    if acteur_id is not None:
        stmt = stmt.where(AuditEvent.actorUserId == acteur_id)
    if action is not None:
        stmt = stmt.where(AuditEvent.action == action)
    if not sees_all:
        # Même restriction de portée que `list_audit_logs` : un gérant ne voit que ses portées.
        stmt = stmt.where(
            _condition_portees(visible_scopes)
        )
    if not await _peut_voir_restreint(db, organization_id, requesting_user_id):
        stmt = stmt.where(AuditEvent.visibility.is_distinct_from(VISIBILITE_RESTREINTE))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.order_by(AuditEvent.createdAt.desc()).limit(limit).offset(offset))
    return list(result.scalars().all()), total or 0


def _condition_portees(portees: set[tuple[str, uuid.UUID]]):
    """Disjonction des couples (type de portée, identifiant de portée) visibles."""
    conditions = [(AuditEvent.scopeResourceType == rtype) & (AuditEvent.scopeResourceId == rid) for rtype, rid in portees]
    combinee = conditions[0]
    for condition in conditions[1:]:
        combinee = combinee | condition
    return combinee


async def obtenir_evenement(db: AsyncSession, organization_id: uuid.UUID, requesting_user_id: uuid.UUID, event_id: uuid.UUID) -> AuditEvent:
    """Détail d'un événement d'audit de l'organisation (BE-172 CA-4, CA-5).

    Lève `AppError` 403 sans `audit.log.view` ni portée visible ; 404
    `audit_event_not_found` si l'identifiant n'existe pas dans cette organisation
    (y compris s'il appartient à un autre tenant, CA-5) ou hors portée de
    l'appelant ; 403 `permission_denied` si l'événement est restreint et que
    l'appelant n'a pas `audit.restricted.view` (CA-4)."""
    sees_all, visible_scopes = await _audit_visibility(db, organization_id, requesting_user_id)
    if not sees_all and not visible_scopes:
        raise AppError(code="permission_denied", message=f"Permission manquante : {AUDIT_LOG_VIEW}.", status_code=403)

    stmt = select(AuditEvent).where(AuditEvent.id == event_id, AuditEvent.organizationId == organization_id)
    if not sees_all:
        stmt = stmt.where(_condition_portees(visible_scopes))
    evenement = (await db.execute(stmt)).scalars().first()
    if evenement is None:
        raise AppError(code="audit_event_not_found", message="Événement d'audit introuvable.", status_code=404)

    if evenement.visibility == VISIBILITE_RESTREINTE and not await _peut_voir_restreint(db, organization_id, requesting_user_id):
        raise AppError(code="permission_denied", message=f"Permission manquante : {AUDIT_RESTRICTED_VIEW}.", status_code=403)
    return evenement
