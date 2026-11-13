"""Routes des jobs d'import et d'export (BE-213), montées sous `/api/v1/jobs`.

Toutes les routes exigent une session et l'en-tête `X-Organization-Id` (organisation courante),
puis la permission du type du job (app/jobs/service.py) avant toute lecture ou écriture.

- `POST ""` : demande de job, 201 (200 si la clé d'idempotence existe déjà) ;
- `GET "/{job_id}"` : état du job, sans contenu ;
- `POST "/{job_id}/cancel"` : annulation d'un job non terminé ;
- `GET "/{job_id}/download"` : contenu du fichier produit (`application/json`).
"""

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.jobs import service
from app.jobs.models import Job
from app.jobs.schemas import CreateJobRequest, JobResponse
from app.rbac.guards import get_current_organization_id

router = APIRouter()


def _reponse(job: Job) -> JobResponse:
    return JobResponse(
        jobId=job.jobId,
        type=job.type,
        state=service.etat_affiche(job),
        manifestSchemaVersion=job.manifestSchemaVersion,
        expiresAt=job.expiresAt,
        createdAt=job.createdAt,
    )


@router.post("", status_code=201, response_model=JobResponse, summary="Demander un job d'import ou d'export")
async def creer_job(
    corps: CreateJobRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Met le job en file. 403 sans la permission du type ; une clé déjà utilisée renvoie le job existant."""
    job, cree = await service.creer_job(db, organization_id, current_user.id, corps)
    if not cree:
        response.status_code = 200
    return _reponse(job)


@router.get("/{job_id}", response_model=JobResponse, summary="État d'un job")
async def lire_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """État du job du tenant courant ; 404 pour un job d'un autre tenant."""
    job = await service.lire_job(db, organization_id, current_user.id, job_id)
    return _reponse(job)


@router.post("/{job_id}/cancel", response_model=JobResponse, summary="Annuler un job")
async def annuler_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Annule un job `queued` ou `running` ; 409 pour un job déjà terminé."""
    job = await service.annuler_job(db, organization_id, current_user.id, job_id)
    return _reponse(job)


@router.get("/{job_id}/download", summary="Télécharger le fichier d'un job")
async def telecharger_job(
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Contenu du fichier ; 409 `DOCUMENT_NOT_READY` tant qu'il n'est pas prêt, 404 `EXPORT_EXPIRED` une fois expiré."""
    job, contenu = await service.telecharger_job(db, organization_id, current_user.id, job_id)
    return Response(
        content=contenu,
        media_type=service.MEDIA_TYPE_FICHIER,
        headers={"Content-Disposition": f'attachment; filename="job-{job.jobId}.json"'},
    )
