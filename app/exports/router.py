"""Routes de l'export de données (BE-243), montées sous `/api/v1/exports`.

Toutes les routes exigent une session et l'en-tête `X-Organization-Id` (organisation courante),
puis la permission `donnees.export.creer` (app/exports/service.py::verifier_permission) avant
toute lecture ou écriture. Il n'existe pas de lien public : le téléchargement passe par la session.

- `POST ""` : demande d'export, 201 avec le statut du job ;
- `GET "/{export_id}"` : statut, empreinte et expiration (sans contenu) ;
- `GET "/{export_id}/download"` : contenu et empreinte, 410 une fois expiré.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.exports import service
from app.exports.schemas import DemandeExport, ExportStatut, ExportTelechargement
from app.identity.models import User
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def _statut(job) -> ExportStatut:
    return ExportStatut(
        id=job.id,
        statut=service.statut_du_job(job),
        perimetre=job.perimetre,
        empreinte=job.empreinte,
        expireAt=job.expireAt,
        createdAt=job.createdAt,
    )


@router.post("", status_code=201, response_model=ExportStatut, summary="Demander un export de données")
async def demander_export(
    corps: DemandeExport,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ExportStatut:
    """Crée un export du périmètre demandé (tenant ou sujet) ; 403 sans permission (journalisé)."""
    await service.verifier_permission(db, organization_id, current_user.id)
    job = await service.demander_export(
        db, organization_id, current_user.id, corps.perimetre.model_dump(mode="json", exclude_none=True)
    )
    return _statut(job)


@router.get("/{export_id}", response_model=ExportStatut, summary="Statut d'un export")
async def statut_export(
    export_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ExportStatut:
    """Statut du job de l'organisation courante ; 404 pour un job d'un autre tenant."""
    await service.verifier_permission(db, organization_id, current_user.id)
    job = await service.obtenir_job(db, organization_id, export_id)
    return _statut(job)


@router.get("/{export_id}/download", response_model=ExportTelechargement, summary="Télécharger un export")
async def telecharger_export(
    export_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> ExportTelechargement:
    """Contenu et empreinte ; 410 `export_expired` une fois l'échéance passée (contenu purgé)."""
    await service.verifier_permission(db, organization_id, current_user.id)
    job = await service.telecharger(db, organization_id, export_id)
    return ExportTelechargement(id=job.id, empreinte=job.empreinte, contenu=job.contenu)
