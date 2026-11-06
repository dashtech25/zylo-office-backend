"""Routes des exports de données asynchrones du portail (BE-117), montées sous `/api/v1/organizations`.

- `POST /organizations/{organization_id}/exports` : demande, 202 avec `export_requested` ;
- `GET /organizations/{organization_id}/exports/{export}` : statut, lien seulement à `ready` ;
- `GET /organizations/{organization_id}/exports/{export}/download` : contenu journalisé, 409 avant
  `ready`, 410 après `expiresAt`.

Chaque route passe par `exiger_action` (portée `OrgScope`, permission `data.export`, BE-101) avant
toute lecture. Le lien de téléchargement n'est pas public : il exige une session et la permission.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.portail.exports import service
from app.portail.exports.schemas import ExportReponse, ExportTelechargement
from app.portail.exports.service import traiter_export
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

# Actions de la politique du portail ; leur permission est dans POLITIQUE_PORTAIL (rbac/portee_organisation.py).
PORTAIL_EXPORT_DEMANDER = "portail.export.demander"
PORTAIL_EXPORT_LIRE = "portail.export.lire"
PORTAIL_EXPORT_TELECHARGER = "portail.export.telecharger"


def _reponse(job, organization_id: uuid.UUID) -> ExportReponse:
    """Statut présenté : le lien n'existe qu'à l'état `ready`, jamais avant (CA-2)."""
    statut = service.statut_du_job(job)
    lien = (
        f"/api/v1/organizations/{organization_id}/exports/{job.id}/download"
        if statut == service.STATUT_PRET
        else None
    )
    return ExportReponse(
        id=job.id,
        statut=statut,
        perimetre=job.perimetre,
        expiresAt=job.expiresAt,
        lienTelechargement=lien,
        createdAt=job.createdAt,
    )


@router.post(
    "/{organization_id}/exports",
    status_code=202,
    response_model=ExportReponse,
    summary="Demander un export de données (BE-117)",
)
async def demander_export(
    background_tasks: BackgroundTasks,
    scope: OrgScope = Depends(exiger_action(PORTAIL_EXPORT_DEMANDER)),
    db: AsyncSession = Depends(get_db),
) -> ExportReponse:
    """Accepte la demande (202, `export_requested`) et confie le traitement à un traitement de fond."""
    job = await service.demander_export(db, scope.organization_id, scope.user_id)
    background_tasks.add_task(traiter_export, job.id)
    return _reponse(job, scope.organization_id)


@router.get(
    "/{organization_id}/exports/{export}",
    response_model=ExportReponse,
    summary="Statut d'un export de données (BE-117)",
)
async def lire_export(
    export: uuid.UUID,
    scope: OrgScope = Depends(exiger_action(PORTAIL_EXPORT_LIRE)),
    db: AsyncSession = Depends(get_db),
) -> ExportReponse:
    """Statut de l'export de l'organisation du chemin ; 404 pour un export d'une autre organisation."""
    job = await service.obtenir_job(db, scope.organization_id, export)
    return _reponse(job, scope.organization_id)


@router.get(
    "/{organization_id}/exports/{export}/download",
    response_model=ExportTelechargement,
    summary="Télécharger un export de données (BE-117)",
)
async def telecharger_export(
    export: uuid.UUID,
    scope: OrgScope = Depends(exiger_action(PORTAIL_EXPORT_TELECHARGER)),
    db: AsyncSession = Depends(get_db),
) -> ExportTelechargement:
    """Contenu d'un export prêt, journalisé ; 409 `export_not_ready` avant, 410 `export_expired` après."""
    job = await service.telecharger(db, scope.organization_id, scope.user_id, export)
    return ExportTelechargement(
        id=job.id,
        statut=service.statut_du_job(job),
        expiresAt=job.expiresAt,
        contenu=job.contenu or [],
    )
