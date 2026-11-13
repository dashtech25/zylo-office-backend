import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import consultation, export_job, service
from app.audit.permissions import AUDIT_EXPORT
from app.audit.schemas import AuditEvenementResponse, AuditLogResponse, ExportAuditCreate, ExportAuditResponse
from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.identity.service import require_organization_member
from app.rbac.guards import get_current_organization_id
from app.rbac.service import require_permission
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


def _reponse_job(job, lien_actif: bool = True) -> ExportAuditResponse:
    """Sérialise un job ; le lien de téléchargement n'existe que tant que le job n'est pas expiré."""
    lien = f"/api/v1/audit/exports/{job.id}/telechargement" if lien_actif else None
    return ExportAuditResponse(
        id=job.id,
        sujet=job.sujet,
        dateDebut=job.periode["dateDebut"],
        dateFin=job.periode["dateFin"],
        motif=job.motif,
        statut=export_job.statut_du_job(job),
        creeAt=job.creeAt,
        expireAt=job.expireAt,
        lienTelechargement=lien,
    )


@router.post(
    "/exports",
    response_model=ExportAuditResponse,
    status_code=201,
    dependencies=[Depends(require_permission(AUDIT_EXPORT))],
    summary="Demander un export du journal d'audit (BE-173)",
)
async def demander_export(
    payload: ExportAuditCreate,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExportAuditResponse:
    """Crée un job d'export (BE-173). Motif obligatoire (422), permission `audit.export` (403),
    durée de rétention configurée (503). La logique est dans app/audit/export_job.py."""
    job = await export_job.demander_export(
        db, organization_id, current_user.id, payload.sujet, payload.dateDebut, payload.dateFin, payload.motif
    )
    return _reponse_job(job)


@router.get(
    "/exports/{job_id}",
    response_model=ExportAuditResponse,
    dependencies=[Depends(require_permission(AUDIT_EXPORT))],
    summary="Statut d'un export du journal d'audit (BE-173)",
)
async def statut_export(
    job_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ExportAuditResponse:
    """Statut et lien de téléchargement temporaire. 404 hors tenant (CA-5)."""
    job = await export_job.obtenir_job(db, organization_id, job_id)
    return _reponse_job(job, lien_actif=not export_job.est_expire(job))


@router.get(
    "/exports/{job_id}/telechargement",
    dependencies=[Depends(require_permission(AUDIT_EXPORT))],
    summary="Contenu d'un export du journal d'audit (BE-173, 410 une fois expiré)",
)
async def telecharger_export(
    job_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Événements du job, limités aux champs autorisés (CA-4). 410 une fois expiré (CA-2)."""
    contenu = await export_job.contenu_export(db, organization_id, job_id)
    return {"data": contenu}


@router.get(
    "/evenements",
    response_model=Page[AuditEvenementResponse],
    summary="Rechercher des événements d'audit (BE-172)",
)
async def rechercher_evenements(
    dateDebut: datetime = Query(..., description="Début de période (obligatoire, borne incluse)."),
    dateFin: datetime = Query(..., description="Fin de période (obligatoire, borne incluse)."),
    sujetType: str = Query(..., min_length=1, description="Type de sujet, valeur de `entityType` (obligatoire)."),
    sujetId: uuid.UUID | None = Query(None, description="Identifiant du sujet, valeur de `entityId` (facultatif)."),
    acteurId: uuid.UUID | None = Query(None, description="Acteur, valeur de `actorUserId` (facultatif)."),
    action: str | None = Query(None, description="Action exacte, par exemple `zyloLiquid.price.update` (facultatif)."),
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Recherche dans le journal `audit_event` de l'organisation courante (BE-172).

    Organisation : en-tête `X-Organization-Id`, validé par l'appartenance active.
    Filtres obligatoires : période (`dateDebut`, `dateFin`) et sujet (`sujetType`) ;
    sans l'un d'eux la réponse est 422 et rien n'est lu (CA-1). Filtres facultatifs :
    `sujetId`, `acteurId`, `action`, cumulables avec la restriction de portée.
    Réponse : acteur, cible, action, motif, temps, résultat, corrélation et
    visibilité (CA-2). Droit `audit.log.view` : sans lui, 403 (CA-3).
    Les événements à visibilité restreinte sont retirés sans la permission
    `audit.restricted.view` (voir app/audit/consultation.py).
    Pagination : `limit`, `offset`."""
    rows, total = await consultation.rechercher_evenements(
        db, organization_id, current_user.id, dateDebut, dateFin, sujetType, sujetId, acteurId, action,
        pagination.limit, pagination.offset,
    )
    return Page(
        data=[AuditEvenementResponse.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )


ACTION_LECTURE_JOURNAL = "audit.journal.consulte"


@router.get(
    "/records",
    response_model=Page[AuditEvenementResponse],
    summary="Lire le journal d'audit de l'organisation courante (BE-184)",
)
async def lister_records(
    dateDebut: datetime = Query(..., description="Début de période (obligatoire, borne incluse)."),
    dateFin: datetime = Query(..., description="Fin de période (obligatoire, borne incluse)."),
    sujetType: str = Query(..., min_length=1, description="Type de sujet, valeur de `entityType` (obligatoire)."),
    sujetId: uuid.UUID | None = Query(None, description="Identifiant du sujet, valeur de `entityId` (facultatif)."),
    acteurId: uuid.UUID | None = Query(None, description="Acteur, valeur de `actorUserId` (facultatif)."),
    action: str | None = Query(None, description="Action exacte (facultatif)."),
    pagination: PaginationParams = Depends(),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page:
    """Lecture du journal `audit_event` de l'organisation courante (BE-184).

    Mêmes filtres et mêmes règles de droits que `GET /audit/evenements` (BE-172) :
    `audit.log.view` (CA-2, 403), isolation tenant (CA-3, 404 pour un tenant qui n'est
    pas celui de l'en-tête validé). Chaque lecture réussie écrit elle-même une entrée
    `audit.journal.consulte` dans la même organisation, puis commit (CA-5) : la lecture
    échoue si son entrée ne peut être écrite (fail-closed, sans lecture sans trace).
    L'entrée de lecture n'apparaît pas dans la page renvoyée, qui est calculée avant."""
    rows, total = await consultation.rechercher_evenements(
        db, organization_id, current_user.id, dateDebut, dateFin, sujetType, sujetId, acteurId, action,
        pagination.limit, pagination.offset,
    )
    page = Page(
        data=[AuditEvenementResponse.model_validate(row) for row in rows],
        meta=PageMeta(total=total, limit=pagination.limit, offset=pagination.offset),
    )
    await service.record_audit_event(
        db,
        organization_id,
        current_user.id,
        ACTION_LECTURE_JOURNAL,
        "audit_event",
        None,
        "Consultation du journal d'audit",
        changes={"sujetType": sujetType, "dateDebut": dateDebut.isoformat(), "dateFin": dateFin.isoformat()},
    )
    await db.commit()
    return page


@router.get(
    "/evenements/{event_id}",
    response_model=AuditEvenementResponse,
    summary="Détail d'un événement d'audit (BE-172)",
)
async def detail_evenement(
    event_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditEvenementResponse:
    """Détail d'un événement de l'organisation courante (BE-172 CA-4, CA-5).

    404 `audit_event_not_found` si l'identifiant n'existe pas dans cette
    organisation, y compris s'il appartient à un autre tenant. 403
    `permission_denied` si l'événement est à visibilité restreinte et que
    l'appelant n'a pas `audit.restricted.view`. Lecture seule."""
    evenement = await consultation.obtenir_evenement(db, organization_id, current_user.id, event_id)
    return AuditEvenementResponse.model_validate(evenement)


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
