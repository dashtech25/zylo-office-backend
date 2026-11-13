"""Exports de données asynchrones du portail (BE-117).

Contrat, par route (app/portail/exports/router.py) :
1. Portée et permission : `exiger_action` (401 sans session, 404 hors appartenance, 403 sans
   `data.export`). Ce contrôle précède toute lecture de l'export.
2. Isolation : tout export est cherché dans l'organisation du chemin. Absent ou d'une autre
   organisation : 404 `export_not_found`, réponse identique.
3. État : `export_requested` -> pas de lien ni de contenu (409 au téléchargement) ; `ready` ->
   lien et contenu ; échéance passée -> 410 `export_expired`, contenu purgé (CA-3).

Demande : `demander_export` écrit la ligne et la trace d'audit, commit, puis publie
`ExportRequested`. Le traitement (`traiter_export`) n'est pas fait dans la requête : le router le
confie à un traitement de fond (`BackgroundTasks`). Il ne produit `ready` que si une durée de vie
est configurée (`settings.EXPORT_EXPIRATION_SECONDS`) ; sans valeur, rien n'est produit et aucun
lien n'existe (CA-5). Aucune durée n'est codée ici.

Les événements sont publiés après commit (règle de app/shared/events.py).
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.portail.exports.models import STATUT_EXPIRE, STATUT_PRET, STATUT_REQUETE, PortailExportJob
from app.shared import events as bus

logger = logging.getLogger(__name__)

PERIMETRE_MEMBRES = "membres"
ACTION_DEMANDE = "data.export.request"
ACTION_TELECHARGEMENT = "data.export.download"
EVENEMENT_DEMANDE = "ExportRequested"
EVENEMENT_PRET = "ExportReady"
EVENEMENT_EXPIRE = "ExportExpired"


def maintenant() -> datetime:
    """Horloge du module. Les tests la remplacent pour figer le temps (CA-3)."""
    return datetime.now(timezone.utc)


def est_expire(job: PortailExportJob, instant: datetime | None = None) -> bool:
    """Vrai si l'export est déjà marqué `expired`, ou si `expiresAt` est atteint (borne incluse)."""
    if job.statut == STATUT_EXPIRE:
        return True
    if job.statut != STATUT_PRET or job.expiresAt is None:
        return False
    return job.expiresAt <= (instant or maintenant())


def statut_du_job(job: PortailExportJob) -> str:
    """Statut présenté à l'API : `expired` dès que l'échéance est passée, même avant la purge."""
    return STATUT_EXPIRE if est_expire(job) else job.statut


async def _membres(db: AsyncSession, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    """Enregistrements des membres actifs de l'organisation. Aucun champ secret n'y figure."""
    lignes = (
        await db.execute(
            select(User, OrganizationUser)
            .join(OrganizationUser, OrganizationUser.userId == User.id)
            .where(OrganizationUser.organizationId == organization_id, User.deletedAt.is_(None))
            .order_by(User.id)
        )
    ).all()
    return [
        {
            "userId": str(utilisateur.id),
            "email": utilisateur.email,
            "fullName": utilisateur.fullName,
            "status": utilisateur.status,
            "membreDepuis": appartenance.createdAt.isoformat(),
        }
        for utilisateur, appartenance in lignes
    ]


async def demander_export(db: AsyncSession, organization_id: uuid.UUID, demandeur_id: uuid.UUID) -> PortailExportJob:
    """Crée la demande en `export_requested`, trace la demande, commit, puis publie `ExportRequested`."""
    job = PortailExportJob(
        id=uuid.uuid4(),
        organizationId=organization_id,
        requestedBy=demandeur_id,
        perimetre=PERIMETRE_MEMBRES,
        statut=STATUT_REQUETE,
        contenu=None,
        expiresAt=None,
    )
    db.add(job)
    await record_audit_event(
        db,
        organization_id,
        demandeur_id,
        ACTION_DEMANDE,
        "export_job",
        job.id,
        "Demande d'export de données (périmètre membres).",
        {"perimetre": PERIMETRE_MEMBRES},
    )
    await db.commit()
    await db.refresh(job)
    await bus.publish(EVENEMENT_DEMANDE, exportId=str(job.id), organizationId=str(organization_id))
    return job


async def obtenir_job(db: AsyncSession, organization_id: uuid.UUID, export_id: uuid.UUID) -> PortailExportJob:
    """Export de l'organisation courante. 404 `export_not_found` si absent ou d'une autre organisation."""
    job = (
        await db.execute(
            select(PortailExportJob).where(
                PortailExportJob.id == export_id, PortailExportJob.organizationId == organization_id
            )
        )
    ).scalar_one_or_none()
    if job is None:
        raise AppError(code="export_not_found", message="Export introuvable.", status_code=404)
    return job


async def traiter_export(export_id: uuid.UUID) -> None:
    """Produit le contenu d'une demande et la passe à `ready` (traitement de fond, hors requête).

    Ouvre sa propre session : la requête qui l'a planifié est déjà terminée. Sans durée de vie
    configurée, la demande reste `export_requested` et rien n'est écrit (CA-5). Une demande déjà
    traitée ou inconnue est ignorée.
    """
    async with AsyncSessionLocal() as db:
        job = await db.get(PortailExportJob, export_id)
        if job is None or job.statut != STATUT_REQUETE:
            return
        duree = settings.EXPORT_EXPIRATION_SECONDS
        if duree is None:
            logger.warning("export %s non produit : durée de vie non configurée", export_id)
            return
        job.contenu = await _membres(db, job.organizationId)
        job.statut = STATUT_PRET
        job.expiresAt = maintenant() + timedelta(seconds=duree)
        await db.commit()
        organization_id = job.organizationId
        expire_a = job.expiresAt
    await bus.publish(EVENEMENT_PRET, exportId=str(export_id), organizationId=str(organization_id),
                      expiresAt=expire_a.isoformat())


async def _expirer(db: AsyncSession, job: PortailExportJob) -> None:
    """Purge le contenu et passe à `expired`. Publie `ExportExpired` une seule fois (CA-3, CA-5)."""
    deja_expire = job.statut == STATUT_EXPIRE
    job.contenu = None
    job.statut = STATUT_EXPIRE
    await db.commit()
    if not deja_expire:
        await bus.publish(EVENEMENT_EXPIRE, exportId=str(job.id), organizationId=str(job.organizationId))


async def telecharger(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, export_id: uuid.UUID
) -> PortailExportJob:
    """Export prêt et non expiré, journalisé. 409 `export_not_ready` avant `ready` ; 410 `export_expired`
    après `expiresAt`, avec purge du contenu."""
    job = await obtenir_job(db, organization_id, export_id)
    if job.statut == STATUT_REQUETE:
        raise AppError(code="export_not_ready", message="L'export n'est pas encore prêt.", status_code=409)
    if est_expire(job):
        await _expirer(db, job)
        raise AppError(code="export_expired", message="Export expiré.", status_code=410)
    await record_audit_event(
        db,
        organization_id,
        user_id,
        ACTION_TELECHARGEMENT,
        "export_job",
        job.id,
        "Téléchargement d'un export de données.",
    )
    await db.commit()
    return job
