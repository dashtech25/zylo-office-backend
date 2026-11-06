"""Jobs d'import et d'export d'un tenant (BE-213).

Contrat, dans cet ordre, pour chaque route (app/jobs/router.py) :
1. Isolation : le job est cherché dans le tenant de l'organisation courante. Absent ou d'un autre
   tenant : 404 `job_not_found` (CA-1). Le tenant est lu depuis `organization.tenantId`.
2. Permission du type du job (`verifier_permission`) : sans elle, 403 `permission_denied` (CA-4).
   Vérifiée à chaque lecture et à chaque téléchargement, pas seulement à la création.
3. État : fichier expiré -> 404 `EXPORT_EXPIRED` (CA-3) ; fichier non prêt -> 409
   `DOCUMENT_NOT_READY` (CA-6).

Création : la clé `idempotencyKey` est unique par tenant. Un doublon avec le même type renvoie
le job existant sans rien créer (CA-2) ; un doublon avec un autre type ou une autre version de
manifeste renvoie 409 `idempotency_key_reused`, pour qu'un import différent ne soit jamais
ignoré en silence.

Le job est seulement mis en file (`queued`). Le traitement est fait par app/jobs/worker.py
(`traiter_job`). Aucun déclencheur périodique ou à la demande n'est branché ici.

Échéance : `DUREE_FICHIER_SECONDES` (QE-API-18 NON TRANCHÉ, recommandation appliquée : 24 h).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.identity.models import Organization
from app.jobs.models import ETAT_CANCELLED, ETAT_EXPIRED, ETAT_QUEUED, ETAT_RUNNING, ETAT_SUCCEEDED, Job
from app.jobs.permissions import PERMISSION_PAR_TYPE
from app.jobs.schemas import CreateJobRequest
from app.rbac.service import user_has_permission
from app.shared.storage import StorageError, get_storage_backend

DUREE_FICHIER_SECONDES = 24 * 60 * 60
MEDIA_TYPE_FICHIER = "application/json"

logger = logging.getLogger(__name__)


async def tenant_de_organisation(db: AsyncSession, organization_id: uuid.UUID) -> uuid.UUID:
    """Tenant racine de l'organisation courante. Une organisation sans tenant ne peut pas avoir de job."""
    tenant_id = await db.scalar(select(Organization.tenantId).where(Organization.id == organization_id))
    if tenant_id is None:
        raise AppError(code="organisation_sans_tenant", message="Organisation sans tenant rattaché.", status_code=422)
    return tenant_id


async def verifier_permission(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, type_job: str) -> None:
    """Refuse sans la permission du type du job (CA-4). Le rôle d'un autre type ne suffit pas."""
    permission = PERMISSION_PAR_TYPE[type_job]
    if await user_has_permission(db, user_id, organization_id, permission):
        return
    raise AppError(code="permission_denied", message=f"Permission manquante : {permission}.", status_code=403)


def est_expire(job: Job, maintenant: datetime | None = None) -> bool:
    """Vrai si le job est marqué `expired`, ou s'il est `succeeded` et que son échéance est atteinte."""
    if job.state == ETAT_EXPIRED:
        return True
    reference = maintenant or datetime.now(timezone.utc)
    return job.state == ETAT_SUCCEEDED and job.expiresAt is not None and job.expiresAt <= reference


def etat_affiche(job: Job) -> str:
    """État présenté à l'API : `expired` dès que l'échéance est passée, même avant la purge."""
    return ETAT_EXPIRED if est_expire(job) else job.state


async def _job_par_cle(db: AsyncSession, tenant_id: uuid.UUID, cle: str) -> Job | None:
    return await db.scalar(select(Job).where(Job.tenantId == tenant_id, Job.idempotencyKey == cle))


def _verifier_meme_demande(existant: Job, corps: CreateJobRequest) -> None:
    if existant.type != corps.type or existant.manifestSchemaVersion != corps.manifestSchemaVersion:
        raise AppError(
            code="idempotency_key_reused",
            message="Cette clé d'idempotence a déjà servi à une autre demande de job.",
            status_code=409,
        )


async def creer_job(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, corps: CreateJobRequest
) -> tuple[Job, bool]:
    """Crée le job en `queued`, ou renvoie le job existant de même clé. Renvoie (job, créé)."""
    await verifier_permission(db, organization_id, user_id, corps.type)
    tenant_id = await tenant_de_organisation(db, organization_id)

    existant = await _job_par_cle(db, tenant_id, corps.idempotencyKey)
    if existant is not None:
        _verifier_meme_demande(existant, corps)
        return existant, False

    job = Job(
        tenantId=tenant_id,
        actorId=user_id,
        type=corps.type,
        manifestSchemaVersion=corps.manifestSchemaVersion,
        state=ETAT_QUEUED,
        idempotencyKey=corps.idempotencyKey,
    )
    try:
        # Savepoint : une course sur la même clé fait échouer seulement cette insertion.
        async with db.begin_nested():
            db.add(job)
            await db.flush()
    except IntegrityError:
        existant = await _job_par_cle(db, tenant_id, corps.idempotencyKey)
        if existant is None:
            raise
        _verifier_meme_demande(existant, corps)
        return existant, False
    await db.commit()
    return job, True


async def lire_job(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Job du tenant courant, avec sa permission. 404 pour un job absent ou d'un autre tenant (CA-1)."""
    tenant_id = await tenant_de_organisation(db, organization_id)
    job = await db.scalar(select(Job).where(Job.jobId == job_id, Job.tenantId == tenant_id))
    if job is None:
        raise AppError(code="job_not_found", message="Job introuvable.", status_code=404)
    await verifier_permission(db, organization_id, user_id, job.type)
    return job


async def annuler_job(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    """Annule un job non terminé (`queued` ou `running`). Le worker relit l'état et s'arrête."""
    job = await lire_job(db, organization_id, user_id, job_id)
    if job.state not in (ETAT_QUEUED, ETAT_RUNNING):
        raise AppError(code="job_not_cancellable", message="Ce job ne peut plus être annulé.", status_code=409)
    job.state = ETAT_CANCELLED
    await db.commit()
    return job


async def telecharger_job(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Job, bytes]:
    """Contenu du fichier produit. 404 `EXPORT_EXPIRED` une fois l'échéance passée (CA-3),
    409 `DOCUMENT_NOT_READY` tant que le job n'est pas `succeeded` (CA-6).

    Un job `succeeded` dont le fichier est absent du stockage renvoie un corps vide (200) et
    journalise un avertissement. Cas à trancher : voir le rapport de la tâche."""
    job = await lire_job(db, organization_id, user_id, job_id)
    if est_expire(job):
        raise AppError(code="EXPORT_EXPIRED", message="Le fichier de ce job a expiré.", status_code=404)
    if job.state != ETAT_SUCCEEDED:
        raise AppError(code="DOCUMENT_NOT_READY", message="Le fichier n'est pas encore prêt.", status_code=409)
    return job, _lire_fichier(job, organization_id)


def _lire_fichier(job: Job, organization_id: uuid.UUID) -> bytes:
    if not job.filePointer:
        logger.warning("job %s succeeded sans filePointer", job.jobId)
        return b""
    try:
        return get_storage_backend().read(job.filePointer)
    except StorageError:
        logger.warning("job %s : fichier absent du stockage (organisation %s)", job.jobId, organization_id)
        return b""


def echeance_fichier(maintenant: datetime) -> datetime:
    """Échéance d'un fichier produit à `maintenant` (voir DUREE_FICHIER_SECONDES)."""
    return maintenant + timedelta(seconds=DUREE_FICHIER_SECONDES)
