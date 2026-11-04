import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service
from app.audit.schemas import AuditLogResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.rbac.guards import get_current_organization_id
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta

router = APIRouter()
# Routes de l'organisation courante (BE-033), montées sous `/organizations` :
# `GET /api/v1/organizations/current/audit-logs`. Séparées de `router` (montée
# sous `/audit`) pour garder l'URL de la définition ; même service, même
# filtrage, aucune logique dupliquée.
organization_audit_router = APIRouter()


async def _page_de_journal(
    db: AsyncSession,
    organization_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    pagination: PaginationParams,
    action_prefix: str | None,
    scope_resource_type: str | None,
    scope_resource_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
) -> Page:
    """Pagination et sérialisation communes aux deux routes de lecture.

    La restriction de portée (§17) est entièrement appliquée par
    `service.list_audit_logs` : cette fonction ne filtre rien elle-même."""
    rows, total = await service.list_audit_logs(
        db, organization_id, requesting_user_id, action_prefix, pagination.limit, pagination.offset,
        scope_resource_type=scope_resource_type, scope_resource_id=scope_resource_id, actor_user_id=actor_user_id,
    )
    return Page(
        data=[AuditLogResponse.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )


@router.get(
    "/organizations/{organization_id}",
    response_model=Page[AuditLogResponse],
    dependencies=[Depends(require_organization_member)],
)
async def list_audit_logs(
    organization_id: uuid.UUID,
    actionPrefix: str | None = None,
    scopeResourceType: str | None = None,
    scopeResourceId: uuid.UUID | None = None,
    actorUserId: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Filtré automatiquement selon la portée que possède l'utilisateur sur
    `audit.log.view` (§17) — un propriétaire voit tout, un gérant de station
    ne voit que les évènements de ses stations autorisées, un utilisateur
    sans la permission reçoit un 403 explicite plutôt qu'une liste vide
    silencieuse. `scopeResourceType`/`scopeResourceId` (Centre administratif
    et opérationnel de la station, domaine « Historique ») filtrent en plus
    sur une entité précise, ex. `station`/<stationId>. `actorUserId` (module
    Personnel, activité récente d'une fiche membre) filtre sur l'auteur —
    jamais un contournement de la restriction de portée ci-dessus."""
    return await _page_de_journal(
        db, organization_id, current_user.id, pagination,
        actionPrefix, scopeResourceType, scopeResourceId, actorUserId,
    )


@organization_audit_router.get(
    "/{organization_id}/audit",
    response_model=Page[AuditLogResponse],
    dependencies=[Depends(require_organization_member)],
    summary="Consulter le journal d'audit d'une organisation (lecture seule, BE-260)",
)
async def list_organization_audit(
    organization_id: uuid.UUID,
    actionPrefix: str | None = None,
    scopeResourceType: str | None = None,
    scopeResourceId: uuid.UUID | None = None,
    actorUserId: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Journal `audit_event` de l'organisation désignée par le chemin (BE-260).

    Route cible de la définition : `GET /api/v1/organizations/{organization_id}/audit`
    (nommage recommandé, NON DÉFINI dans les sources, QE-FON-16).

    Contrat :
    - l'appartenance active à l'organisation du chemin est exigée par
      `require_organization_member` (T-010) ;
    - le droit `audit.log.view` est exigé par `service.list_audit_logs`, qui
      renvoie 403 `permission_denied` sans permission ni portée visible ;
    - aucune ligne d'une autre organisation n'est renvoyée : le filtre
      `organizationId` du service s'applique au chemin ;
    - lecture seule : aucune méthode d'écriture n'est exposée.

    Même logique que `GET /organizations/current/audit-logs` (BE-033) : seul
    le mode de désignation de l'organisation change (chemin au lieu d'en-tête)."""
    return await _page_de_journal(
        db, organization_id, current_user.id, pagination,
        actionPrefix, scopeResourceType, scopeResourceId, actorUserId,
    )


@organization_audit_router.get(
    "/current/audit-logs",
    response_model=Page[AuditLogResponse],
    summary="Consulter le journal d'audit de l'organisation courante (lecture seule)",
)
async def list_current_organization_audit_logs(
    actionPrefix: str | None = None,
    scopeResourceType: str | None = None,
    scopeResourceId: uuid.UUID | None = None,
    actorUserId: uuid.UUID | None = None,
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Journal d'audit (table `audit_event`) de l'organisation courante, BE-033.

    L'organisation vient de l'en-tête `X-Organization-Id`, validé par
    l'appartenance active (`get_current_organization_id`) : l'en-tête n'est
    qu'un sélecteur, jamais une preuve d'accès. Une entrée d'une autre
    organisation n'est jamais renvoyée (isolation, CA-2).

    Droit : `audit.log.view`. Sans ce droit, ou sans portée visible, la
    réponse est 403 `permission_denied` (CA-1), jamais une liste vide. Un
    administrateur d'organisation voit toutes les entrées de l'organisation ;
    une portée (station) restreint la liste aux entrées de cette portée.

    Lecture seule : seule la méthode GET est exposée, PUT, PATCH et DELETE
    renvoient 405 (CA-3). Les entrées ne contiennent jamais de mot de passe
    ni de jeton : le service masque ces clés avant écriture (CA-4).

    Filtres optionnels, cumulables avec la restriction de portée (jamais à sa
    place) : `actionPrefix`, `scopeResourceType`/`scopeResourceId`,
    `actorUserId`. Pagination : `limit`, `offset` (`PaginationParams`)."""
    return await _page_de_journal(
        db, organization_id, current_user.id, pagination,
        actionPrefix, scopeResourceType, scopeResourceId, actorUserId,
    )
